"""pairlist 过滤器实现。"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "MATIC/USDT", "LTC/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "INJ/USDT", "TIA/USDT",
    "SUI/USDT", "SEI/USDT", "FIL/USDT", "ATOM/USDT", "ETC/USDT", "UNI/USDT",
    "AAVE/USDT", "MKR/USDT", "RUNE/USDT", "CRV/USDT", "TON/USDT", "TRX/USDT",
]


def static_pairlist(symbols: list[str] | None) -> list[str]:
    """StaticPairList：返回配置的固定币种（缺省用内置默认列表）。"""
    return [s for s in (symbols or DEFAULT_SYMBOLS) if s]


def volume_pairlist(
    tickers: dict[str, dict],
    number_assets: int = 10,
    min_volume: float = 0.0,
    quote: str = "USDT",
    exclude: list[str] | None = None,
) -> list[str]:
    """VolumePairList：按 24h 成交额（quoteVolume）降序取 Top N。

    tickers: ccxt fetch_tickers() 结果，键为 "BTC/USDT"。
    """
    exclude = set(exclude or [])
    rows = []
    for sym, t in (tickers or {}).items():
        if not sym.endswith("/" + quote):
            continue
        if sym in exclude:
            continue
        vol = float(t.get("quoteVolume") or 0.0)
        price = float(t.get("last") or t.get("close") or 0.0) or 0.0
        if vol < min_volume or price <= 0:
            continue
        rows.append({"symbol": sym, "volume": vol, "price": price})
    rows.sort(key=lambda r: r["volume"], reverse=True)
    return [r["symbol"] for r in rows[: number_assets]]


def price_filter(symbols: list[str], tickers: dict[str, dict], price_min: float | None, price_max: float | None) -> list[str]:
    """PriceFilter：按最新价剔除过贵/过便宜的币。"""
    if price_min is None and price_max is None:
        return symbols
    out = []
    for s in symbols:
        t = (tickers or {}).get(s) or {}
        price = float(t.get("last") or t.get("close") or 0.0) or 0.0
        if price <= 0:
            continue
        if price_min is not None and price < price_min:
            continue
        if price_max is not None and price > price_max:
            continue
        out.append(s)
    return out


def age_filter(
    symbols: list[str],
    loader: Callable[[str], pd.DataFrame],
    min_days: float = 30.0,
    timeframe: str = "1d",
) -> list[str]:
    """AgeFilter：剔除本地/交易所历史不足 min_days 的币。

    loader: 接收 symbol，返回该 symbol 的 OHLCV DataFrame。
    """
    if min_days <= 0:
        return symbols
    out = []
    for s in symbols:
        try:
            df = loader(s)
            if df is None or len(df) < max(2, int(min_days)):
                continue
            span_days = (df.index[-1] - df.index[0]).total_seconds() / 86400.0
            if span_days >= min_days:
                out.append(s)
        except Exception:  # noqa: BLE001
            continue
    return out


def apply_filters(
    symbols: list[str],
    config: dict[str, Any],
    tickers: dict[str, dict] | None = None,
    loader: Callable[[str], pd.DataFrame] | None = None,
) -> list[str]:
    """按配置依次应用价格过滤与上新过滤。"""
    symbols = price_filter(
        symbols, tickers or {},
        config.get("price_min"), config.get("price_max"),
    )
    if loader is not None:
        symbols = age_filter(
            symbols, loader,
            float(config.get("min_age_days", 0) or 0),
            str(config.get("timeframe", "1d")),
        )
    return symbols
