"""深度分析：月度收益、交易统计、回撤分析等。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.backtest.engine import BacktestResult

REASON_LABELS = {"signal": "信号", "stop_loss": "止损", "take_profit": "止盈", "eod": "期末", "margin_call": "强平"}


def _streaks(pnls: list[float]) -> dict:
    best_win = cur_win = 0
    worst_loss = cur_loss = 0
    for p in pnls:
        if p > 0:
            cur_win += 1
            cur_loss = 0
            best_win = max(best_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            worst_loss = max(worst_loss, cur_loss)
    return {"max_consecutive_wins": best_win, "max_consecutive_losses": worst_loss}


def _drawdown_segments(equity: pd.Series) -> list[dict]:
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    segments = []
    start = None
    seg_min = 0.0
    seg_min_ts = None
    for ts, v in dd.items():
        if v < 0:
            if start is None:
                start = ts
            if v < seg_min:
                seg_min = v
                seg_min_ts = ts
        else:
            if start is not None:
                segments.append({"start": start, "end": ts, "depth": seg_min, "peak_time": seg_min_ts})
                start = None
                seg_min = 0.0
    if start is not None:
        segments.append({"start": start, "end": equity.index[-1], "depth": seg_min, "peak_time": seg_min_ts})
    return segments


def _monthly_consistency(monthly: list[dict]) -> dict:
    """月度一致性：盈利月份占比、最佳/最差月份、最大连亏月份数。"""
    vals = [m["return"] for m in monthly]
    if not vals:
        return {"positive_months_pct": 0.0, "best_month": None, "worst_month": None, "max_consecutive_losing_months": 0}
    positive = sum(1 for v in vals if v > 0)
    best = max(monthly, key=lambda m: m["return"])
    worst = min(monthly, key=lambda m: m["return"])
    cur = 0
    max_streak = 0
    for v in vals:
        if v <= 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    return {
        "positive_months_pct": positive / len(vals),
        "best_month": {"month": best["month"], "return": best["return"]},
        "worst_month": {"month": worst["month"], "return": worst["return"]},
        "max_consecutive_losing_months": max_streak,
    }


def _rolling_stability(equity: pd.Series, periods_per_year: int) -> dict:
    """滚动窗口稳定性：滚动夏普 / 波动 / 最大回撤的分布与序列。"""
    rets = equity.pct_change().dropna()
    if len(rets) < 30:
        return {"available": False, "window": 0}
    window = max(20, min(90, len(rets) // 3))
    roll_mean = rets.rolling(window).mean()
    roll_std = rets.rolling(window).std()
    roll_sharpe = (roll_mean / roll_std * np.sqrt(periods_per_year)).dropna()
    roll_vol = (roll_std * np.sqrt(periods_per_year)).dropna()
    roll_max_dd = equity.rolling(window).apply(
        lambda x: float((x / x.cummax() - 1.0).min()), raw=False
    ).dropna()
    return {
        "available": True,
        "window": window,
        "periods_per_year": periods_per_year,
        "sharpe": {
            "mean": float(roll_sharpe.mean()) if len(roll_sharpe) else 0.0,
            "std": float(roll_sharpe.std()) if len(roll_sharpe) > 1 else 0.0,
            "min": float(roll_sharpe.min()) if len(roll_sharpe) else 0.0,
            "max": float(roll_sharpe.max()) if len(roll_sharpe) else 0.0,
            "last": float(roll_sharpe.iloc[-1]) if len(roll_sharpe) else 0.0,
            "positive_pct": float((roll_sharpe > 0).mean()) if len(roll_sharpe) else 0.0,
            "series": [[int(ts.timestamp() * 1000), float(v)] for ts, v in roll_sharpe.items()],
        },
        "volatility_mean": float(roll_vol.mean()) if len(roll_vol) else 0.0,
        "max_drawdown_mean": float(roll_max_dd.mean()) if len(roll_max_dd) else 0.0,
        "max_drawdown_worst": float(roll_max_dd.min()) if len(roll_max_dd) else 0.0,
        "stability_score": float(roll_sharpe.mean() / roll_sharpe.std()) if len(roll_sharpe) > 1 and roll_sharpe.std() > 0 else 0.0,
    }


def analyze(result: BacktestResult, timeframe: str = "1h") -> dict:
    equity = result.equity_curve.astype(float)
    trades = result.trades
    metrics = result.metrics
    initial = metrics["initial_capital"]

    monthly_series = equity.resample("ME").last().pct_change().dropna()
    yearly_series = equity.resample("YE").last().pct_change().dropna()
    monthly = [{"month": ts.strftime("%Y-%m"), "return": float(v)} for ts, v in monthly_series.items()]
    yearly = [{"year": ts.strftime("%Y"), "return": float(v)} for ts, v in yearly_series.items()]

    years = sorted({m["month"][:4] for m in monthly})
    months_idx = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    matrix = {y: {m: None for m in months_idx} for y in years}
    for m in monthly:
        y, mm = m["month"].split("-")
        matrix[y][mm] = m["return"]

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    by_side = {}
    by_reason = {}
    for t in trades:
        by_side.setdefault(t.side, []).append(t.pnl)
        by_reason.setdefault(t.reason, []).append(t.pnl)

    def summarize(group: dict) -> dict:
        out = {}
        for k, vals in group.items():
            label = REASON_LABELS.get(k, k)
            out[label] = {
                "count": len(vals),
                "total": float(sum(vals)),
                "avg": float(np.mean(vals)) if vals else 0.0,
                "win_rate": float(sum(1 for v in vals if v > 0) / len(vals)) if vals else 0.0,
            }
        return out

    holding_hours = [(t.exit_time - t.entry_time).total_seconds() / 3600.0 for t in trades] if trades else [0.0]

    segments = _drawdown_segments(equity)
    depths = [s["depth"] for s in segments]
    dd_info = {
        "max_drawdown": metrics.get("max_drawdown", 0.0),
        "num_drawdowns": len(segments),
        "avg_drawdown": float(np.mean(depths)) if depths else 0.0,
        "longest_drawdown_days": float(max((s["end"] - s["start"]).total_seconds() for s in segments) / 86400.0) if segments else 0.0,
        "current_drawdown": float(equity.iloc[-1] / equity.cummax().iloc[-1] - 1.0),
    }

    annual_return = metrics.get("annual_return", 0.0)
    mdd = abs(metrics.get("max_drawdown", 0.0)) or 1e-9
    calmar = annual_return / mdd if mdd else 0.0

    return {
        "period": {"start": str(equity.index[0]), "end": str(equity.index[-1]), "bars": metrics.get("periods", 0), "timeframe": timeframe},
        "performance": {
            "total_return": metrics.get("total_return"),
            "annual_return": metrics.get("annual_return"),
            "buy_hold_return": metrics.get("buy_hold_return"),
            "excess_return": metrics.get("excess_return"),
            "alpha_annual": metrics.get("alpha_annual"),
            "beta": metrics.get("beta"),
            "sharpe": metrics.get("sharpe"),
            "sortino": metrics.get("sortino"),
            "volatility": metrics.get("volatility"),
            "downside_dev": metrics.get("downside_dev"),
            "var95": metrics.get("var95"),
            "cvar95": metrics.get("cvar95"),
            "ulcer": metrics.get("ulcer"),
            "underwater_time_pct": metrics.get("underwater_time_pct"),
            "max_run_up": metrics.get("max_run_up"),
            "calmar": calmar,
            "max_drawdown": metrics.get("max_drawdown"),
        },
        "monthly_returns": monthly,
        "yearly_returns": yearly,
        "monthly_matrix": matrix,
        "monthly_consistency": _monthly_consistency(monthly),
        "trades": {
            "total": len(trades),
            "win_rate": metrics.get("win_rate"),
            "profit_factor": metrics.get("profit_factor"),
            "avg_win": metrics.get("avg_win"),
            "avg_loss": metrics.get("avg_loss"),
            "avg_win_loss_ratio": metrics.get("avg_win_loss_ratio"),
            "max_win": float(max(wins)) if wins else 0.0,
            "max_loss": float(min(losses)) if losses else 0.0,
            "avg_holding_hours": float(np.mean(holding_hours)),
            "streaks": _streaks(pnls),
            "by_side": summarize(by_side),
            "by_reason": summarize(by_reason),
            "avg_trade_return": metrics.get("avg_trade_return"),
            "avg_risk": metrics.get("avg_risk"),
            "avg_r": metrics.get("avg_r"),
            "expectancy_r": metrics.get("expectancy_r"),
            "r_positive_pct": metrics.get("r_positive_pct"),
            "max_r": metrics.get("max_r"),
            "min_r": metrics.get("min_r"),
            "total_fees": metrics.get("total_fees"),
            "total_pnl": metrics.get("total_pnl"),
        },
        "drawdown": dd_info,
        "exposure": metrics.get("exposure"),
        "rolling_stability": _rolling_stability(equity, int(metrics.get("periods_per_year", 8760) or 8760)),
    }
