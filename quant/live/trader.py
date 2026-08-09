"""?? / ????????

????????? K ? ? ???? ? ???? ? ???? ? ??????
??????????????????????????????? PaperBroker?
"""
from __future__ import annotations

import time

import pandas as pd

from quant.data.fetcher import ExchangeDataFetcher
from quant.execution.base import Broker
from quant.risk.manager import RiskManager
from quant.strategy.base import Strategy
from quant.utils.logger import setup_logger


class LiveTrader:
    def __init__(
        self,
        config: dict,
        broker: Broker,
        strategy: Strategy,
        fetcher: ExchangeDataFetcher,
        storage=None,
        risk: RiskManager | None = None,
        logger=None,
    ):
        self.cfg = config
        self.broker = broker
        self.strategy = strategy
        self.fetcher = fetcher
        self.storage = storage
        self.risk = risk or RiskManager()
        self.logger = logger or setup_logger("live")

        self.symbol = config["data"]["symbol"]
        self.timeframe = config["data"]["timeframe"]
        self.quote = config.get("data", {}).get("quote", "USDT")
        live_cfg = config.get("live", {})
        self.poll_interval = float(live_cfg.get("poll_interval_sec", 60))
        self.warmup_bars = int(live_cfg.get("warmup_bars", 200))
        self.df = pd.DataFrame()

    # ------------------------------------------------------------------ #
    def _refresh_data(self) -> None:
        df = self.fetcher.fetch_ohlcv(self.symbol, self.timeframe, limit=self.warmup_bars + 5)
        if df.empty:
            self.logger.warning("????????")
            return
        if self.storage is not None:
            self.storage.save_ohlcv(self.symbol, self.timeframe, df)
        self.df = df

    def _position_qty(self) -> float:
        qty = 0.0
        for pos in self.broker.get_positions():
            if pos.get("symbol") == self.symbol:
                qty += float(pos.get("amount") or 0.0)
        return qty

    def _equity(self, price: float) -> float:
        balance = self.broker.get_balance()
        cash = float(balance.get(self.quote, 0.0))
        return cash + self._position_qty() * price

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        mode = self.cfg.get("live", {}).get("mode", "paper")
        self.logger.info(
            "?? %s ????: %s @ %s????? %.0f ?",
            mode,
            self.symbol,
            self.timeframe,
            self.poll_interval,
        )
        while True:
            try:
                self._refresh_data()
                if len(self.df) < self.warmup_bars:
                    self.logger.warning("???????%d/%d???????", len(self.df), self.warmup_bars)
                    time.sleep(self.poll_interval)
                    continue

                signal = float(self.strategy.generate_signals(self.df).iloc[-1])
                price = float(self.df["close"].iloc[-1])
                pos_qty = self._position_qty()
                equity = self._equity(price)
                current_side = 1 if pos_qty > 0 else (-1 if pos_qty < 0 else 0)
                target = max(0.0, signal) if self.risk.trade_direction == "long_only" else signal
                target_side = 1 if target > 0 else (-1 if target < 0 else 0)

                self.logger.info(
                    "??=%.2f ??=%+.0f ??=%+.0f ??=%.6f ??=%.2f",
                    price, signal, target, pos_qty, equity,
                )
                if target_side == current_side:
                    pass  # ????
                elif target_side == 0:
                    self.broker.market_order(
                        self.symbol, "sell" if pos_qty > 0 else "buy", abs(pos_qty), price=price
                    )
                    self.logger.info("????")
                else:
                    # ???????
                    if pos_qty != 0 and current_side != target_side:
                        self.broker.market_order(
                            self.symbol, "sell" if pos_qty > 0 else "buy", abs(pos_qty), price=price
                        )
                    qty = self.risk.position_size(equity, price)
                    if qty <= 0:
                        self.logger.warning("????? 0?????")
                    else:
                        self.broker.market_order(
                            self.symbol, "buy" if target_side > 0 else "sell", qty, price=price
                        )
                        self.logger.info("?%s %.6f", "?" if target_side > 0 else "?", qty)

                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                self.logger.info("?????????????")
                break
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("??????: %s", exc)
                time.sleep(self.poll_interval)
