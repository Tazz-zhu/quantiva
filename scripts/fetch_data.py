#!/usr/bin/env python3
"""?? K ?????? SQLite????? CSV??"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from quant.config import load_config  # noqa: E402
from quant.data.fetcher import ExchangeDataFetcher  # noqa: E402
from quant.data.storage import SQLiteStorage  # noqa: E402
from quant.utils.logger import setup_logger  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="??????")
    parser.add_argument("--config", default="config/config.yaml", help="??????")
    parser.add_argument("--exchange", default=None, help="ccxt ??????? binance/okx/bybit")
    parser.add_argument("--symbol", default=None, help="????? BTC/USDT")
    parser.add_argument("--timeframe", default=None, help="K ????? 1h/4h/1d")
    parser.add_argument("--days", type=int, default=None, help="????")
    parser.add_argument("--csv", default=None, help="????? CSV ????")
    args = parser.parse_args()

    logger = setup_logger("fetch")
    cfg = load_config(args.config)
    symbol = args.symbol or cfg["data"]["symbol"]
    timeframe = args.timeframe or cfg["data"]["timeframe"]
    days = args.days or cfg["data"]["days"]
    if args.exchange:
        cfg["exchange"]["id"] = args.exchange
    storage = SQLiteStorage(cfg["data"]["storage_db"])

    logger.info("? %s ??: %s %s %d ?", cfg["exchange"]["id"], symbol, timeframe, days)
    fetcher = ExchangeDataFetcher(cfg["exchange"]["id"], cfg["exchange"].get("sandbox", False))
    since = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) - days * 86_400_000
    try:
        df = fetcher.fetch_ohlcv(symbol, timeframe, since=since)
    except Exception as exc:  # noqa: BLE001
        logger.error("????: %s", exc)
        logger.error("请检查网络/代理后重试，仅支持交易所真实数据")
        sys.exit(1)

    if df.empty:
        logger.error("??????")
        sys.exit(1)

    n = storage.save_ohlcv(symbol, timeframe, df)
    logger.info("??? %d ? K ?? %s", n, storage.db_path)
    logger.info(
        "??: %s ~ %s??????: %.2f",
        df.index[0], df.index[-1], df["close"].iloc[-1],
    )
    if args.csv:
        df.to_csv(args.csv, encoding="utf-8")
        logger.info("??? CSV: %s", args.csv)
    storage.close()


if __name__ == "__main__":
    main()
