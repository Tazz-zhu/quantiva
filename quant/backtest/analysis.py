"""回测深度分析（freqtrade backtest breakdown 移植）。

对已平仓交易按维度聚合：平仓原因 / 月份 / 星期 / 小时，
输出各分组的交易数、盈亏、胜率、平均收益等，帮助定位策略收益来源。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from quant.backtest.engine import Trade


def _trades_frame(trades: list[Trade]) -> pd.DataFrame:
    rows = []
    for t in trades:
        rows.append(
            {
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "side": t.side,
                "pnl": t.pnl,
                "return_pct": t.return_pct,
                "reason": t.reason,
                "fees": t.fees,
                "initial_risk": t.initial_risk,
            }
        )
    return pd.DataFrame(rows)


def _agg(df: pd.DataFrame) -> dict[str, Any]:
    n = len(df)
    if n == 0:
        return {"trades": 0, "pnl": 0.0, "win_rate": 0.0, "avg_return_pct": 0.0, "avg_pnl": 0.0}
    wins = int((df["pnl"] > 0).sum())
    return {
        "trades": n,
        "pnl": round(float(df["pnl"].sum()), 4),
        "win_rate": round(wins / n, 4),
        "avg_return_pct": round(float(df["return_pct"].mean()) * 100, 4),
        "avg_pnl": round(float(df["pnl"].mean()), 4),
    }


def trade_breakdown(trades: list[Trade]) -> dict[str, Any]:
    """按维度输出交易分布。"""
    if not trades:
        return {"by_exit_reason": [], "by_month": [], "by_weekday": [], "by_hour": []}
    df = _trades_frame(trades)
    df["month"] = df["exit_time"].dt.tz_localize(None).dt.to_period("M").astype(str)
    df["weekday"] = df["exit_time"].dt.day_name()
    df["hour"] = df["exit_time"].dt.hour

    def group(col):
        out = []
        for key, g in df.groupby(col, sort=True):
            item = {"key": str(key)}
            item.update(_agg(g))
            out.append(item)
        return out

    return {
        "by_exit_reason": group("reason"),
        "by_month": group("month"),
        "by_weekday": group("weekday"),
        "by_hour": group("hour"),
    }


def trade_stats(trades: list[Trade]) -> dict[str, Any]:
    """逐笔交易统计：最大连亏 / 最长连续盈利 / 最佳最差单笔 / R 分布。"""
    if not trades:
        return {}
    pnls = np.array([t.pnl for t in trades], dtype=float)
    rets = np.array([t.return_pct for t in trades], dtype=float)

    # 最大连亏 / 连胜
    max_loss_streak = cur_l = 0
    max_win_streak = cur_w = 0
    for p in pnls:
        if p < 0:
            cur_l += 1
            cur_w = 0
        else:
            cur_w += 1
            cur_l = 0
        max_loss_streak = max(max_loss_streak, cur_l)
        max_win_streak = max(max_win_streak, cur_w)

    r_vals = [
        t.pnl / t.initial_risk for t in trades if getattr(t, "initial_risk", 0.0) > 0
    ]
    return {
        "max_consecutive_losses": int(max_loss_streak),
        "max_consecutive_wins": int(max_win_streak),
        "best_trade_return_pct": round(float(rets.max()) * 100, 4),
        "worst_trade_return_pct": round(float(rets.min()) * 100, 4),
        "best_trade_pnl": round(float(pnls.max()), 4),
        "worst_trade_pnl": round(float(pnls.min()), 4),
        "avg_r": round(float(np.mean(r_vals)), 4) if r_vals else 0.0,
        "max_r": round(float(np.max(r_vals)), 4) if r_vals else 0.0,
        "min_r": round(float(np.min(r_vals)), 4) if r_vals else 0.0,
    }


