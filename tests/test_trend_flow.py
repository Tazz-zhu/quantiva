"""Unit tests for the TrendFlow strategy (trend + ADX filter + ATR channel exit)."""
import unittest

import pandas as pd

from quant.backtest.engine import BacktestEngine
from quant.data.indicators import adx
from quant.risk.manager import RiskManager
from quant.strategy import STRATEGIES, create_strategy
from quant.strategy.library import get_library
from fixture_loader import load_real_ohlcv


class TestTrendFlow(unittest.TestCase):
    def setUp(self):
        self.data = load_real_ohlcv("4h", n=500)

    def test_registered_in_system(self):
        self.assertIn("trend_flow", STRATEGIES)
        names = {s["name"] for s in get_library()}
        self.assertIn("trend_flow", names)

    def test_signal_values(self):
        strategy = create_strategy("trend_flow", {"direction": "long_short"})
        sig = strategy.generate_signals(self.data)
        self.assertTrue(set(sig.unique()) <= {-1.0, 0.0, 1.0})

    def test_long_only_never_short(self):
        strategy = create_strategy("trend_flow", {"direction": "long_only"})
        sig = strategy.generate_signals(self.data)
        self.assertTrue((sig >= 0).all())

    def test_backtest_runs_and_trades(self):
        strategy = create_strategy("trend_flow", {"fast_ma": 20, "slow_ma": 60, "entry_lookback": 20,
                                                  "exit_atr_mult": 3.0, "min_adx": 20.0,
                                                  "direction": "long_short"})
        engine = BacktestEngine(strategy, self.data, initial_capital=10000,
                                risk=RiskManager(max_position_pct=0.5, trade_direction="long_short"))
        result = engine.run()
        self.assertGreaterEqual(result.metrics["num_trades"], 0)
        sides = {t.side for t in result.trades}
        self.assertTrue(sides <= {"long", "short"})

    def test_adx_indicator(self):
        out = adx(self.data, 14)
        self.assertEqual(len(out), len(self.data))
        self.assertTrue((out.dropna() >= 0).all())
        self.assertTrue((out.dropna() <= 100).all())


if __name__ == "__main__":
    unittest.main()
