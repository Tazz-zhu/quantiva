"""自定义规则策略：用多种指标 + 逻辑条件组合成开仓/平仓信号。

规则 JSON 示例：
{
  "entry": {
    "logic": "all",                          // all | any
    "conditions": [
      {"indicator": "sma", "params": {"period": 20}, "op": ">",
       "compare": "indicator", "compare_indicator": "sma", "compare_params": {"period": 50}},
      {"indicator": "rsi", "params": {"period": 14}, "op": "<",
       "compare": "number", "value": 70}
    ]
  },
  "exit": {"logic": "any", "conditions": [...]},   // 可选
  "direction": "long_only"                          // long_only | long_short
}
"""
from __future__ import annotations

import pandas as pd

from quant.data.indicators import atr, bollinger, ema, macd, rsi, sma
from quant.strategy.base import Strategy

OPS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
       "<=": lambda a, b: a <= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}

# 指标计算函数：输入 df，输出 Series
INDICATORS = {
    "close": lambda df, p=None: df["close"],
    "open": lambda df, p=None: df["open"],
    "high": lambda df, p=None: df["high"],
    "low": lambda df, p=None: df["low"],
    "volume": lambda df, p=None: df["volume"],
    "sma": lambda df, p: sma(df["close"], int(p.get("period", 20))),
    "ema": lambda df, p: ema(df["close"], int(p.get("period", 20))),
    "rsi": lambda df, p: rsi(df["close"], int(p.get("period", 14))),
    "macd_dif": lambda df, p: macd(df["close"], int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9)))[0],
    "macd_dea": lambda df, p: macd(df["close"], int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9)))[1],
    "macd_hist": lambda df, p: macd(df["close"], int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9)))[2],
    "boll_upper": lambda df, p: bollinger(df["close"], int(p.get("period", 20)), float(p.get("num_std", 2.0)))[1],
    "boll_mid": lambda df, p: bollinger(df["close"], int(p.get("period", 20)), float(p.get("num_std", 2.0)))[0],
    "boll_lower": lambda df, p: bollinger(df["close"], int(p.get("period", 20)), float(p.get("num_std", 2.0)))[2],
    "atr": lambda df, p: atr(df, int(p.get("period", 14))),
}

INDICATOR_LABELS = {
    "close": "收盘价", "open": "开盘价", "high": "最高价", "low": "最低价", "volume": "成交量",
    "sma": "SMA 均线", "ema": "EMA 均线", "rsi": "RSI 强弱", "macd_dif": "MACD DIF",
    "macd_dea": "MACD DEA", "macd_hist": "MACD 柱", "boll_upper": "布林上轨",
    "boll_mid": "布林中轨", "boll_lower": "布林下轨", "atr": "ATR 波幅",
}

DEFAULT_PARAMS = {
    "sma": {"period": 20}, "ema": {"period": 20}, "rsi": {"period": 14},
    "macd_dif": {}, "macd_dea": {}, "macd_hist": {},
    "boll_upper": {"period": 20}, "boll_mid": {"period": 20}, "boll_lower": {"period": 20},
    "atr": {"period": 14}, "close": {}, "open": {}, "high": {}, "low": {}, "volume": {},
}


def _series(indicator: str, params: dict | None, df: pd.DataFrame) -> pd.Series:
    if indicator not in INDICATORS:
        raise ValueError("不支持的指标: " + indicator)
    merged = dict(DEFAULT_PARAMS.get(indicator, {}))
    if params:
        merged.update(params)
    return INDICATORS[indicator](df, merged)


def _evaluate(cond: dict, df: pd.DataFrame) -> pd.Series:
    """计算单个条件的布尔 Series。"""
    ind = cond["indicator"]
    params = cond.get("params") or {}
    op = cond.get("op", ">")
    if op not in OPS:
        raise ValueError("不支持的运算符: " + op)
    left = _series(ind, params, df)
    compare = cond.get("compare", "number")
    if compare == "indicator":
        right = _series(cond["compare_indicator"], cond.get("compare_params") or {}, df)
    else:
        right = float(cond.get("value", 0))
    return OPS[op](left, right)


class CustomRulesStrategy(Strategy):
    """多指标组合规则策略。"""

    name = "custom"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.rules = params.get("rules") or {}
        self.direction = self.params.get("direction", "long_only")

    def validate(self) -> None:
        rules = self.rules
        if not isinstance(rules, dict) or "entry" not in rules:
            raise ValueError("自定义策略需要 entry 开仓规则")
        for key in ("entry", "exit"):
            block = rules.get(key)
            if not block:
                continue
            if "conditions" not in block or not isinstance(block["conditions"], list):
                raise ValueError(key + " 规则缺少 conditions 列表")
            for cond in block["conditions"]:
                if "indicator" not in cond:
                    raise ValueError("条件缺少 indicator")

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        self.validate()
        rules = self.rules
        entry = rules.get("entry", {})
        exit_ = rules.get("exit") or {}

        def block_holds(block: dict) -> pd.Series:
            if not block or not block.get("conditions"):
                return pd.Series(False, index=df.index)
            conds = [pd.Series(_evaluate(c, df), index=df.index) for c in block["conditions"]]
            logic = block.get("logic", "all")
            result = conds[0]
            for c in conds[1:]:
                if logic == "any":
                    result = result | c
                else:
                    result = result & c
            return result.fillna(False)

        entry_sig = block_holds(entry)
        exit_sig = block_holds(exit_)

        signal = pd.Series(0.0, index=df.index, dtype=float)
        position = 0
        for i in range(len(df)):
            e = bool(entry_sig.iloc[i])
            x = bool(exit_sig.iloc[i])
            if position == 0:
                if e:
                    position = 1
                elif self.direction == "long_short" and x:
                    position = -1
            elif position == 1:
                if x:
                    position = -1 if self.direction == "long_short" else 0
            elif position == -1:
                if e:
                    position = 1
                elif x:
                    position = 0
            signal.iloc[i] = position
        return signal
