# -*- coding: utf-8 -*-
"""测试用真实行情 fixture 加载器。

数据来源：OKX 交易所真实 K 线（BTC/USDT），抓取后以 CSV 形式保存在 tests/fixtures/。
本模块仅用于单元测试，确保测试使用的是交易所真实数据而非合成数据。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURES = {
    "1h": "ohlcv_btc_1h.csv",
    "4h": "ohlcv_btc_4h.csv",
}


def load_real_ohlcv(timeframe: str = "1h", n: int | None = None) -> pd.DataFrame:
    """读取真实交易所 K 线 fixture；n 指定只取最近 n 根。"""
    path = FIXTURE_DIR / FIXTURES[timeframe]
    if not path.exists():
        raise FileNotFoundError("缺少真实行情 fixture: " + str(path))
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    return df.tail(n) if n is not None else df
