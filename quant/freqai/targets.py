"""标签（目标）工程 —— 前瞻收益 / 涨跌分类 / 波动率缩放。

freqtrade FreqAI 的标签本质是"未来 h 根 K 线的收益"（&-s 标签），
并支持按波动率缩放、二值化。训练时必须配合 purge/embargo 防止标签泄漏。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_targets(
    df: pd.DataFrame,
    horizon: int = 5,
    kind: str = "regression",
    scale_by_atr: bool = True,
) -> pd.DataFrame:
    """构造标签矩阵。

    参数
    ----
    horizon:        预测周期（未来 h 根 K 线收益）
    kind:           "regression"（连续收益）/ "classification"（涨跌 0/1）
    scale_by_atr:   是否用 ATR 缩放（FreqAI 风格，降低波动率异方差）

    返回
    ----
    与 df 对齐的 DataFrame，列为 target（回归）或 target（分类 0/1）。
    最后 horizon 行为 NaN（无法构造完整未来窗口）。
    """
    close = df["close"].astype(float)
    fwd = close.shift(-horizon) / close - 1.0

    out = pd.DataFrame(index=df.index)
    if kind == "classification":
        t = (fwd > 0).astype(float)
        t.loc[fwd.isna()] = np.nan
        out["target"] = t
    else:
        if scale_by_atr and "high" in df and "low" in df:
            from quant.data.indicators import atr
            atr_val = atr(df, 14)
            out["target"] = fwd / atr_val.replace(0.0, np.nan)
        else:
            out["target"] = fwd
    return out
