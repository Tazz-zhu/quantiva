"""经典策略库：各交易流派的代表策略与核心理念。"""
from __future__ import annotations

STRATEGY_LIBRARY = [
    {
        "name": "turtle",
        "school": "趋势跟踪",
        "master": "Richard Dennis · 海龟交易法则",
        "desc": "唐奇安通道突破入场（20日高点），跌破10日低点离场；ATR 控制仓位，让利润奔跑、截断亏损。",
        "params": [
            {"k": "entry_period", "label": "入场突破周期", "type": "number", "def": 20},
            {"k": "exit_period", "label": "离场突破周期", "type": "number", "def": 10},
            {"k": "direction", "label": "交易方向", "type": "select", "def": "long_only", "options": [["long_only", "只做多"], ["long_short", "多空都做"]]},
        ],
    },
    {
        "name": "ma_cross",
        "school": "趋势跟踪",
        "master": "John Murphy · 技术分析",
        "desc": "经典双均线系统：快线上穿慢线金叉做多，下穿死叉离场/做空，趋势跟随的基石。",
        "params": [
            {"k": "fast", "label": "快线周期", "type": "number", "def": 20},
            {"k": "slow", "label": "慢线周期", "type": "number", "def": 50},
            {"k": "direction", "label": "交易方向", "type": "select", "def": "long_only", "options": [["long_only", "只做多"], ["long_short", "多空都做"]]},
        ],
    },
    {
        "name": "macd_cross",
        "school": "趋势/动量",
        "master": "Gerald Appel · MACD",
        "desc": "MACD 金叉（DIF 上穿 DEA）买入、死叉离场/做空，捕捉中期趋势与动量切换。",
        "params": [
            {"k": "fast", "label": "快线", "type": "number", "def": 12},
            {"k": "slow", "label": "慢线", "type": "number", "def": 26},
            {"k": "signal", "label": "信号线", "type": "number", "def": 9},
            {"k": "direction", "label": "交易方向", "type": "select", "def": "long_only", "options": [["long_only", "只做多"], ["long_short", "多空都做"]]},
        ],
    },
    {
        "name": "momentum",
        "school": "动量交易",
        "master": "Mark Minervini / Richard Driehaus",
        "desc": "价格创 50 日新高确认强势动量入场，跌破 20 日均线离场——强者恒强，只买最强。",
        "params": [
            {"k": "lookback", "label": "新高回看周期", "type": "number", "def": 50},
            {"k": "exit_ma", "label": "离场均线", "type": "number", "def": 20},
        ],
    },
    {
        "name": "bollinger",
        "school": "均值回归",
        "master": "John Bollinger · 布林带",
        "desc": "价格跌破下轨视为超卖买入，回归中轨卖出——赚取价格回归均值的收益。",
        "params": [
            {"k": "period", "label": "周期", "type": "number", "def": 20},
            {"k": "num_std", "label": "标准差倍数", "type": "number", "step": 0.1, "def": 2},
        ],
    },
    {
        "name": "rsi_reversion",
        "school": "均值回归",
        "master": "J. Welles Wilder · RSI",
        "desc": "RSI 跌破 30 超卖买入，升破 70 超买卖出——经典摆动指标均值回归。",
        "params": [
            {"k": "period", "label": "RSI 周期", "type": "number", "def": 14},
            {"k": "oversold", "label": "超卖阈值", "type": "number", "def": 30},
            {"k": "overbought", "label": "超买阈值", "type": "number", "def": 70},
        ],
    },
    {
        "name": "grid",
        "school": "震荡网格",
        "master": "区间交易 · Swing Trading",
        "desc": "价格触及 N 日低点（区间下沿）买入，触及 N 日高点（区间上沿）卖出——震荡市低吸高抛。",
        "params": [
            {"k": "period", "label": "区间周期", "type": "number", "def": 20},
        ],
    },
    {
        "name": "triple_screen",
        "school": "多重滤网",
        "master": "Alexander Elder · 三重滤网",
        "desc": "长期趋势（大周期均线）+ 中期回调（RSI2 超卖）+ 短期确认（站上短均线）三层过滤入场。",
        "params": [
            {"k": "fast_ma", "label": "趋势快线", "type": "number", "def": 50},
            {"k": "slow_ma", "label": "趋势慢线", "type": "number", "def": 200},
            {"k": "rsi_period", "label": "RSI 周期", "type": "number", "def": 2},
            {"k": "oversold", "label": "超卖阈值", "type": "number", "def": 30},
            {"k": "overbought", "label": "超买阈值", "type": "number", "def": 70},
        ],
    },
    {
        "name": "code",
        "school": "代码策略",
        "master": "TradingView 风格 · Python",
        "desc": "像 Pine Script 一样直接编写 Python 代码定义交易信号，支持全部指标函数，一键回测与实盘使用。",
        "params": [],
    },
    {
        "name": "custom",
        "school": "自定义",
        "master": "用户自定义规则",
        "desc": "在「策略构建」页可视化组合任意指标条件，灵活搭建自己的交易系统。",
        "params": [],
    },
]

SCHOOL_ICONS = {
    "趋势跟踪": "📈", "动量交易": "🚀", "均值回归": "🔄",
    "震荡网格": "🔁", "多重滤网": "🧅", "代码策略": "🧑‍💻", "自定义": "🎛️",
}


def get_library() -> list[dict]:
    return STRATEGY_LIBRARY


def get_strategy_meta(name: str) -> dict | None:
    for s in STRATEGY_LIBRARY:
        if s["name"] == name:
            return s
    return None
