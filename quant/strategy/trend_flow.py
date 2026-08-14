"""TrendFlow 突破策略 —— 趋势过滤 + Donchian 突破 + ATR 通道退出 + 波动率下限

设计思路（趋势跟踪流派）：
1. 趋势过滤：仅当价格站上慢速 EMA 且快慢 EMA 多头排列时做多（避免震荡市）；
2. 突破入场：收盘价突破 N 期 Donchian 上轨（不含当前 K 线，防前视）；
3. ATR 通道退出：跌破「滚动最高价 - exit_atr_mult * ATR」离场，让利润奔跑；
4. 波动率下限：ATR% 低于阈值时放弃入场（过滤死水行情），0 表示关闭。

信号在收盘后生成、下一根 K 线开盘执行（与回测引擎约定一致）。
"""
from __future__ import annotations

import pandas as pd

from quant.data.indicators import adx, atr, ema
from quant.strategy.base import Strategy


class TrendFlowStrategy(Strategy):
    name = "trend_flow"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.fast_ma = int(self.params.get("fast_ma", 20))
        self.slow_ma = int(self.params.get("slow_ma", 60))
        self.entry_lookback = int(self.params.get("entry_lookback", 20))
        self.exit_atr_mult = float(self.params.get("exit_atr_mult", 3.0))
        self.min_atr_pct = float(self.params.get("min_atr_pct", 0.0))  # 单位 %，0 = 关闭
        self.min_adx = float(self.params.get("min_adx", 0.0))  # ADX trend-strength floor, 0 = off
        self.direction = self.params.get("direction", "long_only")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        fast = ema(close, self.fast_ma)
        slow = ema(close, self.slow_ma)
        atr14 = atr(df, 14)
        atr_pct = atr14 / close

        # 前一根 K 线已确认的 Donchian 通道（防前视偏差）
        dc_high = high.rolling(self.entry_lookback).max().shift(1)
        dc_low = low.rolling(self.entry_lookback).min().shift(1)

        if self.exit_atr_mult > 0:
            exit_long = dc_high - self.exit_atr_mult * atr14
            exit_short = dc_low + self.exit_atr_mult * atr14
        else:  # 未启用 ATR 通道时回退到快线
            exit_long = fast
            exit_short = fast

        vol_ok = (self.min_atr_pct <= 0) | (atr_pct >= self.min_atr_pct / 100.0)
        adx14 = adx(df, 14)
        trend_ok = (self.min_adx <= 0) | (adx14 >= self.min_adx)
        adx14 = adx(df, 14)
        trend_ok = (self.min_adx <= 0) | (adx14 >= self.min_adx)

        long_entry = vol_ok & trend_ok & (close > slow) & (fast > slow) & (close > dc_high)
        long_exit = (close < exit_long) | (close < fast)
        short_entry = vol_ok & trend_ok & (close < slow) & (fast < slow) & (close < dc_low)
        short_exit = (close > exit_short) | (close > fast)

        signal = pd.Series(0.0, index=df.index, dtype=float)
        pos = 0
        for i in range(len(df)):
            if pos == 0:
                if bool(long_entry.iloc[i]):
                    pos = 1
                elif self.direction == "long_short" and bool(short_entry.iloc[i]):
                    pos = -1
            elif pos == 1:
                if bool(long_exit.iloc[i]):
                    pos = 0
                elif self.direction == "long_short" and bool(short_entry.iloc[i]):
                    pos = -1  # 直接反向
            else:  # pos == -1
                if bool(short_exit.iloc[i]):
                    pos = 0
                elif self.direction == "long_short" and bool(long_entry.iloc[i]):
                    pos = 1  # 直接反向
            signal.iloc[i] = pos
        return signal