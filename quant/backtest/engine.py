"""回测引擎：信号在下一根 K 线开盘执行，支持止损/止盈/移动止损/保本/资金费率/保证金检查。

量化正确性约束：
- 信号用上一根 K 线收盘后的值，在本根开盘执行（无前视偏差）
- 止损/止盈触发当根禁止信号重入（防同 bar 假高频）
- 杠杆开仓需满足保证金（名义/杠杆 + 手续费 <= 权益），不足拒绝

freqtrade 优势集成：
- 动态 ROI 表（minimal_roi）：持仓达分钟数且浮盈达标即止盈
- 保护器（Protections）：冷却期 / 回撤熔断 / 止损守卫 / 低盈利暂停
- 仓位调整（position adjustment）：浮盈达 N 倍 ATR 后分批加仓
- 深度分析：平仓原因 / 月度 / 星期 / 小时 breakdown 与逐笔统计
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from quant.analytics.metrics import compute_metrics
from quant.backtest.analysis import trade_breakdown, trade_stats
from quant.data.indicators import atr
from quant.risk.manager import RiskManager
from quant.risk.protections import Protections
from quant.strategy.base import Strategy


@dataclass
class Trade:
    """一笔已平仓交易。"""

    symbol: str
    side: str  # long / short
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    quantity: float
    fees: float
    pnl: float
    return_pct: float
    reason: str  # signal / stop_loss / take_profit / roi / margin_call / eod
    initial_risk: float = 0.0  # 入场 - 止损距离 x 数量（R 倍数分母）


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: dict[str, Any]
    positions: pd.Series
    data: pd.DataFrame
    breakdown: dict[str, Any] = field(default_factory=dict)
    trade_stats: dict[str, Any] = field(default_factory=dict)


class BacktestEngine:
    """逐根 K 线模拟：开盘执行信号、盘中止损止盈、收盘计权益。"""

    def __init__(
        self,
        strategy: Strategy,
        data: pd.DataFrame,
        initial_capital: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage: float = 0.0005,
        risk: RiskManager | None = None,
        symbol: str = "BTC/USDT",
        funding_rate_8h: float = 0.0,
    ):
        if len(data) < 2:
            raise ValueError("数据不足，无法回测（至少需要 2 根 K 线）")
        self.strategy = strategy
        self.data = data
        self.initial_capital = float(initial_capital)
        self.fee_rate = float(fee_rate)
        self.slippage = float(slippage)
        self.risk = risk or RiskManager()
        self.symbol = symbol
        self.funding_rate_8h = float(funding_rate_8h or 0.0)

    # ------------------------------------------------------------------ #
    def run(self) -> BacktestResult:
        df = self.data.copy()
        signals = self.strategy.generate_signals(df).astype(float)
        df["signal"] = signals
        df["atr"] = atr(df, 14)

        cash = float(self.initial_capital)
        position = 0.0
        entry_price: float | None = None
        entry_time: pd.Timestamp | None = None
        entry_qty = 0.0
        entry_risk = 0.0
        entry_fees_paid = 0.0
        adjust_count = 0
        total_adjustments = 0
        side: str | None = None
        current_stop: float | None = None
        no_reentry_this_bar = False
        trades: list[Trade] = []
        equity_list: list[float] = []
        position_list: list[float] = []

        direction = getattr(self.risk, "trade_direction", "long_only")
        allow_reentry = bool(getattr(self.risk, "allow_reentry_same_bar", False))
        protections = Protections(self.risk.protections or {})
        bar_sec = (
            df.index.to_series().diff().dt.total_seconds().median()
            if len(df) > 1
            else 3600.0
        )
        funding_paid = 0.0

        for i in range(len(df)):
            bar = df.iloc[i]
            no_reentry_this_bar = False
            atr_prev = float(df["atr"].iloc[i - 1]) if i > 0 and pd.notna(df["atr"].iloc[i - 1]) else None
            atr_val = bar["atr"] if pd.notna(bar["atr"]) else None

            # 0) 记录权益峰值（回撤熔断用）
            equity_now = cash + position * float(bar["close"])
            protections.record_equity(equity_now)

            # 1) 盘中止损 / 止盈 / 动态 ROI / 移动止损检查（用本根高低点判断）
            if position != 0 and entry_price is not None:
                stop, target = self.risk.stop_prices(side or "long", entry_price, atr_val)
                stop = self.risk.trailing_stop(side or "long", entry_price, float(bar["close"]), atr_val, stop)
                stop = self.risk.break_even_stop(side or "long", entry_price, float(bar["close"]), atr_val, stop)
                current_stop = stop
                exit_price: float | None = None
                reason: str | None = None
                if side == "long":
                    if stop is not None and bar["low"] <= stop:
                        exit_price, reason = stop, "stop_loss"
                    elif target is not None and bar["high"] >= target:
                        exit_price, reason = target, "take_profit"
                else:
                    if stop is not None and bar["high"] >= stop:
                        exit_price, reason = stop, "stop_loss"
                    elif target is not None and bar["low"] <= target:
                        exit_price, reason = target, "take_profit"

                # 动态 ROI（minimal_roi）：持仓时长达标且浮盈达标
                if exit_price is None and entry_time is not None:
                    elapsed_min = float((bar.name - entry_time).total_seconds()) / 60.0
                    roi = self.risk.roi_target(elapsed_min)
                    if roi is not None:
                        if side == "long":
                            profit_pct = (float(bar["close"]) - entry_price) / entry_price
                        else:
                            profit_pct = (entry_price - float(bar["close"])) / entry_price
                        if profit_pct >= float(roi):
                            exit_price, reason = float(bar["close"]), "roi"

                if exit_price is not None:
                    cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                        exit_price, bar.name, reason, cash, position, entry_price, entry_time, entry_qty,
                        entry_risk, side, trades, entry_fees=entry_fees_paid
                    )
                    entry_fees_paid = 0.0
                    adjust_count = 0
                    current_stop = None
                    if protections is not None:
                        protections.record_exit(self.symbol, i, reason,
                                                trades[-1].return_pct if trades else 0.0)
                    if not allow_reentry:
                        no_reentry_this_bar = True

            # 1.5) 仓位调整（freqtrade position adjustment）：浮盈达标后分批加仓
            if position != 0 and entry_price is not None and atr_val is not None:
                if self.risk.should_adjust(side or "long", entry_price, float(bar["close"]), atr_val, adjust_count):
                    equity_adj = cash + position * float(bar["close"])
                    add_notional = equity_adj * max(float(self.risk.adjust_step_pct), 0.0)
                    add_qty = add_notional / float(bar["close"]) if float(bar["close"]) > 0 else 0.0
                    if add_qty > 0:
                        fill = float(bar["close"]) * (1.0 + self.slippage) if position > 0 else float(bar["close"]) * (1.0 - self.slippage)
                        add_notional_fill = add_qty * fill
                        fee = add_notional_fill * self.fee_rate
                        leverage = max(float(self.risk.leverage or 1.0), 1e-9)
                        if add_notional_fill / leverage + fee <= equity_adj * 1.0001:
                            if position > 0:
                                cash -= add_notional_fill + fee
                            else:
                                cash += add_notional_fill - fee
                            old_qty = abs(position)
                            new_qty = old_qty + add_qty
                            avg_entry = (entry_price * old_qty + fill * add_qty) / new_qty
                            position = new_qty if position > 0 else -new_qty
                            entry_price = float(avg_entry)
                            entry_qty = new_qty
                            entry_fees_paid += fee
                            adjust_count += 1
                            total_adjustments += 1

            # 2) 按上一根信号在本根开盘执行（止损平仓当根禁止重入）
            if i > 0 and not (no_reentry_this_bar and position == 0):
                target = float(signals.iloc[i - 1])
                if direction == "long_only":
                    target = max(0.0, target)
                current = 1 if position > 0 else (-1 if position < 0 else 0)
                if target != current:
                    # 保护器：开仓前检查
                    if target != 0 and protections is not None:
                        allowed, why = protections.check_entry(self.symbol, i, equity_now)
                        if not allowed:
                            target = 0
                    open_price = float(bar["open"])
                    if target == 0:
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                            open_price, bar.name, "signal", cash, position, entry_price, entry_time,
                            entry_qty, entry_risk, side, trades, entry_fees=entry_fees_paid
                        )
                        entry_fees_paid = 0.0
                        adjust_count = 0
                        current_stop = None
                        if position == 0 and trades:
                            protections.record_exit(self.symbol, i, "signal", trades[-1].return_pct)
                    elif current == 0:
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side, fee = self._open_position(
                            target, open_price, bar.name, cash, position, entry_price, entry_time, entry_qty, side, atr_prev
                        )
                        entry_fees_paid = fee
                        adjust_count = 0
                        current_stop = None
                    else:  # 反向：先平后开
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                            open_price, bar.name, "signal", cash, position, entry_price, entry_time,
                            entry_qty, entry_risk, side, trades, entry_fees=entry_fees_paid
                        )
                        entry_fees_paid = 0.0
                        adjust_count = 0
                        current_stop = None
                        if trades:
                            protections.record_exit(self.symbol, i, "signal", trades[-1].return_pct)
                        if target != 0:
                            cash, position, entry_price, entry_time, entry_qty, entry_risk, side, fee = self._open_position(
                                target, open_price, bar.name, cash, position, entry_price, entry_time, entry_qty, side, atr_prev
                            )
                            entry_fees_paid = fee
                            adjust_count = 0
                            current_stop = None

            # 3) 资金费率（永续合约近似：持仓名义 x 8h费率 x 持仓时长占比，双向保守计费）
            if self.funding_rate_8h and position != 0:
                funding = abs(position * float(bar["close"]) * self.funding_rate_8h * (bar_sec / (8.0 * 3600.0)))
                cash -= funding
                funding_paid += funding

            equity_list.append(cash + position * float(bar["close"]))
            position_list.append(position)

            # 爆仓/强平检查：盘中价格触及强平价即按强平价平仓（权益 = 持仓名义/杠杆）
            if position != 0 and float(self.risk.leverage or 1.0) > 1 and entry_price is not None:
                lev = float(self.risk.leverage)
                qty_abs = abs(position)
                liq_price = None
                if side == "long" and abs(qty_abs * (1.0 / lev - 1.0)) > 1e-12:
                    liq_price = cash / (qty_abs * (1.0 / lev - 1.0))
                    if liq_price > 0 and float(bar["low"]) <= liq_price:
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                            liq_price, bar.name, "margin_call", cash, position, entry_price, entry_time,
                            entry_qty, entry_risk, side, trades, entry_fees=entry_fees_paid
                        )
                        entry_fees_paid = 0.0
                        adjust_count = 0
                        equity_list[-1] = cash
                        if trades:
                            protections.record_exit(self.symbol, i, "margin_call", trades[-1].return_pct)
                elif side == "short" and abs(qty_abs * (1.0 + 1.0 / lev)) > 1e-12:
                    liq_price = cash / (qty_abs * (1.0 + 1.0 / lev))
                    if liq_price > 0 and float(bar["high"]) >= liq_price:
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                            liq_price, bar.name, "margin_call", cash, position, entry_price, entry_time,
                            entry_qty, entry_risk, side, trades, entry_fees=entry_fees_paid
                        )
                        entry_fees_paid = 0.0
                        adjust_count = 0
                        equity_list[-1] = cash
                        if trades:
                            protections.record_exit(self.symbol, i, "margin_call", trades[-1].return_pct)

        # 期末强制平仓
        if position != 0 and entry_price is not None:
            last_close = float(df["close"].iloc[-1])
            cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                last_close, df.index[-1], "eod", cash, position, entry_price, entry_time,
                entry_qty, entry_risk, side, trades, entry_fees=entry_fees_paid
            )
            equity_list[-1] = cash + position * last_close
            if trades:
                protections.record_exit(self.symbol, len(df) - 1, "eod", trades[-1].return_pct)

        equity_curve = pd.Series(equity_list, index=df.index, dtype=float)
        positions = pd.Series(position_list, index=df.index, dtype=float)

        seconds = (
            df.index.to_series().diff().dt.total_seconds().median()
            if len(df) > 1
            else 3600.0
        )
        periods_per_year = max(int(round(365 * 24 * 3600 / seconds)), 1) if seconds > 0 else 8760
        buy_hold = df["close"].iloc[-1] / df["close"].iloc[0] - 1.0
        metrics = compute_metrics(
            equity_curve,
            trades,
            self.initial_capital,
            periods_per_year=periods_per_year,
            buy_hold_return=buy_hold,
            benchmark_returns=df["close"].pct_change(),
        )
        metrics["exposure"] = float((positions != 0.0).mean()) if len(positions) else 0.0
        metrics["funding_paid"] = round(funding_paid, 4)
        metrics["total_fees"] = float(metrics.get("total_fees", 0.0)) + round(funding_paid, 4)
        metrics["adjustments"] = total_adjustments
        return BacktestResult(
            equity_curve, trades, metrics, positions, df,
            breakdown=trade_breakdown(trades),
            trade_stats=trade_stats(trades),
        )

    # ------------------------------------------------------------------ #
    def _open_position(self, direction, price, ts, cash, position, entry_price, entry_time, entry_qty, side, atr_prev=None):
        """开仓：风险预算仓位 + 保证金检查，返回 (cash, position, entry_price, entry_time, entry_qty, side, initial_risk, entry_fee)。"""
        equity = cash + position * price
        new_side = "long" if direction > 0 else "short"

        # 初始止损距离（用于风险预算仓位与 R 倍数）
        stop_pct = None
        stop_price = None
        if atr_prev is not None or self.risk.stop_loss_pct:
            sp, _tp = self.risk.stop_prices(new_side, price, atr_prev)
            if sp:
                stop_price = sp
                stop_pct = abs(price - sp) / price

        qty = self.risk.risk_position_size(equity, price, stop_pct)
        if qty <= 0:
            return cash, position, entry_price, entry_time, entry_qty, side, 0.0, 0.0

        fill = price * (1.0 + self.slippage) if direction > 0 else price * (1.0 - self.slippage)
        notional = qty * fill
        fee = notional * self.fee_rate
        # 保证金检查：名义/杠杆 + 手续费 <= 权益
        leverage = max(float(self.risk.leverage or 1.0), 1e-9)
        required_margin = notional / leverage + fee
        if required_margin > equity * 1.0001:
            return cash, position, entry_price, entry_time, entry_qty, side, 0.0, 0.0

        if new_side == "long":
            cash -= notional + fee
        else:
            cash += notional - fee
        initial_risk = abs(fill - stop_price) * qty if stop_price else 0.0
        return cash, qty * direction, fill, ts, qty, initial_risk, new_side, fee

    def _close_position(self, price, ts, reason, cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades, entry_fees=0.0):
        if position == 0 or entry_price is None:
            return cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades
        qty = abs(position)
        fill = price * (1.0 - self.slippage) if position > 0 else price * (1.0 + self.slippage)
        notional = qty * fill
        fee = notional * self.fee_rate
        entry_fee = float(entry_fees) if entry_fees else entry_price * qty * self.fee_rate
        if side == "long":
            gross = (fill - entry_price) * qty
            cash += notional - fee
        else:
            gross = (entry_price - fill) * qty
            cash -= notional + fee
        pnl = gross - entry_fee - fee
        trades.append(
            Trade(
                symbol=self.symbol,
                side=side,
                entry_time=entry_time,
                entry_price=entry_price,
                exit_time=ts,
                exit_price=fill,
                quantity=qty,
                fees=entry_fee + fee,
                pnl=pnl,
                return_pct=pnl / (entry_price * qty) if entry_price else 0.0,
                reason=reason,
                initial_risk=round(entry_risk, 4),
            )
        )
        return cash, 0.0, None, None, 0.0, 0.0, None, trades

