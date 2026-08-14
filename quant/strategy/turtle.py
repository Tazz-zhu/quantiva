"""???????Richard Dennis / William Eckhardt?????????? + ?????

??????? 20 ???????? 10 ?????????????????
"""
from __future__ import annotations

import pandas as pd

from quant.data.indicators import donchian
from quant.strategy.base import Strategy


class TurtleStrategy(Strategy):
    name = "turtle"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.entry_period = int(self.params.get("entry_period", 20))
        self.exit_period = int(self.params.get("exit_period", 10))
        self.direction = self.params.get("direction", "long_only")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        up_entry, _ = donchian(df, self.entry_period)
        _, low_exit = donchian(df, self.exit_period)
        up_entry = up_entry.shift(1)  # ???? K ?????????????? K ?????
        low_exit = low_exit.shift(1)
        signal = pd.Series(0.0, index=df.index, dtype=float)
        position = 0
        for i in range(len(df)):
            c = close.iloc[i]
            if position == 0 and pd.notna(up_entry.iloc[i]) and c > up_entry.iloc[i]:
                position = 1
            elif position == 1 and pd.notna(low_exit.iloc[i]) and c < low_exit.iloc[i]:
                position = -1 if self.direction == "long_short" else 0
            elif position == -1 and pd.notna(up_entry.iloc[i]) and c > up_entry.iloc[i]:
                position = 1
            signal.iloc[i] = position
        return signal
