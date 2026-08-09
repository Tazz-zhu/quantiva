"""?????"""
from quant.strategy.base import Strategy
from quant.strategy.ma_cross import MACrossStrategy
from quant.strategy.rsi_reversion import RSIMeanReversionStrategy
from quant.strategy.bollinger import BollingerReversionStrategy
from quant.strategy.custom_rules import CustomRulesStrategy
from quant.strategy.code_strategy import CodeStrategy
from quant.strategy.turtle import TurtleStrategy
from quant.strategy.macd_cross import MACDCrossStrategy
from quant.strategy.momentum import MomentumBreakoutStrategy
from quant.strategy.grid import GridStrategy
from quant.strategy.triple_screen import TripleScreenStrategy

STRATEGIES = {
    cls.name: cls
    for cls in (
        MACrossStrategy,
        RSIMeanReversionStrategy,
        BollingerReversionStrategy,
        CustomRulesStrategy,
        CodeStrategy,
        TurtleStrategy,
        MACDCrossStrategy,
        MomentumBreakoutStrategy,
        GridStrategy,
        TripleScreenStrategy,
    )
}


def create_strategy(name: str, params: dict | None = None) -> Strategy:
    """??????????"""
    if name not in STRATEGIES:
        raise ValueError(f"????: {name}???: {sorted(STRATEGIES)}")
    return STRATEGIES[name](params)


__all__ = ["Strategy", "create_strategy", "STRATEGIES"]
