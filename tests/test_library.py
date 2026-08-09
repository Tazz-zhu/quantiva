"""??????????"""
import unittest

from quant.backtest.engine import BacktestEngine
from quant.data.fetcher import generate_synthetic_ohlcv
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy
from quant.strategy.library import get_library

LIB_STRATEGIES = ["turtle", "ma_cross", "macd_cross", "momentum", "bollinger", "rsi_reversion", "grid", "triple_screen"]


class TestClassicLibrary(unittest.TestCase):
    def setUp(self):
        self.data = generate_synthetic_ohlcv(timeframe="4h", days=300, seed=11)

    def test_library_metadata(self):
        names = {s["name"] for s in get_library()}
        self.assertTrue(LIB_STRATEGIES[0] in names)
        for s in get_library():
            self.assertTrue(s["school"])
            self.assertTrue(s["master"])
            self.assertTrue(s["desc"])

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
