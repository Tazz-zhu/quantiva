"""?????????"""
import unittest

import numpy as np
import pandas as pd

from quant.data.indicators import atr, bollinger, ema, macd, rsi, sma


class TestIndicators(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        close = pd.Series(100.0 + np.cumsum(rng.normal(0, 1, 300)))
        self.df = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": np.abs(rng.normal(100, 10, 300)),
            }
        )

    def test_sma(self):
        s = sma(self.df["close"], 5)
        self.assertTrue(s.iloc[:4].isna().all())
        self.assertAlmostEqual(s.iloc[4], self.df["close"].iloc[:5].mean())

    def test_ema(self):
        s = ema(self.df["close"], 10)
        self.assertFalse(s.isna().all())
        valid = s.dropna()
        self.assertTrue((valid > 0).all())

    def test_rsi_bounds(self):
        r = rsi(self.df["close"], 14).dropna()
        self.assertTrue((r >= 0).all())
        self.assertTrue((r <= 100).all())

    def test_rsi_uptrend(self):
        up = pd.Series(np.arange(1.0, 50.0))
        self.assertGreater(rsi(up, 14).iloc[-1], 90)

    def test_bollinger_order(self):
        mid, upper, lower = bollinger(self.df["close"], 20, 2.0)
        valid = mid.dropna().index
        self.assertTrue((upper.loc[valid] >= mid.loc[valid]).all())
        self.assertTrue((lower.loc[valid] <= mid.loc[valid]).all())

    def test_macd_consistency(self):
        dif, dea, hist = macd(self.df["close"])
        self.assertEqual(len(dif), len(self.df))
        valid = hist.dropna().index
        self.assertTrue((hist.loc[valid] == (dif - dea).loc[valid]).all())

    def test_atr_positive(self):
        a = atr(self.df, 14).dropna()
        self.assertTrue((a > 0).all())


if __name__ == "__main__":
    unittest.main()
