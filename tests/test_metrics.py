"""?????????"""
import unittest

import pandas as pd

from quant.analytics.metrics import compute_metrics, max_drawdown


class FakeTrade:
    def __init__(self, pnl, ret=0.01, fees=0.0):
        self.pnl = pnl
        self.return_pct = ret
        self.fees = fees
        self.entry_time = pd.Timestamp("2024-01-01")
        self.exit_time = pd.Timestamp("2024-01-02")


class TestMetrics(unittest.TestCase):
    def test_max_drawdown(self):
        equity = pd.Series([100.0, 120.0, 90.0, 110.0, 80.0, 130.0])
        dd, ts = max_drawdown(equity)
        self.assertAlmostEqual(dd, 80.0 / 120.0 - 1.0)
        self.assertEqual(ts, equity.index[4])

    def test_metrics_basic(self):
        equity = pd.Series([100.0, 101.0, 99.0, 102.0, 103.0])
        trades = [FakeTrade(10.0), FakeTrade(-4.0), FakeTrade(6.0)]
        m = compute_metrics(equity, trades, 100.0, periods_per_year=365)
        self.assertAlmostEqual(m["total_return"], 0.03)
        self.assertEqual(m["num_trades"], 3)
        self.assertAlmostEqual(m["win_rate"], 2 / 3)
        self.assertAlmostEqual(m["profit_factor"], 16.0 / 4.0)

    def test_profit_factor_infinite(self):
        trades = [FakeTrade(5.0)]
        m = compute_metrics(pd.Series([100.0, 105.0]), trades, 100.0)
        self.assertEqual(m["profit_factor"], float("inf"))


if __name__ == "__main__":
    unittest.main()
