"""模拟盘执行器：内部记账，无真实资金与网络请求，并统计执行质量（滑点/成交/拒单/延迟）。"""
from __future__ import annotations

import time
import uuid

from quant.execution.base import Broker, Order


class PaperBroker(Broker):
    def __init__(
        self,
        initial_balance: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage: float = 0.0005,
        quote: str = "USDT",
    ):
        self.cash = float(initial_balance)
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.quote = quote
        self.positions: dict[str, float] = {}
        self.trades: list[Order] = []
        self.exec_quality: dict = {
            "orders": 0, "fills": 0, "rejects": 0,
            "slippage_bps_sum": 0.0, "latency_ms_sum": 0.0,
        }

    def get_balance(self) -> dict:
        return {self.quote: self.cash}

    def get_ticker(self, symbol: str) -> dict:
        return {"last": None, "bid": None, "ask": None}

    def get_positions(self) -> list:
        return [{"symbol": s, "amount": a} for s, a in self.positions.items() if a]

    def _record(self, symbol: str, side: str, reference: float, fill: float, submit_ts: float, fill_ts: float) -> None:
        eq = self.exec_quality
        eq["fills"] += 1
        if reference and reference > 0:
            eq["slippage_bps_sum"] += abs(fill - reference) / reference * 10000.0
        eq["latency_ms_sum"] += max(0.0, (fill_ts - submit_ts) * 1000.0)

    def _record_reject(self, reason: str) -> None:
        # orders 已在 market_order 入口 +1，这里只记拒单
        self.exec_quality["rejects"] += 1

    def market_order(self, symbol: str, side: str, amount: float, price: float | None = None) -> Order:
        if price is None:
            raise ValueError("模拟盘下单需要提供参考价格 price")
        self.exec_quality["orders"] += 1
        submit_ts = time.time()
        if side not in ("buy", "sell"):
            self._record_reject("未知方向")
            raise ValueError("未知方向: " + side)
        fill = price * (1.0 + self.slippage) if side == "buy" else price * (1.0 - self.slippage)
        notional = fill * amount
        fee = notional * self.fee_rate
        if side == "buy":
            if notional + fee > self.cash + 1e-9:
                self._record_reject("余额不足")
                raise ValueError("模拟盘余额不足: 需要 " + format(notional + fee, ".4f") + " " + self.quote + "，可用 " + format(self.cash, ".4f"))
            self.cash -= notional + fee
            self.positions[symbol] = self.positions.get(symbol, 0.0) + amount
        else:
            # 允许卖出超过现有持仓（产生负仓位 = 模拟做空，保证金记账）
            self.cash += notional - fee
            self.positions[symbol] = self.positions.get(symbol, 0.0) - amount

        self._record(symbol, side, price, fill, submit_ts, time.time())
        order = Order(
            id="paper-" + uuid.uuid4().hex[:12],
            symbol=symbol,
            side=side,
            type="market",
            amount=amount,
            price=fill,
            status="closed",
            filled=amount,
            avg_price=fill,
        )
        self.trades.append(order)
        return order
