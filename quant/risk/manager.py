"""风控模型：固定/风险预算仓位、止损止盈、ATR 移动止损、保本止损、日/回撤熔断。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskManager:
    """统一风控参数（回测与实盘共用）

    - max_position_pct: 单笔名义价值占权益上限（0~1）
    - risk_per_trade_pct: 单笔风险预算（权益%），配合止损距离计算仓位（0=关闭，用固定比例）
    - leverage: 杠杆倍数（开仓保证金 = 名义价值 / 杠杆）
    - stop_loss_pct / take_profit_pct: 固定止损 / 止盈（0.03 = 3%）
    - atr_stop_mult: 未设固定止损时，用 entry +/- atr_stop_mult * ATR
    - trailing_stop_mult: ATR 移动止损（0=关闭）：止损随价格有利方向移动
    - trailing_stop_pct: 固定百分比移动止损（0=关闭）
    - break_even_after_mult: 盈利达到 N 倍 ATR 后止损移至成本价（0=关闭）
    - max_daily_loss_pct: 日亏损熔断（0.02 = 当日亏损权益 2% 熔断）
    - max_drawdown_pct: 组合权益回撤熔断（从峰值回撤达该比例即平仓并暂停开仓）
    - trade_direction: long_only / long_short
    """

    max_position_pct: float = 0.5
    leverage: float = 1.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    atr_stop_mult: float = 2.0
    risk_per_trade_pct: float = 0.0
    trailing_stop_mult: float = 0.0
    trailing_stop_pct: float = 0.0
    break_even_after_mult: float = 0.0
    max_positions: int = 1
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    allow_reentry_same_bar: bool = False
    trade_direction: str = "long_only"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RiskManager":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in config.items() if k in known})

    def position_size(self, equity: float, price: float) -> float:
        """固定比例仓位：权益 x 比例 x 杠杆 / 价格。"""
        if price <= 0 or equity <= 0:
            return 0.0
        notional = equity * self.max_position_pct * self.leverage
        return notional / price

    def risk_position_size(self, equity: float, price: float, stop_distance_pct: float | None = None) -> float:
        """风险预算仓位：风险金额 / 止损距离，并用 max_position_pct 封顶。

        单笔风险 = 权益 x risk_per_trade_pct；止损距离越小仓位越大，反之越小。
        """
        if price <= 0 or equity <= 0:
            return 0.0
        max_qty = self.position_size(equity, price)
        if self.risk_per_trade_pct and stop_distance_pct and stop_distance_pct > 0:
            risk_amount = equity * self.risk_per_trade_pct
            qty = risk_amount / (price * stop_distance_pct)
            return min(qty, max_qty)
        return max_qty

    def stop_prices(
        self,
        side: str,
        entry_price: float,
        atr_value: float | None = None,
    ) -> tuple[float | None, float | None]:
        """初始 (止损价, 止盈价)，未设置则返回 None。"""
        stop: float | None = None
        target: float | None = None
        if self.stop_loss_pct:
            stop = entry_price * (1.0 - self.stop_loss_pct) if side == "long" else entry_price * (1.0 + self.stop_loss_pct)
        elif atr_value and self.atr_stop_mult:
            stop = entry_price - self.atr_stop_mult * atr_value if side == "long" else entry_price + self.atr_stop_mult * atr_value
        if self.take_profit_pct:
            target = entry_price * (1.0 + self.take_profit_pct) if side == "long" else entry_price * (1.0 - self.take_profit_pct)
        return stop, target

    def trailing_stop(self, side: str, entry_price: float, current_price: float, atr_value: float | None, current_stop: float | None) -> float | None:
        """根据最新价格与 ATR 更新移动止损（返回最新止损价）。"""
        stop = current_stop
        if self.trailing_stop_mult and atr_value:
            trail = entry_price - self.trailing_stop_mult * atr_value if side == "long" else entry_price + self.trailing_stop_mult * atr_value
            stop = max(stop, trail) if side == "long" else min(stop, trail) if stop is not None else trail
        if self.trailing_stop_pct:
            trail = current_price * (1.0 - self.trailing_stop_pct) if side == "long" else current_price * (1.0 + self.trailing_stop_pct)
            stop = max(stop, trail) if side == "long" else min(stop, trail) if stop is not None else trail
        return stop

    def break_even_stop(self, side: str, entry_price: float, current_price: float, atr_value: float | None, current_stop: float | None) -> float | None:
        """盈利达到 break_even_after_mult 倍 ATR 后，止损提升至成本价（保本）。"""
        if not self.break_even_after_mult or not atr_value:
            return current_stop
        if side == "long":
            if current_price - entry_price >= self.break_even_after_mult * atr_value:
                return max(current_stop or entry_price, entry_price)
        else:
            if entry_price - current_price >= self.break_even_after_mult * atr_value:
                return min(current_stop or entry_price, entry_price)
        return current_stop
