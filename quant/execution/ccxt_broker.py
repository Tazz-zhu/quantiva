"""真实交易所执行器（ccxt）。API 密钥从环境变量读取，请勿硬编码；统计执行质量（滑点/延迟/拒单）。"""
from __future__ import annotations

import os
import time

import ccxt

from quant.execution.base import Broker, Order


class CCXTBroker(Broker):
    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str | None = None,
        api_secret: str | None = None,
        sandbox: bool = False,
    ):
        if not hasattr(ccxt, exchange_id):
            raise ValueError("不支持的交易所: " + exchange_id)
        key = api_key or os.getenv("CCXT_API_KEY")
        secret = api_secret or os.getenv("CCXT_API_SECRET")
        if not key or not secret:
            raise ValueError("缺少 API 密钥：请设置环境变量 CCXT_API_KEY / CCXT_API_SECRET")
        self.exchange = getattr(ccxt, exchange_id)({
            "apiKey": key,
            "secret": secret,
            "enableRateLimit": True,
            "sandbox": sandbox,
        })
        self.exchange.load_markets()
        self.exec_quality: dict = {
            "orders": 0, "fills": 0, "rejects": 0,
            "slippage_bps_sum": 0.0, "latency_ms_sum": 0.0,
        }

    def get_balance(self) -> dict:
        bal = self.exchange.fetch_balance()
        return {
            k: float(v["free"])
            for k, v in bal.get("total", {}).items()
            if v and v.get("free")
        }

    def get_ticker(self, symbol: str) -> dict:
        t = self.exchange.fetch_ticker(symbol)
        return {"last": t.get("last"), "bid": t.get("bid"), "ask": t.get("ask")}

    def get_positions(self) -> list:
        return self.exchange.fetch_positions()

    def _record(self, symbol: str, side: str, reference: float, fill: float, submit_ts: float, fill_ts: float) -> None:
        eq = self.exec_quality
        eq["fills"] += 1
        if reference and reference > 0 and fill > 0:
            eq["slippage_bps_sum"] += abs(fill - reference) / reference * 10000.0
        eq["latency_ms_sum"] += max(0.0, (fill_ts - submit_ts) * 1000.0)

    def _record_reject(self, reason: str) -> None:
        # orders 已在 market_order 入口 +1，这里只记拒单
        self.exec_quality["rejects"] += 1

    def market_order(self, symbol: str, side: str, amount: float, price: float | None = None) -> Order:
        self.exec_quality["orders"] += 1
        submit_ts = time.time()
        try:
            result = self.exchange.create_order(symbol, "market", side, amount)
        except Exception as exc:  # noqa: BLE001
            self._record_reject(str(exc)[:100])
            raise
        fill_ts = time.time()
        fill = float(result.get("average") or result.get("price") or 0.0)
        if fill > 0 and price:
            self._record(symbol, side, float(price), fill, submit_ts, fill_ts)
        else:
            self.exec_quality["fills"] += 1
        return Order(
            id=str(result.get("id")),
            symbol=result.get("symbol", symbol),
            side=result.get("side", side),
            type=result.get("type", "market"),
            amount=float(result.get("amount") or 0.0),
            price=result.get("average") or result.get("price"),
            status=result.get("status", "unknown"),
            filled=float(result.get("filled") or 0.0),
            avg_price=result.get("average"),
        )
