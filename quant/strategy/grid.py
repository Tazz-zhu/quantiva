"""??/????????????????

??????????????N ????????????N ???????
"""
from __future__ import annotations

import pandas as pd

from quant.strategy.base import Strategy


class GridStrategy(Strategy):
    name = "grid"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.period = int(self.params.get("period", 20))

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        upper = high.rolling(self.period).max()
        lower = low.rolling(self.period).min()
        signal = pd.Series(0.0, index=df.index, dtype=float)
        position = 0
        for i in range(len(df)):
            if pd.isna(lower.iloc[i]) or pd.isna(upper.iloc[i]):
                signal.iloc[i] = position
                continue
            if position == 0 and close.iloc[i] < lower.iloc[i]:
                position = 1
            elif position == 1 and close.iloc[i] > upper.iloc[i]:
                position = 0
            signal.iloc[i] = position
        return signal
