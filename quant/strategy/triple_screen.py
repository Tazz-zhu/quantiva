"""?????????Alexander Elder?????

???????????
1. ????????????????????
2. ?????RSI(2) ?????????????
3. ??????????????????
"""
from __future__ import annotations

import pandas as pd

from quant.data.indicators import ema, rsi, sma
from quant.strategy.base import Strategy


class TripleScreenStrategy(Strategy):
    name = "triple_screen"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.fast_ma = int(self.params.get("fast_ma", 50))
        self.slow_ma = int(self.params.get("slow_ma", 200))
        self.rsi_period = int(self.params.get("rsi_period", 2))
        self.oversold = float(self.params.get("oversold", 30.0))
        self.overbought = float(self.params.get("overbought", 70.0))

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        trend_up = ema(close, self.fast_ma) > ema(close, self.slow_ma)
        r = rsi(close, self.rsi_period)
        confirm = close > sma(close, 5)
        signal = pd.Series(0.0, index=df.index, dtype=float)
        position = 0
        for i in range(len(df)):
            if pd.isna(trend_up.iloc[i]) or pd.isna(r.iloc[i]):
                signal.iloc[i] = position
                continue
            if position == 0 and bool(trend_up.iloc[i]) and r.iloc[i] < self.oversold and bool(confirm.iloc[i]):
                position = 1
            elif position == 1 and (r.iloc[i] > self.overbought or not bool(trend_up.iloc[i])):
                position = 0
            signal.iloc[i] = position
        return signal
