"""超参寻优损失函数（freqtrade 风格：返回值越小越优）。

所有函数接收一个回测结果对象（BacktestResult），返回 "loss"（越小越好）。
与现有 Optimizer 的 "score"（越大越好）通过 loss_score() 互相转换。
"""
from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from quant.backtest.engine import BacktestResult


def _equity_returns(result: BacktestResult) -> pd.Series:
    """从权益曲线计算简单收益率序列。"""
    eq = result.equity_curve.astype(float)
    return eq.pct_change().dropna()


def _periods_per_year(result: BacktestResult) -> int:
    idx = result.equity_curve.index
    if len(idx) > 1:
        seconds = idx.to_series().diff().dt.total_seconds().median()
        if seconds and seconds > 0:
            return max(int(round(365 * 24 * 3600 / seconds)), 1)
    return 8760


def _annualized_return(result: BacktestResult) -> float:
    eq = result.equity_curve.astype(float)
    n = max(len(eq), 1)
    final = float(eq.iloc[-1]) if len(eq) else float(result.metrics.get("initial_capital", 1.0))
    init = float(result.metrics.get("initial_capital", 1.0)) or 1.0
    ppy = _periods_per_year(result)
    if final > 0 and init > 0:
        return (final / init) ** (ppy / n) - 1.0
    return -1.0


# --------------------------------------------------------------------- #
# 单指标损失
# --------------------------------------------------------------------- #
def sharpe_loss(result: BacktestResult, **kwargs: Any) -> float:
    """夏普比率损失：-Sharpe（越低越好）。"""
    return -float(result.metrics.get("sharpe", 0.0) or 0.0)


def sortino_loss(result: BacktestResult, **kwargs: Any) -> float:
    """索提诺比率损失：-Sortino（越低越好）。"""
    return -float(result.metrics.get("sortino", 0.0) or 0.0)


def calmar_loss(result: BacktestResult, **kwargs: Any) -> float:
    """卡玛比率损失：-Calmar（越低越好）。"""
    return -float(result.metrics.get("calmar", 0.0) or 0.0)


def max_drawdown_loss(result: BacktestResult, **kwargs: Any) -> float:
    """最大回撤损失：相对回撤（正值，越小越好）。"""
    return float(result.metrics.get("max_drawdown", 0.0) or 0.0)


def profit_factor_loss(result: BacktestResult, **kwargs: Any) -> float:
    """盈亏比损失：-log(profit_factor)（越低越好，覆盖无亏损情形）。"""
    pf = float(result.metrics.get("profit_factor", 0.0) or 0.0)
    if pf <= 0:
        return 1e6
    return -math.log(pf)


def total_profit_loss(result: BacktestResult, **kwargs: Any) -> float:
    """总收益损失：-总收益率（越低越好）。"""
    return -float(result.metrics.get("total_return", 0.0) or 0.0)


def expectancy_loss(result: BacktestResult, **kwargs: Any) -> float:
    """期望值损失：-期望 R 倍数（越低越好）。"""
    return -float(result.metrics.get("expectancy_r", 0.0) or 0.0)


def sqn_loss(result: BacktestResult, **kwargs: Any) -> float:
    """系统质量指数损失：-SQN（越低越好）。"""
    return -float(result.metrics.get("sqn", 0.0) or 0.0)


# --------------------------------------------------------------------- #
# 多指标组合损失（freqtrade MultiMetricHyperOptLoss 移植）
# --------------------------------------------------------------------- #
DRAWDOWN_MULT = 0.055
LARGE_NUMBER = 1e6
TARGET_TRADE_AMOUNT = 50
EXPECTANCY_CONST = 2.0
PF_CONST = 1.0
WINRATE_CONST = 1.2


