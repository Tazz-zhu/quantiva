#!/usr/bin/env python3
"""????????????JSON + ???? CSV + ?? PNG??"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from quant.backtest.engine import BacktestEngine  # noqa: E402
from quant.config import load_config  # noqa: E402
from quant.data.fetcher import ExchangeDataFetcher, generate_synthetic_ohlcv  # noqa: E402
from quant.data.storage import SQLiteStorage  # noqa: E402
from quant.report.chart import plot_backtest  # noqa: E402
from quant.risk.manager import RiskManager  # noqa: E402
from quant.strategy import create_strategy  # noqa: E402
from quant.utils.logger import setup_logger  # noqa: E402

METRIC_LABELS = [
    ("total_return", "????"),
    ("annual_return", "?????"),
    ("buy_hold_return", "???????"),
    ("sharpe", "????"),
    ("sortino", "?????"),
    ("volatility", "?????"),
    ("max_drawdown", "????"),
    ("win_rate", "??"),
    ("profit_factor", "???(Profit Factor)"),
    ("num_trades", "????"),
    ("avg_trade_return", "???????"),
    ("avg_holding_hours", "??????(??)"),
    ("total_fees", "????"),
    ("exposure", "?????"),
]

PERCENT_KEYS = {"win_rate", "exposure"}


def main() -> None:
    parser = argparse.ArgumentParser(description="????????")
    parser.add_argument("--config", default="config/config.yaml", help="??????")
    parser.add_argument("--exchange", default=None, help="ccxt ??????? binance/okx/bybit")
    parser.add_argument("--strategy", default=None, help="???: ma_cross | rsi_reversion | bollinger")
    parser.add_argument("--symbol", default=None, help="????? BTC/USDT")
    parser.add_argument("--timeframe", default=None, help="K ????? 1h/4h/1d")
    parser.add_argument("--days", type=int, default=None, help="????")
    parser.add_argument("--synthetic", action="store_true", help="????????????")
    parser.add_argument("--output", default=None, help="???????? reports/btc_ma")
    parser.add_argument("--no-chart", action="store_true", help="?????")
    args = parser.parse_args()

    logger = setup_logger("backtest")
    cfg = load_config(args.config)

    symbol = args.symbol or cfg["data"]["symbol"]
    timeframe = args.timeframe or cfg["data"]["timeframe"]
    days = args.days or cfg["data"]["days"]
    if args.exchange:
        cfg["exchange"]["id"] = args.exchange
    if args.strategy:
        cfg["strategy"]["name"] = args.strategy
    out_prefix = args.output or (
        f"{cfg['report']['output_dir']}/backtest_{symbol.replace('/', '_')}_{timeframe}"
    )

    # 1) ????
    if args.synthetic:
        logger.info("??????: %s %s %d ?", symbol, timeframe, days)
        df = generate_synthetic_ohlcv(timeframe=timeframe, days=days)
    else:
        storage = SQLiteStorage(cfg["data"]["storage_db"])
        df = storage.load_ohlcv(symbol, timeframe)
        if len(df) < 200:
            logger.info("?????????? %s ?? %d ???", cfg["exchange"]["id"], days)
            fetcher = ExchangeDataFetcher(cfg["exchange"]["id"], cfg["exchange"].get("sandbox", False))
            since = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) - days * 86_400_000
            try:
                df = fetcher.fetch_ohlcv(symbol, timeframe, since=since)
            except Exception as exc:  # noqa: BLE001
                logger.error("????: %s", exc)
                logger.error("?????/?????? --synthetic ??????????")
                sys.exit(1)
            storage.save_ohlcv(symbol, timeframe, df)
        storage.close()
        if df.empty:
            logger.error("????????????/??????? --synthetic ????")
            sys.exit(1)

    # 2) ?????
    strategy = create_strategy(cfg["strategy"]["name"], cfg["strategy"].get("params"))
    risk = RiskManager.from_config(cfg["risk"])
    logger.info("??: %s", strategy)
    logger.info("??: %s", risk)

    # 3) ????
    engine = BacktestEngine(
        strategy=strategy,
        data=df,
        initial_capital=cfg["backtest"]["initial_capital"],
        fee_rate=cfg["backtest"]["fee_rate"],
        slippage=cfg["backtest"]["slippage"],
        risk=risk,
        symbol=symbol,
    )
    result = engine.run()
    metrics = result.metrics

    # 4) ?????
    print("\n" + "=" * 62)
    print(f"????  {symbol}  {timeframe}  ?? = {strategy.name}")
    print("=" * 62)
    for key, label in METRIC_LABELS:
        value = metrics.get(key)
        if value is None:
            continue
        if key in PERCENT_KEYS:
            print(f"{label:<18}{value * 100:>12.2f}%")
        elif isinstance(value, float):
            print(f"{label:<18}{value:>12.4f}")
        else:
            print(f"{label:<18}{value:>12}")
    print("=" * 62)

    # 5) ????
    out_dir = Path(out_prefix).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = Path(out_prefix + ".json")
    report_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"JSON ?????: {report_path.resolve()}")

    if result.trades:
        trades_path = Path(out_prefix + "_trades.csv")
        with open(trades_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["side", "entry_time", "entry_price", "exit_time", "exit_price",
                 "quantity", "fees", "pnl", "return_pct", "reason"]
            )
            for t in result.trades:
                writer.writerow([
                    t.side, t.entry_time, f"{t.entry_price:.6f}", t.exit_time,
                    f"{t.exit_price:.6f}", f"{t.quantity:.6f}", f"{t.fees:.4f}",
                    f"{t.pnl:.4f}", f"{t.return_pct:.4%}", t.reason,
                ])
        print(f"???????: {trades_path.resolve()}")

    if not args.no_chart:
        chart_path = plot_backtest(result.data, result.equity_curve, result.trades, Path(out_prefix + ".png"))
        print(f"?????: {chart_path.resolve()}")


if __name__ == "__main__":
    main()
