"""??????????"""
import unittest

from quant.backtest.engine import BacktestEngine
from fixture_loader import load_real_ohlcv
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy
from quant.strategy.library import get_library

LIB_STRATEGIES = ["turtle", "ma_cross", "macd_cross", "momentum", "bollinger", "rsi_reversion", "grid", "triple_screen", "trend_flow"]


class TestClassicLibrary(unittest.TestCase):
    def setUp(self):
        self.data = load_real_ohlcv("4h", n=500)

    def test_library_metadata(self):
        names = {s["name"] for s in get_library()}
        self.assertTrue(LIB_STRATEGIES[0] in names)
        for s in get_library():
            self.assertTrue(s["school"])
            self.assertTrue(s["master"])
            self.assertTrue(s["desc"])

    def test_breakout_strategies_actually_trade(self):
        """turtle / grid ???????? bar ????????????????????"""
        for name in ("turtle", "grid"):
            with self.subTest(strategy=name):
                strategy = create_strategy(name, {})
                engine = BacktestEngine(
                    strategy, self.data, initial_capital=10000,
                    risk=RiskManager(max_position_pct=0.5),
                )
                result = engine.run()
                self.assertGreater(result.metrics["num_trades"], 0, f"{name} ?????")

    def test_all_library_strategies_run(self):
        for name in LIB_STRATEGIES:
            with self.subTest(strategy=name):
                strategy = create_strategy(name, {})
                engine = BacktestEngine(
                    strategy, self.data, initial_capital=10000,
                    risk=RiskManager(max_position_pct=0.5),
                )
                result = engine.run()
                self.assertGreaterEqual(result.metrics["num_trades"], 0)
                self.assertIn("total_return", result.metrics)


if __name__ == "__main__":
    unittest.main()
