#!/usr/bin/env python3
"""????? / ???????"""
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

from quant.config import load_config  # noqa: E402
from quant.data.fetcher import ExchangeDataFetcher  # noqa: E402
from quant.data.storage import SQLiteStorage  # noqa: E402
from quant.execution.ccxt_broker import CCXTBroker  # noqa: E402
from quant.execution.paper import PaperBroker  # noqa: E402
from quant.live.trader import LiveTrader  # noqa: E402
from quant.risk.manager import RiskManager  # noqa: E402
from quant.strategy import create_strategy  # noqa: E402
from quant.utils.logger import setup_logger  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="????/?????")
    parser.add_argument("--config", default="config/config.yaml", help="??????")
    parser.add_argument("--exchange", default=None, help="ccxt ??????? binance/okx/bybit")
    parser.add_argument("--mode", choices=["paper", "live"], default=None, help="????????")
    parser.add_argument("--symbol", default=None, help="????? BTC/USDT")
    parser.add_argument("--timeframe", default=None, help="K ???")
    args = parser.parse_args()

    logger = setup_logger("run_live")
    cfg = load_config(args.config)
    if args.exchange:
        cfg["exchange"]["id"] = args.exchange
    if args.mode:
        cfg["live"]["mode"] = args.mode
    if args.symbol:
        cfg["data"]["symbol"] = args.symbol
    if args.timeframe:
        cfg["data"]["timeframe"] = args.timeframe

    symbol = cfg["data"]["symbol"]
    timeframe = cfg["data"]["timeframe"]
    mode = cfg["live"]["mode"]

    strategy = create_strategy(cfg["strategy"]["name"], cfg["strategy"].get("params"))
    risk = RiskManager.from_config(cfg["risk"])
    fetcher = ExchangeDataFetcher(cfg["exchange"]["id"], cfg["exchange"].get("sandbox", False))
    storage = SQLiteStorage(cfg["data"]["storage_db"])

    if mode == "paper":
        broker = PaperBroker(
            initial_balance=cfg["live"].get("paper_initial_balance", 10000.0),
            fee_rate=cfg["backtest"]["fee_rate"],
            slippage=cfg["backtest"]["slippage"],
        )
    else:
        broker = CCXTBroker(cfg["exchange"]["id"], sandbox=cfg["exchange"].get("sandbox", False))

    logger.info("??=%s ??=%s ??=%s ??=%s", mode, strategy.name, symbol, timeframe)
    trader = LiveTrader(cfg, broker, strategy, fetcher, storage=storage, risk=risk, logger=logger)
    trader.run()


if __name__ == "__main__":
    main()
