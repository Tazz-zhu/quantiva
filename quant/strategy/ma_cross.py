"""????????

?????????????????????????????
"""

from __future__ import annotations

import pandas as pd

from quant.data.indicators import sma
from quant.strategy.base import Strategy


class MACrossStrategy(Strategy):
    name = "ma_cross"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.fast = int(self.params.get("fast", 20))
        self.slow = int(self.params.get("slow", 50))
        self.direction = self.params.get("direction", "long_only")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fast_ma = sma(close, self.fast)
        slow_ma = sma(close, self.slow)
        above = (fast_ma > slow_ma).astype(float)
        if self.direction == "long_short":
            signal = above * 2.0 - 1.0  # +1 / -1
        else:
            signal = above  # +1 / 0
        return signal.reindex(df.index).fillna(0.0)
