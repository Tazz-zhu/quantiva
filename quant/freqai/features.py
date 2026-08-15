"""技术指标特征工程 —— 全部使用历史数据（因果），杜绝前视。

与 freqtrade FreqAI 的特征集思路一致：收益率、波动率、动量、均值回归、
成交量、通道位置等，通过不同回看周期构造多尺度特征矩阵。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.data.indicators import atr, bollinger, macd, rsi, sma


def _roc(series: pd.Series, n: int) -> pd.Series:
    return series.pct_change(n)


def build_features(
    df: pd.DataFrame,
    lookbacks: tuple[int, ...] = (5, 10, 20, 50),
    include_volume: bool = True,
    corr_data: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """从 OHLCV 数据构造特征矩阵（返回与 df 对齐的 DataFrame）。

    特征组：
    - 收益率 ROC（多周期）
    - 波动率（收益滚动标准差）与 ATR 比率
    - RSI / MACD / 布林 %B / 带宽
    - 均线偏离（close/SMA、EMA 比值）
    - 通道位置（Donchian）
    - 成交量比率（量/量均、量 Z 分数）
    - 关联对特征（corr_data）：用其它币种收益/比值做横截面特征（freqtrade FreqAI 关联对）
    """
    feat = pd.DataFrame(index=df.index)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float) if include_volume and "volume" in df else None

    # 1) 收益率
    for n in lookbacks:
        feat[f"roc_{n}"] = _roc(close, n)

    # 2) 波动率
    ret = close.pct_change()
    for n in (5, 10, 20):
        feat[f"vol_{n}"] = ret.rolling(n, min_periods=n).std()
    feat["atr_ratio"] = atr(df, 14) / close

    # 3) RSI
    feat["rsi_7"] = rsi(close, 7)
    feat["rsi_14"] = rsi(close, 14)

    # 4) MACD
    dif, dea, hist = macd(close)
    feat["macd_dif"] = dif
    feat["macd_dea"] = dea
    feat["macd_hist"] = hist

    # 5) 布林带
    mid, upper, lower = bollinger(close, 20, 2.0)
    bb_range = (upper - lower).replace(0.0, np.nan)
    feat["bb_pctb"] = (close - lower) / bb_range
    feat["bb_width"] = (upper - lower) / mid.replace(0.0, np.nan)

    # 6) 均线偏离
    for n in (10, 20, 50):
        s = sma(close, n)
        feat[f"close_sma_{n}"] = close / s.replace(0.0, np.nan) - 1.0
        feat[f"ema_{n}_ratio"] = close.ewm(span=n, adjust=False).mean() / close - 1.0

    # 7) 通道位置（Donchian）
    for n in (20, 50):
        hi = high.rolling(n, min_periods=n).max()
        lo = low.rolling(n, min_periods=n).min()
        rng = (hi - lo).replace(0.0, np.nan)
        feat[f"donchian_{n}"] = (close - lo) / rng

    # 8) 成交量
    if vol is not None:
        vol_sma20 = vol.rolling(20, min_periods=20).mean()
        feat["volume_ratio_20"] = vol / vol_sma20.replace(0.0, np.nan)
        vol_std20 = vol.rolling(20, min_periods=20).std()
        feat["volume_z_20"] = (vol - vol_sma20) / vol_std20.replace(0.0, np.nan)

    # 9) 关联对特征（横截面）：其它币种的历史收益与相对强弱
    if corr_data:
        for sym, cdf in corr_data.items():
            if not isinstance(cdf, pd.DataFrame) or cdf.empty or "close" not in cdf:
                continue
            cclose = cdf["close"].astype(float).reindex(df.index).ffill()
            tag = sym.split("/")[0].replace("-", "").upper()
            for n in lookbacks:
                feat[f"corr_{tag}_roc_{n}"] = cclose.pct_change(n)
            feat[f"corr_{tag}_ratio"] = cclose / close.replace(0.0, np.nan) - 1.0

    return feat


FEATURE_GROUPS: dict[str, list[str]] = {
    "momentum": ["roc_5", "roc_10", "roc_20", "roc_50", "rsi_7", "rsi_14", "macd_hist"],
    "volatility": ["vol_5", "vol_10", "vol_20", "atr_ratio", "bb_width"],
    "mean_reversion": ["bb_pctb", "close_sma_10", "close_sma_20", "close_sma_50", "ema_10_ratio", "ema_20_ratio", "ema_50_ratio"],
    "trend": ["macd_dif", "macd_dea", "donchian_20", "donchian_50", "roc_20", "roc_50"],
    "volume": ["volume_ratio_20", "volume_z_20"],
}
