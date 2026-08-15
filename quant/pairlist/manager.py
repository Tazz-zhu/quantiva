"""PairListManager —— 动态选币管理器（freqtrade pairlist 移植）。

用法：
    plm = PairListManager(exchange_id="okx", config={...}, proxy="")
    pairs = plm.get_pairs()   # 返回最终交易标的列表
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from quant.pairlist.filters import apply_filters, static_pairlist, volume_pairlist


class PairListManager:
    """按配置生成交易标的列表：静态 / 成交量轮动 + 价格与上新过滤。"""

    def __init__(
        self,
        exchange_id: str = "okx",
        config: dict[str, Any] | None = None,
        proxy: str = "",
    ):
        self.exchange_id = exchange_id
        self.config = config or {}
        self.proxy = proxy
        self._tickers: dict[str, dict] | None = None

    # ------------------------------------------------------------------ #
    def get_pairs(self, refresh_tickers: bool = False) -> list[str]:
        """生成最终标的列表。"""
        cfg = self.config
        method = str(cfg.get("method", "static"))
        symbols = cfg.get("symbols") or []
        exclude = cfg.get("exclude") or []

        if method == "volume":
            tickers = self.tickers(refresh=refresh_tickers)
            pairs = volume_pairlist(
                tickers,
                number_assets=int(cfg.get("number_assets", 10)),
                min_volume=float(cfg.get("min_volume", 0) or 0),
                quote=str(cfg.get("quote", "USDT")),
                exclude=exclude,
            )
        else:
            pairs = [s for s in static_pairlist(symbols) if s not in exclude]

        # 过滤
        pairs = apply_filters(
            pairs, cfg,
            tickers=self._tickers,
            loader=cfg.get("_loader"),
        )
        if not pairs and symbols:
            pairs = [s for s in symbols if s not in exclude][:1]
        return pairs

    # ------------------------------------------------------------------ #
    def tickers(self, refresh: bool = False) -> dict[str, dict]:
        """获取交易所全部 ticker（缓存 5 分钟）。"""
        import time

        now = time.time()
        if self._tickers is not None and not refresh and (now - self._tickers.get("_ts", 0)) < 300:
            return {k: v for k, v in self._tickers.items() if k != "_ts"}
        from quant.data.fetcher import ExchangeDataFetcher

        fetcher = ExchangeDataFetcher(self.exchange_id, proxy=self.proxy)
        try:
            raw = fetcher.exchange.fetch_tickers()
            out = {}
            for sym, t in raw.items():
                out[sym] = {
                    "last": t.get("last"),
                    "close": t.get("close"),
                    "quoteVolume": t.get("quoteVolume"),
                    "baseVolume": t.get("baseVolume"),
                    "percentage": t.get("percentage"),
                }
        finally:
            try:
                fetcher.exchange.close()
            except Exception:  # noqa: BLE001
                pass
        out["_ts"] = time.time()
        self._tickers = out
        return {k: v for k, v in out.items() if k != "_ts"}

    def preview(self, refresh: bool = False) -> dict[str, Any]:
        """预览选币结果：返回每个标的的 24h 成交额与最新价。"""
        pairs = self.get_pairs(refresh_tickers=refresh)
        t = self._tickers or {}
        rows = []
        for i, s in enumerate(pairs, 1):
            info = t.get(s) or {}
            rows.append({
                "rank": i,
                "symbol": s,
                "volume_24h": info.get("quoteVolume"),
                "price": info.get("last") or info.get("close"),
                "change_24h": info.get("percentage"),
            })
        return {
            "method": self.config.get("method", "static"),
            "number_assets": len(pairs),
            "pairs": rows,
        }
