"""滚动样本外（Walk-Forward / 滚动前推）验证 —— 严谨抗过拟合核心工具。

思想：把历史数据切分成多个连续的"训练段 → 样本外段"折叠，
每折只在训练段内做参数寻优，再在紧邻的样本外段验证。
只有多折样本外一致表现好的参数才有资格上实盘。

设计参考 freqtrade 社区 walk-forward 方法论：
- 每折训练窗口可滚动（rolling）或扩展（expanding）
- 训练段与样本外段之间无重叠
- 汇总全部样本外段的拼接权益与指标，避免"只挑一段好运"
"""
from __future__ import annotations

import itertools
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from quant.backtest.engine import BacktestEngine
from quant.config import exchange_proxy, load_config
from quant.data.fetcher import ExchangeDataFetcher
from quant.data.storage import SQLiteStorage
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy
from quant.rigor.losses import compute_loss
from quant.rigor.significance import bootstrap_p_value, strategy_verdict


def expand_ranges(param_ranges: dict) -> list[dict]:
    keys = list(param_ranges.keys())
    if not keys:
        return [{}]
    combos = list(itertools.product(*[param_ranges[k] for k in keys]))
    return [dict(zip(keys, c)) for c in combos]


def load_ohlcv_for_analysis(config_path: str, data_cfg: dict) -> pd.DataFrame:
    """加载分析用 K 线（与 Optimizer 一致：仅交易所真实数据 / 本地库）。"""
    source = data_cfg.get("source", "exchange")
    symbol = data_cfg.get("symbol", "BTC/USDT")
    timeframe = data_cfg.get("timeframe", "4h")
    days = int(data_cfg.get("days", 300))
    if source == "synthetic":
        raise ValueError("合成数据已停用，系统仅使用交易所真实行情")
    if source == "db":
        storage = SQLiteStorage(data_cfg.get("storage_db", "data/ohlcv.db"))
        try:
            df = storage.load_ohlcv(symbol, timeframe)
        finally:
            storage.close()
        if df.empty:
            raise ValueError("本地数据库无数据")
        return df
    fetcher = ExchangeDataFetcher(
        data_cfg.get("exchange", "binance"),
        proxy=exchange_proxy(load_config(config_path)),
    )
    since = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) - days * 86_400_000
    return fetcher.fetch_ohlcv(symbol, timeframe, since=since)


@dataclass
class WalkForwardFold:
    """单个折叠：训练段寻优 → 样本外段验证。"""

    index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_params: dict
    best_loss: float
    is_metrics: dict
    oos_metrics: dict
    oos_trades: int


def _backtest_one(
    strategy_name: str,
    params: dict,
    df: pd.DataFrame,
    risk_cfg: dict,
    bt_cfg: dict,
    symbol: str,
) -> tuple[dict, object]:
    params = dict(params)
    direction = params.pop("direction", None)
    strategy = create_strategy(strategy_name, params)
    risk = RiskManager.from_config(risk_cfg or {})
    if direction:
        risk.trade_direction = direction
    engine = BacktestEngine(
        strategy=strategy,
        data=df,
        initial_capital=float(bt_cfg.get("initial_capital", 10000)),
        fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
        slippage=float(bt_cfg.get("slippage", 0.0005)),
        risk=risk,
        symbol=symbol,
        funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
    )
    result = engine.run()
    return params, result


