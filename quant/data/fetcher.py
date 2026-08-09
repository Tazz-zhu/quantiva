"""?????????????ccxt?????????"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from quant.utils.logger import setup_logger

logger = setup_logger(__name__)

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

PANDAS_FREQ_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1D",
    "1w": "1W",
}


def to_pandas_freq(timeframe: str) -> str:
    """?????????? 1m/4h/1d???? pandas 3.0 ?????????"""
    if timeframe not in PANDAS_FREQ_MAP:
        raise ValueError(f"???? timeframe: {timeframe}")
    return PANDAS_FREQ_MAP[timeframe]


TIMEFRAME_NANOS = {
    "1m": 60 * 1_000_000_000,
    "5m": 5 * 60 * 1_000_000_000,
    "15m": 15 * 60 * 1_000_000_000,
    "30m": 30 * 60 * 1_000_000_000,
    "1h": 3600 * 1_000_000_000,
    "2h": 2 * 3600 * 1_000_000_000,
    "4h": 4 * 3600 * 1_000_000_000,
    "6h": 6 * 3600 * 1_000_000_000,
    "12h": 12 * 3600 * 1_000_000_000,
    "1d": 24 * 3600 * 1_000_000_000,
    "1w": 7 * 24 * 3600 * 1_000_000_000,
}


class ExchangeDataFetcher:
    """?? ccxt ?????? K ??????????? API ????"""

    def __init__(self, exchange_id: str = "binance", sandbox: bool = False, proxy: str = ""):
        import ccxt

        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"???????: {exchange_id}")
        exchange_cls = getattr(ccxt, exchange_id)
        params = {"enableRateLimit": True, "sandbox": sandbox}
        if proxy:
            params["proxies"] = {"http": proxy, "https": proxy}
        self.exchange = exchange_cls(params)
        logger.info("??????: %s", exchange_id)

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """???? K ??????????? UTC ?? DataFrame?"""
        raw = self.exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, since=since, limit=limit
        )
        if not raw:
            return pd.DataFrame(columns=["timestamp"] + OHLCV_COLUMNS)
        df = pd.DataFrame(raw, columns=["timestamp"] + OHLCV_COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp").astype(float)
        return df[OHLCV_COLUMNS]

    def fetch_ohlcv_paginated(
        self,
        symbol: str,
        timeframe: str,
        days: int | None = None,
        since: int | None = None,
        max_pages: int = 300,
    ) -> pd.DataFrame:
        """???????? K ???? days ??????????

        ????? fetch_ohlcv ?????? 1000 ????? 730 ? 1h
        ??? 95% ????????????????????????
        """
        freq_nanos = TIMEFRAME_NANOS.get(timeframe)
        if freq_nanos is None:
            raise ValueError(f"????????: {timeframe}")
        freq_ms = freq_nanos // 1_000_000
        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        if since is None:
            if days is None:
                raise ValueError("days ? since ??????")
            since = now_ms - int(days) * 86_400_000
        elif days is not None:
            since = max(since, now_ms - int(days) * 86_400_000)

        # OKX 等交易所单页最多返回 300 根；用 300 作为分页步长可兼容多数交易所
        page_limit = 300
        cursor = int(since)
        frames: list[pd.DataFrame] = []
        for _ in range(max_pages):
            raw = self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=cursor, limit=page_limit
            )
            if not raw:
                break
            frames.append(pd.DataFrame(raw, columns=["timestamp"] + OHLCV_COLUMNS))
            last_ts = int(raw[-1][0])
            if len(raw) < page_limit:
                break
            next_ts = last_ts + freq_ms
            if next_ts <= cursor or last_ts >= now_ms - freq_ms:
                break
            cursor = next_ts

        if not frames:
            return pd.DataFrame(columns=["timestamp"] + OHLCV_COLUMNS)
        raw = pd.concat(frames, ignore_index=True)
        raw = raw.drop_duplicates(subset="timestamp").sort_values("timestamp")
        df = pd.DataFrame(raw, columns=["timestamp"] + OHLCV_COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp").astype(float)
        return df[OHLCV_COLUMNS]


def generate_synthetic_ohlcv(
    timeframe: str = "1h",
    days: int = 730,
    base_price: float = 40000.0,
    annual_vol: float = 0.8,
    drift: float = 0.2,
    seed: int = 42,
) -> pd.DataFrame:
    """????????????? + ????????????????"""
    freq_nanos = TIMEFRAME_NANOS.get(timeframe)
    if freq_nanos is None:
        raise ValueError(f"???? timeframe: {timeframe}")
    freq = pd.tseries.frequencies.to_offset(to_pandas_freq(timeframe))
    periods = int(pd.Timedelta(days=days) / pd.Timedelta(nanoseconds=freq_nanos))
    rng = np.random.default_rng(seed)

    dt = freq_nanos / (365 * 24 * 3600 * 1_000_000_000)
    mu = drift * dt
    sigma = annual_vol * np.sqrt(dt)

    rets = rng.normal(mu, sigma, periods)
    jump_idx = rng.random(periods) < 0.002
    rets[jump_idx] += rng.normal(0.0, sigma * 3.0, int(jump_idx.sum()))

    close = base_price * np.cumprod(1.0 + rets)
    open_ = np.empty(periods)
    open_[0] = base_price
    open_[1:] = close[:-1]

    spread = np.abs(rng.normal(0.0, sigma * 0.3, periods))
    high = np.maximum(open_, close) * (1.0 + spread)
    low = np.minimum(open_, close) * (1.0 - spread)
    volume = rng.lognormal(mean=0.0, sigma=0.5, size=periods) * (base_price / 50.0)

    index = pd.date_range(
        end=pd.Timestamp.now(tz="UTC").floor(freq),
        periods=periods,
        freq=freq,
    )
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
    df.index.name = "timestamp"
    return df
