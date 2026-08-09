"""回测引擎：信号在下一根 K 线开盘执行，支持止损/止盈/移动止损/保本/资金费率/保证金检查。

量化正确性约束：
- 信号用上一根 K 线收盘后的值，在本根开盘执行（无前视偏差）
- 止损/止盈触发当根禁止信号重入（防同 bar 假高频）
- 杠杆开仓需满足保证金（名义/杠杆 + 手续费 <= 权益），不足拒绝
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quant.analytics.metrics import compute_metrics
from quant.data.indicators import atr
from quant.risk.manager import RiskManager
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
    reason: str  # signal / stop_loss / take_profit / eod
    initial_risk: float = 0.0  # 入场 - 止损距离 x 数量（R 倍数分母）


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: dict[str, Any]
    positions: pd.Series
    data: pd.DataFrame


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
        side: str | None = None
        current_stop: float | None = None
        no_reentry_this_bar = False
        trades: list[Trade] = []
        equity_list: list[float] = []
        position_list: list[float] = []

        direction = getattr(self.risk, "trade_direction", "long_only")
        allow_reentry = bool(getattr(self.risk, "allow_reentry_same_bar", False))
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

            # 1) 盘中止损 / 止盈 / 移动止损检查（用本根高低点判断）
            if position != 0 and entry_price is not None:
                atr_val = bar["atr"] if pd.notna(bar["atr"]) else None
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
                if exit_price is not None:
                    cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                        exit_price, bar.name, reason, cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades
                    )
                    current_stop = None
                    if not allow_reentry:
                        no_reentry_this_bar = True

            # 2) 按上一根信号在本根开盘执行（止损平仓当根禁止重入）
            if i > 0 and not (no_reentry_this_bar and position == 0):
                target = float(signals.iloc[i - 1])
                if direction == "long_only":
                    target = max(0.0, target)
                current = 1 if position > 0 else (-1 if position < 0 else 0)
                if target != current:
                    open_price = float(bar["open"])
                    if target == 0:
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                            open_price, bar.name, "signal", cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades
                        )
                        current_stop = None
                    elif current == 0:
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side = self._open_position(
                            target, open_price, bar.name, cash, position, entry_price, entry_time, entry_qty, side, atr_prev
                        )
                        current_stop = None
                    else:  # 反向：先平后开
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                            open_price, bar.name, "signal", cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades
                        )
                        current_stop = None
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side = self._open_position(
                            target, open_price, bar.name, cash, position, entry_price, entry_time, entry_qty, side, atr_prev
                        )

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
                            liq_price, bar.name, "margin_call", cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades
                        )
                        equity_list[-1] = cash
                elif side == "short" and abs(qty_abs * (1.0 + 1.0 / lev)) > 1e-12:
                    liq_price = cash / (qty_abs * (1.0 + 1.0 / lev))
                    if liq_price > 0 and float(bar["high"]) >= liq_price:
                        cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                            liq_price, bar.name, "margin_call", cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades
                        )
                        equity_list[-1] = cash

        # 期末强制平仓
        if position != 0 and entry_price is not None:
            last_close = float(df["close"].iloc[-1])
            cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades = self._close_position(
                last_close, df.index[-1], "eod", cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades
            )
            equity_list[-1] = cash + position * last_close

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
        return BacktestResult(equity_curve, trades, metrics, positions, df)

    # ------------------------------------------------------------------ #
    def _open_position(self, direction, price, ts, cash, position, entry_price, entry_time, entry_qty, side, atr_prev=None):
        """开仓：风险预算仓位 + 保证金检查，返回 (cash, position, entry_price, entry_time, entry_qty, side, initial_risk)。"""
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
            return cash, position, entry_price, entry_time, entry_qty, side, 0.0

        fill = price * (1.0 + self.slippage) if direction > 0 else price * (1.0 - self.slippage)
        notional = qty * fill
        fee = notional * self.fee_rate
        # 保证金检查：名义/杠杆 + 手续费 <= 权益
        leverage = max(float(self.risk.leverage or 1.0), 1e-9)
        required_margin = notional / leverage + fee
        if required_margin > equity * 1.0001:
            return cash, position, entry_price, entry_time, entry_qty, side, 0.0

        if new_side == "long":
            cash -= notional + fee
        else:
            cash += notional - fee
        initial_risk = abs(fill - stop_price) * qty if stop_price else 0.0
        return cash, qty * direction, fill, ts, qty, initial_risk, new_side

    def _close_position(self, price, ts, reason, cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades):
        if position == 0 or entry_price is None:
            return cash, position, entry_price, entry_time, entry_qty, entry_risk, side, trades
        qty = abs(position)
        fill = price * (1.0 - self.slippage) if position > 0 else price * (1.0 + self.slippage)
        notional = qty * fill
        fee = notional * self.fee_rate
        entry_fee = entry_price * qty * self.fee_rate
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