def run_walkforward(
    config_path: str,
    strategy_name: str,
    param_ranges: dict,
    data_cfg: dict,
    risk_cfg: dict | None = None,
    bt_cfg: dict | None = None,
    loss: str = "sharpe",
    n_splits: int = 4,
    train_ratio: float = 0.6,
    expanding: bool = False,
    min_trades: int = 5,
    max_combos: int = 100,
    workers: int = 4,
    progress: Callable[[int, int], None] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """执行滚动样本外验证。

    参数
    ----
    n_splits:    折叠数（每折一个训练段+样本外段）
    train_ratio: 每折训练段占"训练+样本外"的比例
    expanding:   True=训练窗口逐步扩展；False=固定长度滚动
    loss:        寻优损失函数名（见 quant.rigor.losses）
    """
    combos = expand_ranges(param_ranges)
    if len(combos) > max_combos:
        combos = combos[:max_combos]
    if not combos:
        raise ValueError("参数网格为空")

    cfg = load_config(config_path)
    bt = {**cfg.get("backtest", {}), **(bt_cfg or {})}
    risk = risk_cfg or cfg.get("risk", {})
    symbol = data_cfg.get("symbol", "BTC/USDT")
    df = load_ohlcv_for_analysis(config_path, data_cfg)
    df = df.sort_index()
    n = len(df)
    if n < 200:
        raise ValueError(f"数据量不足：仅 {n} 根 K 线，滚动样本外至少需要 200 根")
    n_splits = max(2, min(int(n_splits), 8))
    train_ratio = max(0.3, min(0.85, float(train_ratio)))

    # 构造折叠边界：每折训练段长度 + 样本外段长度
    folds: list[tuple[int, int, int, int]] = []
    if expanding:
        # 扩展窗口：训练段起点固定，终点递增
        first_train_end = int(n * (0.5 / n_splits))
        oos_len = int((n - first_train_end) / n_splits)
        for k in range(n_splits):
            tr_end = first_train_end + k * oos_len
            te_start = tr_end
            te_end = min(n, te_start + oos_len)
            folds.append((0, tr_end, te_start, te_end))
    else:
        # 滚动窗口：每折固定训练段长度
        seg_len = int(n / (n_splits * train_ratio + (1 - train_ratio) * n_splits))
        train_len = int(seg_len * train_ratio)
        oos_len = seg_len - train_len
        if oos_len < 20:
            oos_len = max(20, int(n / (n_splits + 2)))
            train_len = max(int(n / n_splits) - oos_len, 50)
        offset = n - (train_len + oos_len) * n_splits
        start = max(0, offset)
        for k in range(n_splits):
            tr_start = start + k * (train_len + oos_len)
            tr_end = tr_start + train_len
            te_start = tr_end
            te_end = min(n, te_start + oos_len)
            if te_end - te_start < 10 or tr_end - tr_start < 50:
                continue
            folds.append((tr_start, tr_end, te_start, te_end))

    if len(folds) < 2:
        raise ValueError("折叠数量不足，请减少 n_splits 或增加数据量")

    fold_results: list[WalkForwardFold] = []
    done = 0
    lock = threading.Lock()

    def run_fold(fold: tuple[int, int, int, int], idx: int) -> WalkForwardFold | None:
        tr_s, tr_e, te_s, te_e = fold
        train_df = df.iloc[tr_s:tr_e]
        test_df = df.iloc[te_s:te_e]

        # 训练段网格寻优
        best_params: dict | None = None
        best_loss = float("inf")
        is_metrics: dict | None = None
        for combo in combos:
            try:
                p, result = _backtest_one(strategy_name, combo, train_df, risk, bt, symbol)
                if int(result.metrics.get("num_trades", 0)) < min_trades:
                    continue
                loss_val = compute_loss(loss, result)
                if loss_val < best_loss:
                    best_loss = loss_val
                    best_params = dict(combo)
                    is_metrics = result.metrics
            except Exception:  # noqa: BLE001
                continue
        if best_params is None:
            return None

        # 样本外验证
        try:
            _, result2 = _backtest_one(strategy_name, best_params, test_df, risk, bt, symbol)
            return WalkForwardFold(
                index=idx,
                train_start=train_df.index[0],
                train_end=train_df.index[-1],
                test_start=test_df.index[0],
                test_end=test_df.index[-1],
                best_params=best_params,
                best_loss=best_loss,
                is_metrics=is_metrics or {},
                oos_metrics=result2.metrics,
                oos_trades=int(result2.metrics.get("num_trades", 0)),
            )
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(run_fold, f, i): i for i, f in enumerate(folds)}
        for fut in as_completed(futures):
            res = fut.result()
            with lock:
                if res is not None:
                    fold_results.append(res)
                done += 1
                if progress:
                    progress(done, len(folds))

    fold_results.sort(key=lambda f: f.index)
    if not fold_results:
        return {"error": "所有折叠均未找到满足最小交易数的参数组合", "folds": []}

    # 汇总：拼接全部样本外段权益
    oos_metrics_combined: dict | None = None
    oos_returns: list[float] = []
    try:
        segments = []
        for f in fold_results:
            # 重新跑一次最优参数以取权益曲线（保证与指标一致）
            p, result = _backtest_one(strategy_name, f.best_params, df.loc[f.test_start:f.test_end], risk, bt, symbol)
            segments.append(result.equity_curve)
            oos_returns.extend(result.equity_curve.pct_change().dropna().tolist())
        combined = pd.concat(segments)
        # 拼接权益曲线需按顺序首尾相连（每段从上一段终值开始）
        chain = []
        last = float(bt.get("initial_capital", 10000))
        for seg in segments:
            seg2 = seg / seg.iloc[0] * last
            chain.append(seg2)
            last = float(seg2.iloc[-1])
        combined_equity = pd.concat(chain)
        from quant.analytics.metrics import compute_metrics
        oos_metrics_combined = compute_metrics(
            combined_equity,
            [],
            float(bt.get("initial_capital", 10000)),
            periods_per_year=_periods_per_year(df),
            buy_hold_return=float(df["close"].iloc[-1] / df["close"].iloc[0] - 1.0),
        )
        # 交易级指标：汇总各折样本外 trades
        all_trades = []
        for f in fold_results:
            _, result = _backtest_one(strategy_name, f.best_params, df.loc[f.test_start:f.test_end], risk, bt, symbol)
            all_trades.extend(result.trades)
        if all_trades:
            oos_metrics_combined = compute_metrics(
                combined_equity, all_trades, float(bt.get("initial_capital", 10000)),
                periods_per_year=_periods_per_year(df),
            )
    except Exception:  # noqa: BLE001
        oos_metrics_combined = None

    # 显著性
    significance = None
    if oos_returns and len(oos_returns) >= 20:
        significance = bootstrap_p_value(oos_returns, n_boot=1000, seed=seed,
                                         periods_per_year=_periods_per_year(df))

    # 参数稳定性：各折最优参数是否一致
    param_keys = list(param_ranges.keys())
    best_param_sets = [tuple(sorted(f.best_params.items())) for f in fold_results]
    distinct = len(set(best_param_sets))
    stability = {
        "distinct_params": distinct,
        "total_folds": len(fold_results),
        "param_consistency": round(1.0 - (distinct - 1) / max(1, len(fold_results) - 1), 4) if len(fold_results) > 1 else 1.0,
        "verdict": "各折最优参数一致，稳定性好" if distinct == 1 else (
            "各折最优参数存在差异，需人工复核" if distinct <= 2 else "各折最优参数差异大，过拟合风险高"
        ),
    }

    verdict = strategy_verdict(None, oos_metrics_combined, significance, stability)

    return {
        "strategy": strategy_name,
        "loss": loss,
        "n_splits": n_splits,
        "expanding": expanding,
        "total_combos": len(combos),
        "folds": [
            {
                "index": f.index,
                "train": [str(f.train_start), str(f.train_end)],
                "test": [str(f.test_start), str(f.test_end)],
                "best_params": f.best_params,
                "best_loss": round(f.best_loss, 4),
                "is_metrics": f.is_metrics,
                "oos_metrics": f.oos_metrics,
                "oos_trades": f.oos_trades,
            }
            for f in fold_results
        ],
        "oos_metrics_combined": oos_metrics_combined,
        "significance": significance,
        "stability": stability,
        "verdict": verdict,
    }


def _periods_per_year(df: pd.DataFrame) -> int:
    if len(df) > 1:
        seconds = df.index.to_series().diff().dt.total_seconds().median()
        if seconds and seconds > 0:
            return max(int(round(365 * 24 * 3600 / seconds)), 1)
    return 8760
