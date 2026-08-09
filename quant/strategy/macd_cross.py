"""MACD ???????Gerald Appel??

?????DIF ?? DEA ?????????????/???
"""
from __future__ import annotations

import pandas as pd

from quant.data.indicators import macd
from quant.strategy.base import Strategy


class MACDCrossStrategy(Strategy):
    name = "macd_cross"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.fast = int(self.params.get("fast", 12))
        self.slow = int(self.params.get("slow", 26))
        self.signal = int(self.params.get("signal", 9))
        self.direction = self.params.get("direction", "long_only")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        dif, dea, _ = macd(df["close"], self.fast, self.slow, self.signal)
        above = (dif > dea).astype(float)
        if self.direction == "long_short":
            signal = above * 2.0 - 1.0
        else:
            signal = above
        return signal.reindex(df.index).fillna(0.0)
