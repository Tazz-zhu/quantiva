"""多币种组合回测引擎（freqtrade 组合回测移植）。

在统一时间轴上同时模拟多个币种：
- 共享现金池与开仓数上限（max_open_trades）
- 每个币种独立计算信号/止损/止盈/动态 ROI/仓位调整/保护器
- 组合权益曲线、组合回撤、各币种贡献统计

正确性约束与单币种引擎一致：信号在下一根 K 线开盘执行，无前视。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from quant.analytics.metrics import compute_metrics
from quant.backtest.analysis import trade_breakdown, trade_stats
from quant.backtest.engine import Trade
from quant.data.indicators import atr
from quant.risk.manager import RiskManager
from quant.risk.protections import Protections
from quant.strategy.base import Strategy


@dataclass
class PortfolioResult:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: dict[str, Any]
    per_symbol: dict[str, dict[str, Any]]
    breakdown: dict[str, Any] = field(default_factory=dict)
    trade_stats: dict[str, Any] = field(default_factory=dict)


class PortfolioBacktester:
    """多币种组合回测。"""

    def __init__(
        self,
        strategies: dict[str, Strategy],
        data: dict[str, pd.DataFrame],
        initial_capital: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage: float = 0.0005,
        risk: RiskManager | None = None,
        max_open_trades: int = 3,
        funding_rate_8h: float = 0.0,
        align: str = "inner",
    ):
        if not strategies or not data:
            raise ValueError("组合回测需要至少一个标的与策略")
        self.strategies = strategies
        self.data = data
        self.initial_capital = float(initial_capital)
        self.fee_rate = float(fee_rate)
        self.slippage = float(slippage)
        self.risk = risk or RiskManager()
        self.max_open_trades = max(1, int(max_open_trades))
        self.funding_rate_8h = float(funding_rate_8h or 0.0)
        self.align = align
        self._last_close: dict[str, float] = {}
        self._bar_index = 0

    # ------------------------------------------------------------------ #
    def run(self) -> PortfolioResult:
        prepared: dict[str, pd.DataFrame] = {}
        for sym, df in self.data.items():
            d = df.copy().sort_index()
            d["signal"] = self.strategies[sym].generate_signals(d).astype(float)
            d["atr"] = atr(d, 14)
            prepared[sym] = d

        common = self._common_index(prepared)
        cash = float(self.initial_capital)
        positions: dict[str, dict[str, Any]] = {}
        protections = Protections(self.risk.protections or {})
        trades: list[Trade] = []
        equity_list: list[float] = []
        self._last_close = {}
        bar_sec = self._bar_seconds(prepared)
        funding_paid = 0.0

        def mark_equity() -> float:
            eq = cash
            for sym, st in positions.items():
                px = self._last_close.get(sym) or st["entry_price"]
                eq += st["qty"] * px
            return eq

        for i, t in enumerate(common):
            self._bar_index = i

            # 1) 盘中：止损/止盈/ROI + 加仓
            for sym in list(positions.keys()):
                st = positions[sym]
                d = prepared[sym]
                if t not in d.index:
                    self._last_close[sym] = st["last_close"]
                    continue
                bar = d.loc[t]
                atr_val = float(bar["atr"]) if pd.notna(bar["atr"]) else None
                exit_price, reason = self._check_exit(st, t, bar, atr_val)
                if exit_price is not None:
                    cash = self._close(sym, t, reason, exit_price, cash, positions, trades, protections, i)
                    continue
                self._last_close[sym] = float(bar["close"])
                st["last_close"] = float(bar["close"])
                if atr_val is not None:
                    cash = self._adjust(sym, t, cash, positions, st, atr_val)

            # 2) 信号执行：上一根信号 → 本根开盘
            for sym, d in prepared.items():
                if t not in d.index:
                    continue
                idx_pos = d.index.get_loc(t)
                if idx_pos <= 0:
                    continue
                target = float(d["signal"].iloc[idx_pos - 1])
                if self.risk.trade_direction == "long_only":
                    target = max(0.0, target)
                cur = 0
                if sym in positions:
                    cur = 1 if positions[sym]["side"] == "long" else -1
                if target == cur:
                    continue
                open_price = float(d["open"].iloc[idx_pos])
                if target == 0:
                    if sym in positions:
                        cash = self._close(sym, t, "signal", open_price, cash, positions, trades, protections, i)
                else:
                    if cur != 0:
                        cash = self._close(sym, t, "signal", open_price, cash, positions, trades, protections, i)
                    if sym in positions:
                        continue
                    if len(positions) >= self.max_open_trades:
                        continue
                    allowed, _why = protections.check_entry(sym, i, mark_equity())
                    if not allowed:
                        continue
                    cash = self._open(sym, t, target, open_price, cash, positions, d)

            # 3) 资金费率
            if self.funding_rate_8h and positions:
                for sym, st in positions.items():
                    px = self._last_close.get(sym) or st["entry_price"]
                    funding = abs(st["qty"] * px * self.funding_rate_8h * (bar_sec / (8.0 * 3600.0)))
                    cash -= funding
                    funding_paid += funding

            equity_list.append(mark_equity())

        # 期末强平
        for sym in list(positions.keys()):
            d = prepared[sym]
            last = float(d["close"].iloc[-1])
            cash = self._close(sym, common[-1], "eod", last, cash, positions, trades, protections, len(common) - 1)
        equity_list[-1] = mark_equity()

        equity_curve = pd.Series(equity_list, index=common, dtype=float)
        seconds = self._bar_seconds(prepared)
        periods_per_year = max(int(round(365 * 24 * 3600 / seconds)), 1) if seconds > 0 else 8760
        metrics = compute_metrics(
            equity_curve, trades, self.initial_capital,
            periods_per_year=periods_per_year,
            buy_hold_return=self._portfolio_buy_hold(prepared, common),
        )
        metrics["max_open_trades"] = self.max_open_trades
        metrics["symbols"] = len(prepared)
        metrics["funding_paid"] = round(funding_paid, 4)
        metrics["total_fees"] = float(metrics.get("total_fees", 0.0)) + round(funding_paid, 4)

        per_symbol: dict[str, dict[str, Any]] = {}
        for sym in prepared:
            st = [t for t in trades if t.symbol == sym]
            wins = [t.pnl for t in st if t.pnl > 0]
            losses = [t.pnl for t in st if t.pnl <= 0]
            loss_sum = abs(sum(losses))
            pf = (sum(wins) / loss_sum) if loss_sum > 0 else (None if not wins else float("inf"))
            per_symbol[sym] = {
                "num_trades": len(st),
                "pnl": round(float(sum(t.pnl for t in st)), 4),
                "win_rate": round(len(wins) / len(st), 4) if st else 0.0,
                "profit_factor": (round(float(pf), 4) if pf is not None and pf != float("inf") else (None if pf is None else "inf")),
                "avg_return_pct": round(float(np.mean([t.return_pct for t in st])) * 100, 4) if st else 0.0,
            }

        return PortfolioResult(
            equity_curve=equity_curve,
            trades=trades,
            metrics=metrics,
            per_symbol=per_symbol,
            breakdown=trade_breakdown(trades),
            trade_stats=trade_stats(trades),
        )

    # ------------------------------------------------------------------ #
    def _common_index(self, prepared: dict[str, pd.DataFrame]) -> pd.Index:
        indexes = [d.index for d in prepared.values()]
        common = indexes[0]
        for ix in indexes[1:]:
            common = common.union(ix) if self.align == "outer" else common.intersection(ix)
        common = pd.Index(sorted(common))
        if len(common) < 20:
            raise ValueError("组合数据对齐后不足 20 根 K 线，请检查各标的周期/时间范围是否一致")
        return common

    def _equity(self, cash: float, positions: dict[str, dict[str, Any]]) -> float:
        eq = cash
        for sym, st in positions.items():
            px = self._last_close.get(sym) or st["entry_price"]
            eq += st["qty"] * px
        return eq

    def _check_exit(self, st: dict, t, bar, atr_val) -> tuple[float | None, str | None]:
        side = st["side"]
        entry_price = st["entry_price"]
        stop, target = self.risk.stop_prices(side, entry_price, atr_val)
        stop = self.risk.trailing_stop(side, entry_price, float(bar["close"]), atr_val, stop)
        stop = self.risk.break_even_stop(side, entry_price, float(bar["close"]), atr_val, stop)
        st["current_stop"] = stop
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
        if exit_price is None and st["entry_time"] is not None:
            elapsed_min = float((t - st["entry_time"]).total_seconds()) / 60.0
            roi = self.risk.roi_target(elapsed_min)
            if roi is not None:
                if side == "long":
                    profit_pct = (float(bar["close"]) - entry_price) / entry_price
                else:
                    profit_pct = (entry_price - float(bar["close"])) / entry_price
                if profit_pct >= float(roi):
                    exit_price, reason = float(bar["close"]), "roi"
        return exit_price, reason

    def _open(self, sym, t, direction, price, cash, positions, d) -> float:
        equity = self._equity(cash, positions)
        new_side = "long" if direction > 0 else "short"
        idx = d.index.get_loc(t)
        atr_prev = float(d["atr"].iloc[idx - 1]) if idx > 0 and pd.notna(d["atr"].iloc[idx - 1]) else None
        stop_pct = None
        stop_price = None
        if atr_prev is not None or self.risk.stop_loss_pct:
            sp, _tp = self.risk.stop_prices(new_side, price, atr_prev)
            if sp:
                stop_price = sp
                stop_pct = abs(price - sp) / price
        qty = self.risk.risk_position_size(equity, price, stop_pct)
        if qty <= 0:
            return cash
        fill = price * (1.0 + self.slippage) if direction > 0 else price * (1.0 - self.slippage)
        notional = qty * fill
        fee = notional * self.fee_rate
        leverage = max(float(self.risk.leverage or 1.0), 1e-9)
        if notional / leverage + fee > equity * 1.0001:
            return cash
        if new_side == "long":
            cash -= notional + fee
        else:
            cash += notional - fee
        positions[sym] = {
            "side": new_side,
            "qty": qty,
            "entry_price": fill,
            "entry_time": t,
            "entry_qty": qty,
            "entry_risk": abs(fill - stop_price) * qty if stop_price else 0.0,
            "entry_fees": fee,
            "adjust_count": 0,
            "current_stop": None,
            "last_close": fill,
        }
        self._last_close[sym] = fill
        return cash

    def _adjust(self, sym, t, cash, positions, st, atr_val) -> float:
        if not self.risk.should_adjust(st["side"], st["entry_price"], self._last_close.get(sym) or st["entry_price"], atr_val, st["adjust_count"]):
            return cash
        px = self._last_close.get(sym) or st["entry_price"]
        equity = self._equity(cash, positions)
        add_notional = equity * max(float(self.risk.adjust_step_pct), 0.0)
        add_qty = add_notional / px if px > 0 else 0.0
        if add_qty <= 0:
            return cash
        fill = px * (1.0 + self.slippage) if st["side"] == "long" else px * (1.0 - self.slippage)
        add_notional_fill = add_qty * fill
        fee = add_notional_fill * self.fee_rate
        leverage = max(float(self.risk.leverage or 1.0), 1e-9)
        if add_notional_fill / leverage + fee > equity * 1.0001:
            return cash
        if st["side"] == "long":
            cash -= add_notional_fill + fee
        else:
            cash += add_notional_fill - fee
        old_qty = st["qty"]
        new_qty = old_qty + add_qty
        st["entry_price"] = (st["entry_price"] * old_qty + fill * add_qty) / new_qty
        st["qty"] = new_qty
        st["entry_qty"] = new_qty
        st["entry_fees"] += fee
        st["adjust_count"] += 1
        return cash

    def _close(self, sym, t, reason, price, cash, positions, trades, protections, bar_idx) -> float:
        st = positions.pop(sym)
        qty = abs(st["qty"])
        fill = price * (1.0 - self.slippage) if st["qty"] > 0 else price * (1.0 + self.slippage)
        notional = qty * fill
        fee = notional * self.fee_rate
        entry_fee = float(st["entry_fees"]) if st["entry_fees"] else st["entry_price"] * qty * self.fee_rate
        if st["side"] == "long":
            gross = (fill - st["entry_price"]) * qty
            cash += notional - fee
        else:
            gross = (st["entry_price"] - fill) * qty
            cash -= notional + fee
        pnl = gross - entry_fee - fee
        trades.append(Trade(
            symbol=sym, side=st["side"],
            entry_time=st["entry_time"], entry_price=st["entry_price"],
            exit_time=t, exit_price=fill,
            quantity=qty, fees=entry_fee + fee,
            pnl=pnl, return_pct=pnl / (st["entry_price"] * qty) if st["entry_price"] else 0.0,
            reason=reason, initial_risk=round(st["entry_risk"], 4),
        ))
        protections.record_exit(sym, bar_idx, reason, trades[-1].return_pct)
        return cash

    # ------------------------------------------------------------------ #
    def _bar_seconds(self, prepared: dict[str, pd.DataFrame]) -> float:
        for d in prepared.values():
            if len(d) > 1:
                s = d.index.to_series().diff().dt.total_seconds().median()
                if s and s > 0:
                    return float(s)
        return 3600.0

    def _portfolio_buy_hold(self, prepared: dict[str, pd.DataFrame], common: pd.Index) -> float:
        rets = []
        for sym, d in prepared.items():
            sub = d.reindex(common).dropna(subset=["close"])
            if len(sub) >= 20:
                rets.append(sub["close"].iloc[-1] / sub["close"].iloc[0] - 1.0)
        return float(np.mean(rets)) if rets else 0.0
