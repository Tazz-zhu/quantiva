"""???????Mark Minervini / Richard Driehaus??

???????? N ???????????????????? N ??????
"""
from __future__ import annotations

import pandas as pd

from quant.data.indicators import sma
from quant.strategy.base import Strategy


class MomentumBreakoutStrategy(Strategy):
    name = "momentum"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.lookback = int(self.params.get("lookback", 50))
        self.exit_ma = int(self.params.get("exit_ma", 20))

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        high = df["high"]
        prior_high = high.rolling(self.lookback).max().shift(1)  # ???????
        ma = sma(close, self.exit_ma)
        signal = pd.Series(0.0, index=df.index, dtype=float)
        position = 0
        for i in range(len(df)):
            if pd.isna(prior_high.iloc[i]):
                signal.iloc[i] = position
                continue
            if position == 0 and close.iloc[i] > prior_high.iloc[i]:
                position = 1
            elif position == 1 and (close.iloc[i] < ma.iloc[i] or close.iloc[i] < prior_high.iloc[i] * 0.93):
                position = 0
            signal.iloc[i] = position
        return signal
