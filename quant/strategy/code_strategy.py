"""代码策略：像 TradingView Pine Script 一样编写 Python 代码定义交易信号。

用户代码在一个受限命名空间中执行，可用的对象：
- df: K 线 DataFrame（open / high / low / close / volume）
- sma / ema / rsi / macd / bollinger / atr / donchian: 指标函数
- pd / np: pandas / numpy
- params: 参数字典（UI 传入）
- 必须定义 generate_signals(df, params) 返回信号序列（+1 做多 / -1 做空 / 0 空仓）

默认模板：
def generate_signals(df, params):
    fast = int(params.get("fast", 20))
    slow = int(params.get("slow", 50))
    ma_fast = sma(df["close"], fast)
    ma_slow = sma(df["close"], slow)
    return (ma_fast > ma_slow).astype(float)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.data.indicators import atr, bollinger, donchian, ema, macd, rsi, sma
from quant.strategy.base import Strategy

DEFAULT_CODE = '''def generate_signals(df, params):
    """双均线示例：快线上穿慢线做多。

    可用：df / sma / ema / rsi / macd / bollinger / atr / donchian / pd / np / params
    返回：+1 做多、-1 做空、0 空仓 的序列（长度与 df 相同）
    """
    fast = int(params.get("fast", 20))
    slow = int(params.get("slow", 50))
    ma_fast = sma(df["close"], fast)
    ma_slow = sma(df["close"], slow)
    signal = (ma_fast > ma_slow).astype(float)
    return signal
'''

CODE_DOC = """## 代码策略说明（TradingView 风格）

### 可用对象
| 对象 | 说明 |
| --- | --- |
| `df` | K 线 DataFrame，列：open / high / low / close / volume |
| `sma(s, n)` | 简单移动平均 |
| `ema(s, n)` | 指数移动平均 |
| `rsi(s, n)` | RSI 指标 |
| `macd(s, fast, slow, signal)` | 返回 (DIF, DEA, 柱) |
| `bollinger(s, n, k)` | 返回 (中轨, 上轨, 下轨) |
| `atr(df, n)` | ATR 指标 |
| `donchian(df, n)` | 返回 (上轨, 下轨) |
| `pd` / `np` | pandas / numpy |
| `params` | 参数 dict（可在界面配置） |

### 编写规则
1. 必须定义 `generate_signals(df, params)` 函数；
2. 返回与 df 等长的信号序列：`1` 做多 / `-1` 做空 / `0` 空仓（支持 float 与 NaN 自动处理）；
3. 可直接用 `pd.Series` / `numpy` 编写复杂逻辑；
4. 代码在本地沙箱执行，仅供自己使用，请注意代码正确性。"""


class CodeStrategy(Strategy):
    """用户代码策略。"""

    name = "code"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.code = self.params.get("code") or DEFAULT_CODE
        self._fn = None
        self._error: str | None = None
        self._namespace: dict = {}
        self.compile_code()

    def compile_code(self) -> None:
        """编译用户代码并提取 generate_signals 函数。"""
        self._namespace = {
            "pd": pd,
            "np": np,
            "sma": sma,
            "ema": ema,
            "rsi": rsi,
            "macd": macd,
            "bollinger": bollinger,
            "atr": atr,
            "donchian": donchian,
            "__builtins__": __builtins__,
        }
        try:
            exec(compile(self.code, "<code_strategy>", "exec"), self._namespace)
        except Exception as exc:  # noqa: BLE001
            self._error = "代码编译失败: " + str(exc)
            self._fn = None
            return
        fn = self._namespace.get("generate_signals")
        if not callable(fn):
            self._error = "代码中未找到 generate_signals(df, params) 函数"
            self._fn = None
            return
        self._fn = fn
        self._error = None

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if self._fn is None:
            raise ValueError(self._error or "代码未编译")
        try:
            result = self._fn(df, self.params)
        except TypeError:
            # 兼容只接收 df 的写法
            result = self._fn(df)
        if not isinstance(result, pd.Series):
            raise ValueError("generate_signals 必须返回 pandas Series（当前类型: " + type(result).__name__ + "）")
        if len(result) != len(df):
            raise ValueError("信号长度 (" + str(len(result)) + ") 与 K 线数量 (" + str(len(df)) + ") 不一致")
        signal = result.reindex(df.index)
        signal = pd.to_numeric(signal, errors="coerce").fillna(0.0)
        signal = signal.clip(-1.0, 1.0)
        return signal.astype(float)
