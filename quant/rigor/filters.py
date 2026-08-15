"""优化纪元过滤器（freqtrade hyperopt_epoch_filters 移植）。

对一组优化结果（每个元素含 metrics 与可选 loss）应用硬性门槛过滤，
剔除过拟合 / 不可用的参数组合，返回剩余结果与过滤统计。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EpochFilterOptions:
    """过滤选项（None = 不启用该过滤）。"""

    only_profitable: bool = False          # 仅保留盈利组合
    filter_min_trades: int = 0             # 最小交易数（0=关闭）
    filter_max_trades: int = 0             # 最大交易数（0=关闭）
    filter_min_avg_profit: float | None = None   # 单笔平均收益下限 %（如 0.1 = 0.1%）
    filter_max_avg_profit: float | None = None   # 单笔平均收益上限 %
    filter_min_total_profit: float | None = None # 总收益（绝对额）下限
    filter_max_total_profit: float | None = None # 总收益（绝对额）上限
    filter_min_objective: float | None = None    # loss 上限（更小更优；过滤 loss < 该值）
    filter_max_objective: float | None = None    # loss 下限（过滤 loss > 该值）
    filter_max_drawdown: float | None = None     # 最大回撤上限（0.2 = 20%）
    filter_min_profit_factor: float | None = None  # 盈亏比下限
    filter_min_sharpe: float | None = None       # 夏普下限
    filter_min_win_rate: float | None = None     # 胜率下限

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "EpochFilterOptions":
        if not cfg:
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in cfg.items() if k in known})


def _get(epoch: dict, key: str, default: Any = None) -> Any:
    metrics = epoch.get("metrics") or {}
    return epoch.get(key, metrics.get(key, default))


def filter_epochs(
    epochs: list[dict],
    options: EpochFilterOptions | dict[str, Any] | None = None,
    loss_key: str = "loss",
) -> tuple[list[dict], dict[str, int]]:
    """过滤优化纪元。

    参数
    ----
    epochs:  优化结果列表，每个元素形如 {"params": {...}, "metrics": {...}, "loss": float, ...}
    options: EpochFilterOptions 或 dict

    返回
    ----
    (过滤后的列表, 统计 {"total": n, "removed": m, ...})
    """
    if isinstance(options, dict):
        options = EpochFilterOptions.from_config(options)
    options = options or EpochFilterOptions()
    stats: dict[str, int] = {"total": len(epochs)}

    kept = list(epochs)
    removed_total = 0

    def apply(pred, label: str):
        nonlocal kept, removed_total
        before = len(kept)
        kept = [e for e in kept if pred(e)]
        removed = before - len(kept)
        stats[label] = removed
        stats["removed"] = removed_total = stats.get("removed", 0) + removed

    if options.only_profitable:
        apply(lambda e: float(_get(e, "total_return", 0) or 0) > 0, "not_profitable")

    if options.filter_min_trades > 0:
        apply(
            lambda e: int(_get(e, "num_trades", 0) or 0) >= options.filter_min_trades,
            "below_min_trades",
        )
    if options.filter_max_trades > 0:
        apply(
            lambda e: int(_get(e, "num_trades", 0) or 0) <= options.filter_max_trades,
            "above_max_trades",
        )

    if options.filter_min_avg_profit is not None:
        apply(
            lambda e: float(_get(e, "avg_trade_return", 0) or 0) * 100
            > options.filter_min_avg_profit,
            "below_min_avg_profit",
        )
    if options.filter_max_avg_profit is not None:
        apply(
            lambda e: float(_get(e, "avg_trade_return", 0) or 0) * 100
            < options.filter_max_avg_profit,
            "above_max_avg_profit",
        )

    if options.filter_min_total_profit is not None:
        apply(
            lambda e: float(_get(e, "total_pnl", 0) or 0) > options.filter_min_total_profit,
            "below_min_total_profit",
        )
    if options.filter_max_total_profit is not None:
        apply(
            lambda e: float(_get(e, "total_pnl", 0) or 0) < options.filter_max_total_profit,
            "above_max_total_profit",
        )

    if options.filter_min_objective is not None:
        # loss 越小越优：过滤 loss 高于门槛的组合
        apply(
            lambda e: float(e.get(loss_key, -1e9) or -1e9) < options.filter_min_objective,
            "above_min_objective",
        )
    if options.filter_max_objective is not None:
        apply(
            lambda e: float(e.get(loss_key, 1e9) or 1e9) > options.filter_max_objective,
            "below_max_objective",
        )

    if options.filter_max_drawdown is not None:
        apply(
            lambda e: abs(float(_get(e, "max_drawdown", 0) or 0)) <= options.filter_max_drawdown,
            "above_max_drawdown",
        )
    if options.filter_min_profit_factor is not None:
        apply(
            lambda e: float(_get(e, "profit_factor", 0) or 0) >= options.filter_min_profit_factor,
            "below_min_profit_factor",
        )
    if options.filter_min_sharpe is not None:
        apply(
            lambda e: float(_get(e, "sharpe", -99) or -99) >= options.filter_min_sharpe,
            "below_min_sharpe",
        )
    if options.filter_min_win_rate is not None:
        apply(
            lambda e: float(_get(e, "win_rate", 0) or 0) >= options.filter_min_win_rate,
            "below_min_win_rate",
        )

    stats["kept"] = len(kept)
    return kept, stats
