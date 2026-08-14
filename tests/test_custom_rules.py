"""????????????"""
import unittest

from quant.backtest.engine import BacktestEngine
from fixture_loader import load_real_ohlcv
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy

RULES = {
    "entry": {
        "logic": "all",
        "conditions": [
            {"indicator": "sma", "params": {"period": 10}, "op": ">",
             "compare": "indicator", "compare_indicator": "sma", "compare_params": {"period": 30}},
            {"indicator": "rsi", "params": {"period": 14}, "op": "<",
             "compare": "number", "value": 70},
        ],
    },
    "exit": {
        "logic": "any",
        "conditions": [
            {"indicator": "sma", "params": {"period": 10}, "op": "<",
             "compare": "indicator", "compare_indicator": "sma", "compare_params": {"period": 30}},
            {"indicator": "rsi", "params": {"period": 14}, "op": ">",
             "compare": "number", "value": 75},
        ],
    },
    "direction": "long_only",
}


class TestCustomRules(unittest.TestCase):
    def setUp(self):
        self.data = load_real_ohlcv("4h", n=400)

    def test_custom_strategy_runs(self):
        strategy = create_strategy("custom", {"rules": RULES, "direction": "long_only"})
        engine = BacktestEngine(strategy, self.data, initial_capital=10000,
                                risk=RiskManager(max_position_pct=0.5))
        result = engine.run()
        self.assertGreaterEqual(result.metrics["num_trades"], 0)
        self.assertTrue((result.positions >= 0).all())

    def test_custom_invalid_rules(self):
        strategy = create_strategy("custom", {"rules": {"exit": {"conditions": []}}})
        with self.assertRaises(ValueError):
            strategy.generate_signals(self.data)

    def test_custom_long_short(self):
        rules = dict(RULES)
        rules["direction"] = "long_short"
        strategy = create_strategy("custom", {"rules": rules})
        engine = BacktestEngine(strategy, self.data,
                                risk=RiskManager(max_position_pct=0.5, trade_direction="long_short"))
        result = engine.run()
        sides = {t.side for t in result.trades}
        self.assertTrue(sides <= {"long", "short"})
        self.assertGreaterEqual(result.metrics["num_trades"], 0)


if __name__ == "__main__":
    unittest.main()
