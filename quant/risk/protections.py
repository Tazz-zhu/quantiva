"""交易保护器（Protections）—— freqtrade plugins/protections 移植。

回测与实盘共用的动态风控闸门：
- CooldownPeriod:       平仓后冷却 N 根 K 线再允许开仓
- MaxDrawdownProtection: 账户回撤达阈值后暂停开仓，直到回撤收敛
- StoplossGuard:         一段时间内止损次数过多则暂停开仓
- LowProfitPairs:        某标的近期累计盈利过差则暂停该标的开仓

用法：Protections 实例在引擎循环中逐 bar 调用 check_entry / record_exit。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ProtectionConfig:
    """保护器配置（全部可选）。"""

    cooldown_candles: int = 0                     # 平仓后冷却 K 线数（0=关闭）
    max_drawdown_pct: float | None = None         # 账户回撤熔断阈值（0.1=10%）
    drawdown_recover_pct: float | None = None     # 回撤恢复阈值（默认回撤阈值一半）
    stoploss_guard_count: int = 0                 # 窗口内止损次数上限（0=关闭）
    stoploss_guard_window: int = 48               # 止损统计窗口（K 线数）
    stoploss_guard_pause: int = 24                # 触发后暂停开仓 K 线数
    low_profit_window: int = 0                    # 低盈利统计窗口（0=关闭）
    low_profit_threshold: float = -0.02           # 窗口累计收益率低于该值则暂停
    low_profit_pause: int = 24                    # 触发后暂停开仓 K 线数

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "ProtectionConfig":
        if not cfg:
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in cfg.items() if k in known})


@dataclass
class _SymbolState:
    last_exit_candle: int = -10**9
    stoploss_count: int = 0
    stoploss_window_start: int = 0
    low_profit_sum: float = 0.0
    low_profit_window_start: int = 0
    low_profit_pause_until: int = -10**9
    drawdown_pause_until: int = -10**9


class Protections:
    """按标的维护保护状态，供回测与实盘调用。"""

    def __init__(self, config: ProtectionConfig | dict[str, Any] | None = None):
        if isinstance(config, dict):
            config = ProtectionConfig.from_config(config)
        self.config = config or ProtectionConfig()
        self.states: dict[str, _SymbolState] = {}
        self.peak_equity: float | None = None

    # ------------------------------------------------------------------ #
    def check_entry(self, symbol: str, candle_index: int, equity: float) -> tuple[bool, str]:
        """判断当前是否允许开仓。返回 (allowed, reason)。"""
        cfg = self.config
        st = self.states.setdefault(symbol, _SymbolState())

        # 冷却期
        if cfg.cooldown_candles > 0 and candle_index - st.last_exit_candle < cfg.cooldown_candles:
            return False, f"冷却期（距上次平仓 {candle_index - st.last_exit_candle}/{cfg.cooldown_candles} 根）"

        # 回撤熔断
        if cfg.max_drawdown_pct:
            if self.peak_equity is None or equity > self.peak_equity:
                self.peak_equity = equity
            if self.peak_equity > 0:
                dd = equity / self.peak_equity - 1.0
                if dd <= -abs(cfg.max_drawdown_pct):
                    recover = cfg.drawdown_recover_pct or abs(cfg.max_drawdown_pct) / 2.0
                    if dd > -recover:
                        st.drawdown_pause_until = -10**9
                    else:
                        return False, f"回撤熔断（当前回撤 {dd * 100:.1f}%）"

        # 止损守卫
        if cfg.stoploss_guard_count > 0 and st.stoploss_count >= cfg.stoploss_guard_count:
            if candle_index - st.stoploss_window_start <= cfg.stoploss_guard_window:
                if candle_index - st.stoploss_window_start <= cfg.stoploss_guard_window + cfg.stoploss_guard_pause:
                    return False, f"止损过多（{st.stoploss_count} 次/窗口），暂停开仓"

        # 低盈利标的暂停
        if cfg.low_profit_window > 0:
            if candle_index - st.low_profit_window_start >= cfg.low_profit_window:
                if st.low_profit_sum <= cfg.low_profit_threshold:
                    st.low_profit_pause_until = candle_index + cfg.low_profit_pause
                st.low_profit_sum = 0.0
                st.low_profit_window_start = candle_index
            if candle_index < st.low_profit_pause_until:
                return False, f"低盈利暂停（窗口收益 {st.low_profit_sum * 100:.2f}%）"

        return True, ""

    # ------------------------------------------------------------------ #
    def record_exit(self, symbol: str, candle_index: int, reason: str, pnl_pct: float) -> None:
        """记录一次平仓，更新保护状态。"""
        st = self.states.setdefault(symbol, _SymbolState())
        st.last_exit_candle = candle_index
        if reason == "stop_loss":
            if st.stoploss_count == 0:
                st.stoploss_window_start = candle_index
            st.stoploss_count += 1
            # 窗口滑动：窗口外的止损不再计入
            while (
                self.config.stoploss_guard_window > 0
                and st.stoploss_count > 0
                and candle_index - st.stoploss_window_start > self.config.stoploss_guard_window
            ):
                st.stoploss_count -= 1
                st.stoploss_window_start += 1
        if self.config.low_profit_window > 0:
            if candle_index - st.low_profit_window_start >= self.config.low_profit_window:
                st.low_profit_window_start = candle_index
                st.low_profit_sum = 0.0
            st.low_profit_sum += pnl_pct

    def record_equity(self, equity: float) -> None:
        """记录权益峰值（用于回撤熔断）。"""
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity

    def reset(self) -> None:
        self.states.clear()
        self.peak_equity = None

