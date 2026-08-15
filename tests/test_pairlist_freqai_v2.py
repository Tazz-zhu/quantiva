# -*- coding: utf-8 -*-
"""pairlist 动态选币与 FreqAI 增强（关联特征/重训）测试。"""
import tempfile
import unittest

import numpy as np
import pandas as pd

from quant.freqai import FreqAIPipeline, build_features
from quant.freqai.retrainer import FreqAIRetrainer
from quant.pairlist.filters import age_filter, price_filter, static_pairlist, volume_pairlist
from fixture_loader import load_real_ohlcv


class TestPairlist(unittest.TestCase):
    def test_static(self):
        self.assertEqual(static_pairlist(["A/USDT", "B/USDT"]), ["A/USDT", "B/USDT"])
        self.assertIn("BTC/USDT", static_pairlist(None))

    def test_volume_ranking(self):
        tickers = {
            "ETH/USDT": {"quoteVolume": 500, "last": 3000},
            "BTC/USDT": {"quoteVolume": 1000, "last": 60000},
            "SOL/USDT": {"quoteVolume": 300, "last": 150},
            "X/USD": {"quoteVolume": 999, "last": 1},  # 非 USDT 报价剔除
        }
        pairs = volume_pairlist(tickers, number_assets=2, min_volume=100)
        self.assertEqual(pairs, ["BTC/USDT", "ETH/USDT"])

    def test_price_filter(self):
        tickers = {"A/USDT": {"last": 0.5}, "B/USDT": {"last": 50}, "C/USDT": {"last": 5000}}
        out = price_filter(["A/USDT", "B/USDT", "C/USDT"], tickers, price_min=1, price_max=1000)
        self.assertEqual(out, ["B/USDT"])

    def test_age_filter(self):
        idx = pd.date_range("2025-01-01", periods=30, freq="1d", tz="UTC")
        df_old = pd.DataFrame({"close": np.linspace(100, 110, 30)}, index=idx)
        df_new = pd.DataFrame({"close": np.linspace(100, 110, 10)}, index=idx[:10])
        loader = {"OLD/USDT": df_old, "NEW/USDT": df_new}
        out = age_filter(["OLD/USDT", "NEW/USDT"], lambda s: loader[s], min_days=20)
        self.assertEqual(out, ["OLD/USDT"])


class TestFreqAIEnhance(unittest.TestCase):
    def setUp(self):
        self.df = load_real_ohlcv("1h", n=600)
        idx = self.df.index
        r = np.random.default_rng(3)
        close2 = self.df["close"].values * (1 + 0.01 * np.cumsum(r.normal(0, 1, len(idx))))
        self.corr = pd.DataFrame(
            {"open": close2 * 0.999, "high": close2 * 1.01, "low": close2 * 0.99,
             "close": close2, "volume": 1.0}, index=idx
        )

    def test_corr_features(self):
        feat = build_features(self.df, corr_data={"ETH/USDT": self.corr})
        corr_cols = [c for c in feat.columns if c.startswith("corr_")]
        self.assertGreater(len(corr_cols), 0)
        self.assertIn("corr_ETH_ratio", corr_cols)

    def test_pipeline_with_corr(self):
        pipe = FreqAIPipeline(model_name="ridge", kind="regression", horizon=4)
        res = pipe.backtest(self.df, n_windows=2, min_train=150, corr_data={"ETH/USDT": self.corr})
        self.assertGreater(res["prediction_coverage"], 0.1)

    def test_retrainer(self):
        with tempfile.TemporaryDirectory() as td:
            pipe = FreqAIPipeline(model_name="ridge", kind="regression", horizon=4, model_dir=td)
            rt = FreqAIRetrainer(pipe, lambda: (self.df, {"ETH/USDT": self.corr}), name="live", keep_history=2)
            info = rt.train_now()
            self.assertEqual(rt.train_count, 1)
            self.assertIsNotNone(rt.last_train_at)
            models = [m["name"] for m in pipe.list_models()]
            self.assertIn("live", models)
            pred = pipe.predict_latest(self.df, name="live", corr_data={"ETH/USDT": self.corr})
            self.assertIn("prediction", pred)
            st = rt.status()
            self.assertFalse(st["running"])


if __name__ == "__main__":
    unittest.main()
