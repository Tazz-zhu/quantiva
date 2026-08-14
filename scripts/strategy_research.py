#!/usr/bin/env python3
"""策略研究与防过拟合回测脚本
================================
流程：
1. 从本地 SQLite 加载真实交易所 K 线数据；
2. 数据切分：TRAIN(样本内) / TEST(样本外, 最后 1-train_ratio)，另有 Walk-Forward 滚动验证；
3. 在 TRAIN 上做并行网格搜索（目标 = Calmar，限制最少交易数）；
4. Walk-Forward：多窗口“窗口内训练→窗口外验证”，衡量泛化能力；
5. 最优参数在 TRAIN / TEST 上分别回测 + 参数敏感性分析（防过拟合诊断）；
6. 可选：用同一组最优参数对比其它周期（4h/1h），展示周期敏感性；
7. 输出 PNG 图表 + JSON + Markdown 报告。
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from quant.backtest.engine import BacktestEngine  # noqa: E402
from quant.config import load_config  # noqa: E402
from quant.data.storage import SQLiteStorage  # noqa: E402
from quant.report.chart import plot_backtest  # noqa: E402
from quant.risk.manager import RiskManager  # noqa: E402
from quant.strategy import create_strategy  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# 默认搜索网格（控制过拟合：参数空间适中、目标稳健）
DEFAULT_GRID = {
    "fast_ma": [10, 20, 30, 40],
    "slow_ma": [30, 50, 60, 100, 150],
    "entry_lookback": [10, 20, 30, 40],
    "exit_atr_mult": [2.0, 3.0, 4.0, 5.0],
    "min_atr_pct": [0.0, 0.2],
    "min_adx": [0.0, 24.0],
}

WF_LITE_GRID = {
    "fast_ma": [10, 20, 30],
    "slow_ma": [30, 60, 150],
    "entry_lookback": [10, 20, 30],
    "exit_atr_mult": [2.0, 3.0, 4.0],
    "min_atr_pct": [0.0, 0.2],
    "min_adx": [0.0, 24.0],
}


def expand_ranges(grid: dict) -> list[dict]:
    keys = list(grid.keys())
    return [dict(zip(keys, c)) for c in itertools.product(*[grid[k] for k in keys])]


def make_risk(cfg_risk: dict, direction: str) -> RiskManager:
    risk = RiskManager.from_config(cfg_risk)
    risk.trade_direction = direction
    return risk


def run_one(params: dict, data: pd.DataFrame, risk: RiskManager, bt_cfg: dict,
            symbol: str, strategy_name: str, min_trades: int):
    strategy = create_strategy(strategy_name, params)
    engine = BacktestEngine(
        strategy=strategy,
        data=data,
        initial_capital=float(bt_cfg.get("initial_capital", 10000)),
        fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
        slippage=float(bt_cfg.get("slippage", 0.0005)),
        risk=risk,
        symbol=symbol,
        funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
    )
    try:
        res = engine.run()
        m = res.metrics
        num = int(m.get("num_trades", 0))
        calmar = float(m.get("calmar", -999))
        if num < min_trades:
            return params, -999.0, dict(num_trades=num)
        return params, calmar, {
            "total_return": m.get("total_return"),
            "annual_return": m.get("annual_return"),
            "sharpe": m.get("sharpe"),
            "sortino": m.get("sortino"),
            "max_drawdown": m.get("max_drawdown"),
            "win_rate": m.get("win_rate"),
            "profit_factor": m.get("profit_factor"),
            "num_trades": num,
            "calmar": calmar,
            "sqn": m.get("sqn"),
            "final_equity": m.get("final_equity"),
            "exposure": m.get("exposure"),
        }
    except Exception as exc:  # noqa: BLE001
        return params, -999.0, {"error": str(exc)[:200]}


def _score_one(params, data, risk, bt_cfg, symbol, strategy_name, min_trades, objective):
    if objective == "min_half" and len(data) >= 200:
        half = len(data) // 2
        h_min = max(3, int(min_trades * 0.5))
        r1 = run_one(params, data.iloc[:half], risk, bt_cfg, symbol, strategy_name, h_min)
        r2 = run_one(params, data.iloc[half:], risk, bt_cfg, symbol, strategy_name, h_min)
        c1, c2 = r1[1], r2[1]
        target = min(c1, c2)
        extra = {"half1_calmar": c1, "half2_calmar": c2,
                 "half1_trades": r1[2].get("num_trades"), "half2_trades": r2[2].get("num_trades")}
        return params, target, extra
    return run_one(params, data, risk, bt_cfg, symbol, strategy_name, min_trades)


def grid_search(data: pd.DataFrame, grid: dict, risk: RiskManager, bt_cfg: dict,
                symbol: str, strategy_name: str, min_trades: int, workers: int,
                objective: str = "calmar") -> list[dict]:
    combos = expand_ranges(grid)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_score_one, c, data, risk, bt_cfg, symbol, strategy_name, min_trades, objective) for c in combos]
        for fut in as_completed(futures):
            params, target, extra = fut.result()
            results.append({"params": params, "target": target, **extra})
    results.sort(key=lambda r: r["target"], reverse=True)
    return results


def backtest_full(data: pd.DataFrame, params: dict, risk: RiskManager, bt_cfg: dict,
                  symbol: str, strategy_name: str):
    strategy = create_strategy(strategy_name, params)
    engine = BacktestEngine(
        strategy=strategy,
        data=data,
        initial_capital=float(bt_cfg.get("initial_capital", 10000)),
        fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
        slippage=float(bt_cfg.get("slippage", 0.0005)),
        risk=risk,
        symbol=symbol,
        funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
    )
    return engine.run()


def sensitivity(data: pd.DataFrame, base_params: dict, grid: dict, risk: RiskManager,
                bt_cfg: dict, symbol: str, strategy_name: str, min_trades: int) -> list[dict]:
    rows = []
    for key in base_params:
        if key not in grid:
            continue
        for val in grid[key]:
            p = dict(base_params)
            p[key] = val
            _, target, extra = run_one(p, data, risk, bt_cfg, symbol, strategy_name, min_trades)
            rows.append({"param": key, "value": val, "target": target, **extra})
    return rows


def plot_walkforward(wf_results: list, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(11, 5))
    for i, wf in enumerate(wf_results):
        eq = wf["equity"]
        norm = eq / eq.iloc[0]
        ax.plot(norm.index, norm.values, label=f"WF{i+1} OOS")
    ax.axhline(1.0, color="gray", lw=0.8, ls="--")
    ax.set_title("Walk-Forward Out-of-Sample Equity (Normalized)")
    ax.set_ylabel("Equity / Initial")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def plot_sensitivity(rows: list[dict], best_calmar: float, out_path: Path) -> Path:
    fig, axes = plt.subplots(1, len(set(r["param"] for r in rows)), figsize=(14, 3.6), squeeze=False)
    params = sorted(set(r["param"] for r in rows))
    for ax, param in zip(axes[0], params):
        sub = [r for r in rows if r["param"] == param]
        vals = [r["value"] for r in sub]
        tars = [r["target"] for r in sub]
        colors = ["#2E86AB" if v >= 0 else "#C44E52" for v in tars]
        ax.bar([str(v) for v in vals], tars, color=colors)
        ax.axhline(0, color="gray", lw=0.8)
        if best_calmar > 0:
            ax.axhline(best_calmar * 0.5, color="orange", lw=1.0, ls="--", label="50% best")
        ax.set_title(param)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3, axis="y")
    fig.suptitle("Parameter Sensitivity (TRAIN, Calmar)", y=1.02, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def fmt_pct(x):
    return "n/a" if x is None else f"{x * 100:.2f}%"


def fmt_num(x, digits=3):
    return "n/a" if x is None else f"{x:.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="策略研究与防过拟合回测")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--strategy", default="trend_flow")
    parser.add_argument("--direction", default="long_short", choices=["long_only", "long_short"])
    parser.add_argument("--out", default="reports/strategy_research")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--train-ratio", type=float, default=0.6, help="TRAIN 占比（样本内）")
    parser.add_argument("--wf-windows", type=int, default=4, help="Walk-Forward 窗口数")
    parser.add_argument("--min-trades", type=int, default=12)
    parser.add_argument("--fee", type=float, default=None, help="手续费率（覆盖配置）")
    parser.add_argument("--slippage", type=float, default=None, help="滑点（覆盖配置）")
    parser.add_argument("--compare-timeframes", default="4h,1h", help="用最优参数对比的其它周期，逗号分隔，空串关闭")
    parser.add_argument("--params-file", default=None, help="fixed params JSON file (robust quoting)")
    parser.add_argument("--params", default=None,
                        help='fixed params JSON, skip grid search (e.g. {"fast_ma":20})')
    parser.add_argument("--objective", default="calmar", choices=["calmar", "min_half"],
                        help="?????calmar=???Calmar?min_half=????/?????????Calmar??????")
    parser.add_argument("--quick", action="store_true", help="使用精简网格")
    args = parser.parse_args()

    cfg = load_config(args.config)
    bt_cfg = dict(cfg["backtest"])
    if args.fee is not None:
        bt_cfg["fee_rate"] = args.fee
    if args.slippage is not None:
        bt_cfg["slippage"] = args.slippage
    risk = make_risk(cfg["risk"], args.direction)

    storage = SQLiteStorage(cfg["data"]["storage_db"])
    df = storage.load_ohlcv(args.symbol, args.timeframe)
    storage.close()
    if len(df) < 300:
        print(f"数据不足：{len(df)} 根 K 线（{args.symbol} {args.timeframe}）", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = WF_LITE_GRID if args.quick else DEFAULT_GRID

    fixed_params = None
    if args.params_file:
        fixed_params = json.loads(Path(args.params_file).read_text(encoding='utf-8'))
    elif args.params:
        fixed_params = json.loads(args.params)
    split = int(len(df) * args.train_ratio)
    train_df = df.iloc[:split]
    test_df = df.iloc[split:]
    print(f"数据：{args.symbol} {args.timeframe} 共 {len(df)} 根 | "
          f"TRAIN {len(train_df)}（{df.index[0]:%Y-%m-%d}） | TEST {len(test_df)}（{test_df.index[0]:%Y-%m-%d}）")

    # ---------- 1) TRAIN grid search ----------
    if fixed_params is not None:
        print(f"\n[1/5] using fixed params (skip grid search): {fixed_params}")
        search = []
        best = {"params": fixed_params, "target": 0.0}
    else:
        print(f"\n[1/5] TRAIN grid search ({len(expand_ranges(grid))} combos, workers={args.workers}, direction={args.direction})...")
        search = grid_search(train_df, grid, risk, bt_cfg, args.symbol, args.strategy, args.min_trades, args.workers, args.objective)
        best = search[0]
    best_params = dict(best["params"])

    # ---------- 2) Walk-Forward ----------
    print("\n[2/5] Walk-Forward (" + ("fixed-params OOS segments" if fixed_params is not None else "re-optimize per window") + ")...")
    wf_results = []
    wf_grid = WF_LITE_GRID if args.quick else grid
    n = len(df)
    wf_fracs = [(w + 1) / args.wf_windows for w in range(args.wf_windows)]
    wf_fracs[-1] = 1.0
    wf_skipped = 0
    for w, frac in enumerate(wf_fracs):
        end = int(n * frac)
        win = df.iloc[:end]
        wsplit = int(len(win) * 0.7)
        wtrain, wtest = win.iloc[:wsplit], win.iloc[wsplit:]
        if len(wtest) < 100:
            wf_skipped += 1
            continue
        if fixed_params is not None:
            sp = dict(fixed_params)
            res = backtest_full(wtest, sp, risk, bt_cfg, args.symbol, args.strategy)
        else:
            wf_min = max(4, int(args.min_trades * len(wtrain) / max(len(train_df), 1)))
            s = grid_search(wtrain, wf_grid, risk, bt_cfg, args.symbol, args.strategy, wf_min, args.workers, "calmar")
            sp = dict(s[0]["params"])
            res = backtest_full(wtest, sp, risk, bt_cfg, args.symbol, args.strategy)
        wf_results.append({
            "window": w + 1,
            "range": f"{wtest.index[0]:%Y-%m-%d} ~ {wtest.index[-1]:%Y-%m-%d}",
            "params": sp,
            "metrics": res.metrics,
            "equity": res.equity_curve,
        })
        m = res.metrics
        print(f"  WF{w+1} [{wf_results[-1]['range']}] params={sp}  ret={fmt_pct(m.get('total_return'))}  "
              f"sharpe={fmt_num(m.get('sharpe'))}  mdd={fmt_pct(m.get('max_drawdown'))}  calmar={fmt_num(m.get('calmar'))}")
    if wf_skipped:
        print(f"  (skipped {wf_skipped} windows with test segment < 100 bars)")
    # ---------- 3) 最优参数：TRAIN / TEST 最终回测 ----------
    print(f"\n[3/5] 最优参数在 TRAIN / TEST 上最终回测：{best_params}")
    res_train = backtest_full(train_df, best_params, risk, bt_cfg, args.symbol, args.strategy)
    res_test = backtest_full(test_df, best_params, risk, bt_cfg, args.symbol, args.strategy)
    m_train, m_test = res_train.metrics, res_test.metrics
    for label, m in (("TRAIN", m_train), ("TEST", m_test)):
        print(f"{label}: ret={fmt_pct(m.get('total_return'))} ann={fmt_pct(m.get('annual_return'))} "
              f"sharpe={fmt_num(m.get('sharpe'))} mdd={fmt_pct(m.get('max_drawdown'))} "
              f"win={fmt_pct(m.get('win_rate'))} trades={m.get('num_trades')} calmar={fmt_num(m.get('calmar'))}")

    # ---------- 4) 参数敏感性 ----------
    print(f"\n[4/5] 参数敏感性分析（TRAIN）...")
    sens_min = max(3, int(args.min_trades * 0.5))
    sens = sensitivity(train_df, best_params, grid, risk, bt_cfg, args.symbol, args.strategy, sens_min)
    for row in sens:
        print(f"  {row['param']:<16} {row['value']:<6} calmar={row['target']:.3f}  ret={fmt_pct(row.get('total_return'))}  trades={row.get('num_trades')}")

    # ---------- 5) 多周期对比 + 图表 + 报告 ----------
    print("\n[5/5] 多周期对比与报告生成...")
    compares = []
    for tf in [x.strip() for x in (args.compare_timeframes or "").split(",") if x.strip()]:
        d = storage_load(args.config, args.symbol, tf)
        if d is None or len(d) < 200:
            continue
        r = backtest_full(d, best_params, risk, bt_cfg, args.symbol, args.strategy)
        compares.append({"timeframe": tf, "rows": len(d), "metrics": r.metrics,
                         "buy_hold": float(d["close"].iloc[-1] / d["close"].iloc[0] - 1)})
        m = r.metrics
        print(f"  {tf}: ret={fmt_pct(m.get('total_return'))} sharpe={fmt_num(m.get('sharpe'))} "
              f"mdd={fmt_pct(m.get('max_drawdown'))} trades={m.get('num_trades')} (B&H={compares[-1]['buy_hold']:+.2%})")

    best_calmar = float(m_train.get("calmar", 0))
    oos_calmar = float(m_test.get("calmar", 0))
    is_sharpe = float(m_train.get("sharpe", 0))
    oos_sharpe = float(m_test.get("sharpe", 0))
    sens_pos = sum(1 for r in sens if r["target"] > 0)
    sens_half = sum(1 for r in sens if best_calmar > 0 and r["target"] >= best_calmar * 0.5)
    wf_pos = sum(1 for w in wf_results if w["metrics"].get("total_return", -1) > 0)
    wf_sharpe_pos = sum(1 for w in wf_results if (w["metrics"].get("sharpe") or 0) > 0)

    chart_is = plot_backtest(res_train.data, res_train.equity_curve, res_train.trades, out_dir / "backtest_train.png")
    chart_test = plot_backtest(res_test.data, res_test.equity_curve, res_test.trades, out_dir / "backtest_test.png")
    chart_wf = plot_walkforward(wf_results, out_dir / "walkforward_oos.png")
    chart_sens = plot_sensitivity(sens, best_calmar, out_dir / "sensitivity.png")

    def clean(v):
        if isinstance(v, pd.Timestamp):
            return str(v)
        if isinstance(v, float) and v != v:
            return None
        return v

    report = {
        "meta": {
            "symbol": args.symbol, "timeframe": args.timeframe, "strategy": args.strategy,
            "direction": args.direction, "objective": args.objective, "rows": len(df), "train_rows": len(train_df),
            "test_rows": len(test_df), "train_start": str(df.index[0]),
            "train_end": str(train_df.index[-1]), "test_start": str(test_df.index[0]),
            "test_end": str(df.index[-1]), "fee_rate": bt_cfg.get("fee_rate"),
            "slippage": bt_cfg.get("slippage"),
        },
        "best_params": best_params,
        "top10_train": search[:10],
        "train_metrics": {k: clean(v) for k, v in m_train.items()},
        "test_metrics": {k: clean(v) for k, v in m_test.items()},
        "walkforward": [
            {"window": w["window"], "range": w["range"], "params": w["params"],
             "metrics": {k: clean(v) for k, v in w["metrics"].items()}}
            for w in wf_results
        ],
        "sensitivity": [{k: clean(v) for k, v in r.items()} for r in sens],
        "compare_timeframes": [
            {"timeframe": c["timeframe"], "rows": c["rows"], "buy_hold": c["buy_hold"],
             "metrics": {k: clean(v) for k, v in c["metrics"].items()}}
            for c in compares
        ],
        "overfit_diagnostics": {
            "is_sharpe": is_sharpe,
            "oos_sharpe": oos_sharpe,
            "oos_is_sharpe_ratio": (oos_sharpe / is_sharpe) if is_sharpe > 0 else None,
            "is_calmar": best_calmar,
            "oos_calmar": oos_calmar,
            "is_annual_return": m_train.get("annual_return"),
            "oos_annual_return": m_test.get("annual_return"),
            "oos_excess_vs_buyhold": m_test.get("excess_return"),
            "sensitivity_positive_ratio": sens_pos / len(sens) if sens else None,
            "sensitivity_half_best_ratio": sens_half / len(sens) if sens else None,
            "wf_positive_windows": f"{wf_pos}/{len(wf_results)}",
            "wf_sharpe_positive_windows": f"{wf_sharpe_pos}/{len(wf_results)}",
            "wf_avg_oos_annual": float(pd.Series([w["metrics"].get("annual_return") or 0 for w in wf_results]).mean()),
            "wf_avg_oos_sharpe": float(pd.Series([w["metrics"].get("sharpe") or 0 for w in wf_results]).mean()),
            "wf_avg_oos_mdd": float(pd.Series([w["metrics"].get("max_drawdown") or 0 for w in wf_results]).mean()),
        },
        "charts": {
            "train": str(chart_is.name), "test": str(chart_test.name),
            "walkforward": str(chart_wf.name), "sensitivity": str(chart_sens.name),
        },
    }
    (out_dir / "research.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        f"# 策略研究与回测报告 —— {args.strategy} @ {args.symbol} {args.timeframe}",
        "",
        f"- 数据范围：{df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d}（{len(df)} 根 K 线）",
        f"- 切分：TRAIN（样本内）{len(train_df)} 根 / TEST（样本外）{len(test_df)} 根",
        f"- 方向：{args.direction}；成本：费率 {bt_cfg['fee_rate']}，滑点 {bt_cfg['slippage']}，杠杆 {risk.leverage}，仓位上限 {risk.max_position_pct:.0%}",
        "",
        "## 1. 最优参数（TRAIN 网格搜索，目标 Calmar）",
        "",
        "```json",
        json.dumps(best_params, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 2. 样本内 / 样本外表现",
        "",
        "| 指标 | TRAIN（样本内） | TEST（样本外） |",
        "|---|---|---|",
        f"| 总收益 | {fmt_pct(m_train.get('total_return'))} | {fmt_pct(m_test.get('total_return'))} |",
        f"| 年化收益 | {fmt_pct(m_train.get('annual_return'))} | {fmt_pct(m_test.get('annual_return'))} |",
        f"| 买入持有 | {fmt_pct(m_train.get('buy_hold_return'))} | {fmt_pct(m_test.get('buy_hold_return'))} |",
        f"| 夏普 | {fmt_num(m_train.get('sharpe'))} | {fmt_num(m_test.get('sharpe'))} |",
        f"| 索提诺 | {fmt_num(m_train.get('sortino'))} | {fmt_num(m_test.get('sortino'))} |",
        f"| 最大回撤 | {fmt_pct(m_train.get('max_drawdown'))} | {fmt_pct(m_test.get('max_drawdown'))} |",
        f"| 胜率 | {fmt_pct(m_train.get('win_rate'))} | {fmt_pct(m_test.get('win_rate'))} |",
        f"| 盈亏比 | {fmt_num(m_train.get('profit_factor'))} | {fmt_num(m_test.get('profit_factor'))} |",
        f"| 交易数 | {m_train.get('num_trades')} | {m_test.get('num_trades')} |",
        f"| Calmar | {fmt_num(m_train.get('calmar'))} | {fmt_num(m_test.get('calmar'))} |",
        f"| SQN | {fmt_num(m_train.get('sqn'))} | {fmt_num(m_test.get('sqn'))} |",
        "",
        f"![样本内回测](backtest_train.png)",
        f"![样本外回测](backtest_test.png)",
        "",
        "## 3. Walk-Forward " + ("固定参数逐段样本外验证" if fixed_params is not None else "每窗口重新选参") + "",
        "",
        "| 窗口 | 区间 | 选中参数 | 总收益 | 夏普 | 最大回撤 |",
        "|---|---|---|---|---|---|",
    ]
    for w in wf_results:
        lines.append(
            f"| WF{w['window']} | {w['range']} | {json.dumps(w['params'], ensure_ascii=False)} | "
            f"{fmt_pct(w['metrics'].get('total_return'))} | {fmt_num(w['metrics'].get('sharpe'))} | "
            f"{fmt_pct(w['metrics'].get('max_drawdown'))} |"
        )
    lines += [
        "",
        f"![Walk-Forward 样本外净值](walkforward_oos.png)",
        "",
        "## 4. 过拟合诊断",
        "",
        f"- 样本内 Sharpe：{is_sharpe:.3f}；样本外 Sharpe：{oos_sharpe:.3f}"
        f"（比值 {(oos_sharpe / is_sharpe if is_sharpe > 0 else float('nan')):.2f}）",
        f"- 样本内 Calmar：{best_calmar:.3f}；样本外 Calmar：{oos_calmar:.3f}",
        f"- 参数敏感性：{len(sens)} 个邻域组合中 {sens_pos} 个为正（{sens_pos / len(sens):.0%}），"
        f"{sens_half} 个达到最优 Calmar 的 50% 以上",
        f"- Walk-Forward：{len(wf_results)} 个窗口样本外 {wf_pos} 个正收益、{wf_sharpe_pos} 个正夏普；"
        f"平均年化 {report['overfit_diagnostics']['wf_avg_oos_annual']:.2%}，平均夏普 {report['overfit_diagnostics']['wf_avg_oos_sharpe']:.3f}",
        "",
        "> 结论标准：样本外表现是否延续样本内收益、参数是否处于“平台”而非“尖峰”、Walk-Forward 是否多数窗口为正，三者共同判断是否存在过拟合。",
        "",
        f"![参数敏感性](sensitivity.png)",
        "",
    ]
    if compares:
        lines += [
            "## 5. 同一参数跨周期对比",
            "",
            "| 周期 | K 线数 | 总收益 | 夏普 | 最大回撤 | 交易数 | 买入持有 |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in compares:
            m = c["metrics"]
            lines.append(
                f"| {c['timeframe']} | {c['rows']} | {fmt_pct(m.get('total_return'))} | "
                f"{fmt_num(m.get('sharpe'))} | {fmt_pct(m.get('max_drawdown'))} | "
                f"{m.get('num_trades')} | {c['buy_hold']:+.2%} |"
            )
        lines.append("")
    (out_dir / "strategy_research.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n完成。报告输出目录：{out_dir.resolve()}")
    print(f"  JSON      : {out_dir / 'research.json'}")
    print(f"  Markdown  : {out_dir / 'strategy_research.md'}")


def storage_load(config_path: str, symbol: str, timeframe: str):
    """独立加载数据库（重新打开连接，避免线程问题）。"""
    try:
        cfg = load_config(config_path)
        s = SQLiteStorage(cfg["data"]["storage_db"])
        d = s.load_ohlcv(symbol, timeframe)
        s.close()
        return d
    except Exception:
        return None


if __name__ == "__main__":
    main()