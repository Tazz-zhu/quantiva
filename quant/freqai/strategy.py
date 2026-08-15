"""FreqAIStrategy —— 基于机器学习预测产生交易信号的策略。

- 回归模型：预测值 >= long_threshold 做多，<= -short_threshold 做空（多空模式）
- 分类模型：上涨概率 >= long_threshold 做多，<= 1-long_threshold 做空
预测列由 FreqAIPipeline.backtest() 合并进 OHLCV（freqai_pred / freqai_prob），
信号与其它策略同约定：本根收盘生成、下一根开盘执行，无前视。
"""
from __future__ import annotations

import pandas as pd

from quant.strategy.base import Strategy


class FreqAIStrategy(Strategy):
    name = "freqai"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.kind = str(self.params.get("kind", "regression"))
        self.long_threshold = float(self.params.get("long_threshold", 0.0))
        self.short_threshold = float(self.params.get("short_threshold", 0.0))
        self.direction = str(self.params.get("direction", "long_only"))

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        sig = pd.Series(0.0, index=df.index, dtype=float)
        if self.kind == "classification":
            if "freqai_prob" not in df.columns:
                return sig
            prob = df["freqai_prob"].astype(float)
            sig.loc[prob >= self.long_threshold] = 1.0
            if self.direction == "long_short":
                sig.loc[prob <= 1.0 - self.short_threshold] = -1.0
        else:
            if "freqai_pred" not in df.columns:
                return sig
            pred = df["freqai_pred"].astype(float)
            sig.loc[pred >= self.long_threshold] = 1.0
            if self.direction == "long_short":
                sig.loc[pred <= -self.short_threshold] = -1.0
        return sig.fillna(0.0)