def multi_metric_loss(
    result: BacktestResult,
    drawdown_mult: float = DRAWDOWN_MULT,
    target_trade_amount: int = TARGET_TRADE_AMOUNT,
    **kwargs: Any,
) -> float:
    """freqtrade MultiMetricHyperOptLoss：收益 × 盈亏比 × 期望 × 胜率 × 交易数惩罚。

    总收益扣除回撤惩罚后再与各对数因子相乘；交易数不足时施加惩罚。
    """
    trades = result.trades
    total_profit = float(sum(t.pnl for t in trades))
    winning = sum(t.pnl for t in trades if t.pnl > 0)
    losing = sum(t.pnl for t in trades if t.pnl <= 0)
    profit_factor = winning / (abs(losing) + 1e-6)
    log_profit_factor = math.log(profit_factor + PF_CONST)

    r_vals = [t.pnl / t.initial_risk for t in trades if getattr(t, "initial_risk", 0.0) > 0]
    expectancy_ratio = float(np.mean(r_vals)) if r_vals else 0.0
    log_expectancy_ratio = math.log(min(10.0, expectancy_ratio) + EXPECTANCY_CONST)

    winrate = (sum(1 for t in trades if t.pnl > 0) / len(trades)) if trades else 0.0
    log_winrate_coef = math.log(WINRATE_CONST + winrate)

    relative_account_drawdown = float(result.metrics.get("max_drawdown", 0.0) or 0.0)

    trade_count_penalty = 1.0
    trade_count = len(trades)
    if trade_count < target_trade_amount:
        trade_count_penalty = 1 - (abs(trade_count - target_trade_amount) / target_trade_amount)
        trade_count_penalty = max(trade_count_penalty, 0.1)

    profit_draw_function = total_profit - (relative_account_drawdown * total_profit) * (
        1 - drawdown_mult
    )
    value = (
        profit_draw_function
        * log_profit_factor
        * log_expectancy_ratio
        * log_winrate_coef
        * trade_count_penalty
    )
    return -1.0 * value


# --------------------------------------------------------------------- #
# 按持仓时长加权的收益损失（freqtrade ShortTradeDurHyperOptLoss 移植）
# --------------------------------------------------------------------- #
def short_trade_dur_loss(result: BacktestResult, **kwargs: Any) -> float:
    """短持仓时间损失：总收益按平均持仓时长加权（鼓励快进快出）。"""
    trades = result.trades
    if not trades:
        return 1e6
    total_profit = sum(t.pnl for t in trades)
    holding = [
        (t.exit_time - t.entry_time).total_seconds() / 3600.0 for t in trades
    ]
    avg_holding = float(np.mean(holding)) if holding else 0.0
    # 目标持仓 8 小时：超过则按比例惩罚收益
    target_dur = 8.0
    if avg_holding > target_dur:
        total_profit *= target_dur / avg_holding
    return -total_profit


# --------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------- #
LOSS_FUNCTIONS: dict[str, tuple[str, Callable[[BacktestResult], float]]] = {
    "sharpe": ("夏普比率（-Sharpe）", sharpe_loss),
    "sortino": ("索提诺比率（-Sortino）", sortino_loss),
    "calmar": ("卡玛比率（-Calmar）", calmar_loss),
    "max_drawdown": ("最大回撤最小化", max_drawdown_loss),
    "profit_factor": ("盈亏比最大化（-log PF）", profit_factor_loss),
    "total_profit": ("总收益最大化", total_profit_loss),
    "expectancy": ("期望 R 倍数最大化", expectancy_loss),
    "sqn": ("系统质量指数（-SQN）", sqn_loss),
    "multi_metric": ("多指标组合（freqtrade MultiMetric）", multi_metric_loss),
    "short_trade_dur": ("短持仓时间加权收益", short_trade_dur_loss),
}


def compute_loss(name: str, result: BacktestResult, **kwargs: Any) -> float:
    """按名称计算损失（越小越优）。未知名称抛 ValueError。"""
    if name not in LOSS_FUNCTIONS:
        raise ValueError(f"未知损失函数: {name}，可选 {list(LOSS_FUNCTIONS)}")
    return float(LOSS_FUNCTIONS[name][1](result, **kwargs))


def loss_score(name: str, result: BacktestResult, **kwargs: Any) -> float:
    """损失转换为 Optimizer 的 score（越大越优）：score = -loss。"""
    return -compute_loss(name, result, **kwargs)
