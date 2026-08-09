"""量化指标计算：最大回撤 / 夏普 / 索提诺 / 期望值 / 恢复因子 / SQN 等。"""
from __future__ import annotations

import numpy as np
import pandas as pd

SECONDS_PER_YEAR = 365 * 24 * 3600


def max_drawdown(equity: pd.Series) -> tuple[float, pd.Timestamp]:
    """计算最大回撤（返回最大回撤比例与发生时间戳）。"""
    if equity.empty:
        return 0.0, pd.NaT
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    idx = dd.idxmin()
    return float(dd.min()), idx


def _annualize(returns: pd.Series, periods_per_year: int) -> float:
    if len(returns) < 2 or returns.std() <= 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def compute_metrics(
    equity_curve: pd.Series,
    trades: list,
    initial_capital: float,
    periods_per_year: int = 8760,
    buy_hold_return: float | None = None,
    benchmark_returns: pd.Series | None = None,
) -> dict:
    """从权益曲线与交易列表计算完整绩效指标（含尾部风险 / 回撤深度 / R 倍数 / 基准统计）。"""
    equity = equity_curve.astype(float)
    returns = equity.pct_change().dropna()
    final = float(equity.iloc[-1]) if len(equity) else float(initial_capital)
    n = max(len(equity), 1)

    total_return = final / initial_capital - 1.0
    annual_return = (final / initial_capital) ** (periods_per_year / n) - 1.0 if final > 0 else -1.0
    ret_std = float(returns.std()) if len(returns) > 1 else 0.0
    mean_r = float(returns.mean()) if len(returns) else 0.0
    volatility = ret_std * np.sqrt(periods_per_year) if ret_std > 0 else 0.0

    # 夏普：年化收益 / 年化波动（用简单收益）
    sharpe = mean_r / ret_std * np.sqrt(periods_per_year) if ret_std > 0 else 0.0
    # 下行偏差（标准 Downside Deviation，MAR=0）：sqrt(mean(min(r,0)^2)) 并年化
    downside_dev_ann = (
        float(np.sqrt((returns[returns < 0] ** 2).mean())) * np.sqrt(periods_per_year)
        if len(returns) > 1 else 0.0
    )
    # Sortino：年化收益 / 年化下行偏差
    sortino = (mean_r * periods_per_year) / downside_dev_ann if downside_dev_ann > 0 else 0.0

    mdd, mdd_ts = max_drawdown(equity)
    running_max = equity.cummax()
    dd_series = equity / running_max - 1.0
    underwater_time_pct = float((dd_series < 0).mean()) if len(dd_series) else 0.0
    ulcer = float(np.sqrt((dd_series ** 2).mean())) if len(dd_series) else 0.0
    max_run_up = float((equity / equity.cummin() - 1.0).max()) if len(equity) else 0.0

    # 尾部风险
    var95 = float(np.percentile(returns, 5)) if len(returns) else 0.0
    tail = returns[returns <= var95] if len(returns) else returns
    cvar95 = float(tail.mean()) if len(tail) else 0.0
    skew = float(returns.skew()) if len(returns) > 2 else 0.0
    kurtosis = float(returns.kurtosis()) if len(returns) > 3 else 0.0
    best_day = float(returns.max()) if len(returns) else 0.0
    worst_day = float(returns.min()) if len(returns) else 0.0
    p5 = float(np.percentile(returns, 5)) if len(returns) else 0.0
    tail_ratio = float(np.percentile(returns, 95) / abs(p5)) if len(returns) and p5 != 0 else 0.0

    num_trades = len(trades)
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    win_rate = len(wins) / num_trades if num_trades else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    avg_win_loss_ratio = avg_win / abs(avg_loss) if avg_loss else (float("inf") if avg_win > 0 else 0.0)
    avg_trade_return = float(np.mean([t.return_pct for t in trades])) if trades else 0.0
    total_fees = float(sum(t.fees for t in trades))
    total_pnl = float(sum(t.pnl for t in trades))

    # 期望值（每笔交易的平均期望盈利，金额）
    expectancy = win_rate * avg_win - (1.0 - win_rate) * avg_loss if num_trades else 0.0
    # 恢复因子：总收益 / 最大回撤（衡量回撤后的恢复能力）
    recovery_factor = total_return / abs(mdd) if mdd < 0 else 0.0
    # 卡玛比率：年化收益 / 最大回撤
    calmar = annual_return / abs(mdd) if mdd < 0 else 0.0
    # SQN（Van Tharp 系统质量指数）：sqrt(N) * 平均单笔收益 / 单笔收益标准差
    if num_trades > 1:
        rets = np.array([t.return_pct for t in trades], dtype=float)
        sd = float(rets.std())
        sqn = float(np.sqrt(num_trades) * rets.mean() / sd) if sd > 0 else 0.0
    else:
        sqn = 0.0

    # R 倍数统计（每笔初始风险 = 入场-止损距离 x 数量）
    risks = [t.initial_risk for t in trades if getattr(t, "initial_risk", 0.0) > 0]
    r_vals = [t.pnl / t.initial_risk for t in trades if getattr(t, "initial_risk", 0.0) > 0]
    avg_risk = float(np.mean(risks)) if risks else 0.0
    avg_r = float(np.mean(r_vals)) if r_vals else 0.0
    expectancy_r = avg_r
    r_positive_pct = float(sum(1 for r in r_vals if r > 0) / len(r_vals)) if r_vals else 0.0
    max_r = float(np.max(r_vals)) if r_vals else 0.0
    min_r = float(np.min(r_vals)) if r_vals else 0.0

    # 平均持仓时长（小时）
    holding = [(t.exit_time - t.entry_time).total_seconds() / 3600.0 for t in trades] if trades else [0.0]
    avg_holding_hours = float(np.mean(holding))

    # 基准统计（Alpha / Beta / 超额收益，基准为标的买入持有收益序列）
    alpha_annual = None
    beta = None
    excess_return = None
    if benchmark_returns is not None and len(returns) > 2:
        br = benchmark_returns.dropna()
        common = returns.reindex(br.index).dropna()
        br = br.reindex(common.index).dropna()
        common = common.reindex(br.index).dropna()
        if len(common) > 2:
            bvar = float(br.var())
            if bvar > 0:
                beta = float(common.cov(br) / bvar)
                bench_ann = float((1.0 + br.mean()) ** periods_per_year - 1.0)
                alpha_annual = annual_return - beta * bench_ann
    if buy_hold_return is not None:
        excess_return = total_return - float(buy_hold_return)

    return {
        "initial_capital": float(initial_capital),
        "final_equity": final,
        "total_return": total_return,
        "annual_return": annual_return,
        "buy_hold_return": float(buy_hold_return) if buy_hold_return is not None else None,
        "excess_return": excess_return,
        "volatility": volatility,
        "downside_dev": downside_dev_ann,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "max_drawdown_time": str(mdd_ts),
        "underwater_time_pct": underwater_time_pct,
        "ulcer": ulcer,
        "max_run_up": max_run_up,
        "var95": var95,
        "cvar95": cvar95,
        "skew": skew,
        "kurtosis": kurtosis,
        "best_day": best_day,
        "worst_day": worst_day,
        "tail_ratio": tail_ratio,
        "alpha_annual": alpha_annual,
        "beta": beta,
        "num_trades": num_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_win_loss_ratio": avg_win_loss_ratio,
        "avg_trade_return": avg_trade_return,
        "expectancy": expectancy,
        "expectancy_pct": avg_trade_return,
        "recovery_factor": recovery_factor,
        "calmar": calmar,
        "sqn": sqn,
        "avg_holding_hours": avg_holding_hours,
        "avg_risk": avg_risk,
        "avg_r": avg_r,
        "expectancy_r": expectancy_r,
        "r_positive_pct": r_positive_pct,
        "max_r": max_r,
        "min_r": min_r,
        "total_fees": total_fees,
        "total_pnl": total_pnl,
        "periods": n,
        "periods_per_year": periods_per_year,
    }
