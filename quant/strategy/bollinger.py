"""?????????????????????????????"""
from __future__ import annotations

import pandas as pd

from quant.data.indicators import bollinger
from quant.strategy.base import Strategy


class BollingerReversionStrategy(Strategy):
    name = "bollinger"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.period = int(self.params.get("period", 20))
        self.num_std = float(self.params.get("num_std", 2.0))

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        mid, _, lower = bollinger(close, self.period, self.num_std)
        signal = pd.Series(0.0, index=df.index, dtype=float)
        position = 0
        for i in range(len(df)):
            low_val = lower.iloc[i]
            mid_val = mid.iloc[i]
            if pd.isna(low_val) or pd.isna(mid_val):
                signal.iloc[i] = float(position)
                continue
            if position == 0 and close.iloc[i] < low_val:
                position = 1
            elif position == 1 and close.iloc[i] > mid_val:
                position = 0
            signal.iloc[i] = float(position)
        return signal
