"""RSI ??????????????????????"""
from __future__ import annotations

import pandas as pd

from quant.data.indicators import rsi
from quant.strategy.base import Strategy


class RSIMeanReversionStrategy(Strategy):
    name = "rsi_reversion"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.period = int(self.params.get("period", 14))
        self.oversold = float(self.params.get("oversold", 30.0))
        self.overbought = float(self.params.get("overbought", 70.0))

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi_series = rsi(df["close"], self.period)
        signal = pd.Series(0.0, index=df.index, dtype=float)
        position = 0
        for i in range(len(df)):
            value = rsi_series.iloc[i]
            if pd.isna(value):
                signal.iloc[i] = float(position)
                continue
            if position == 0 and value < self.oversold:
                position = 1
            elif position == 1 and value > self.overbought:
                position = 0
            signal.iloc[i] = float(position)
        return signal
