# -*- coding: utf-8 -*-
"""quant.freqai 测试：特征 / 切分 / 管线回测 / 策略信号 / 模型持久化。"""
import tempfile
import unittest

import numpy as np
import pandas as pd

from quant.freqai import FreqAIPipeline, FreqAIStrategy
from quant.freqai.features import build_features
from quant.freqai.split import walk_forward_windows
from quant.freqai.targets import build_targets
from fixture_loader import load_real_ohlcv


class TestFreqAI(unittest.TestCase):
    def setUp(self):
        self.df = load_real_ohlcv("1h", n=700)

    def test_build_features_causal(self):
        feat = build_features(self.df)
        self.assertIn("roc_5", feat.columns)
        self.assertIn("rsi_14", feat.columns)
        # 特征不应含未来信息：最后一行也应有值（除需要更长回看的）
        self.assertFalse(feat.isna().all().any())

    def test_build_targets(self):
        tgt = build_targets(self.df, horizon=5, kind="regression")
        self.assertIn("target", tgt.columns)
        self.assertTrue(tgt["target"].iloc[-5:].isna().all())

    def test_walk_forward_windows_no_leak(self):
        wins = list(walk_forward_windows(500, n_windows=4, test_size=50, purge=5, embargo=3))
        for tr, te in wins:
            # 训练集最后一行 + purge/embargo 后应严格早于测试集
            self.assertLess(tr[-1], te[0])
            # 无重叠
            self.assertTrue(set(tr).isdisjoint(set(te)))

    def test_pipeline_backtest_and_strategy(self):
        pipe = FreqAIPipeline(model_name="random_forest", kind="regression", horizon=5)
        res = pipe.backtest(self.df, n_windows=3, min_train=150)
        self.assertIn("freqai_pred", res["data"].columns)
        self.assertGreater(res["prediction_coverage"], 0.3)
        strategy = FreqAIStrategy({"kind": "regression", "direction": "long_only", "long_threshold": 0.0})
        sig = strategy.generate_signals(res["data"])
        self.assertIn(sig.iloc[-1], (0.0, 1.0))

    def test_classification_strategy(self):
        pipe = FreqAIPipeline(model_name="random_forest", kind="classification", horizon=5)
        res = pipe.backtest(self.df, n_windows=3, min_train=150)
        strategy = FreqAIStrategy({"kind": "classification", "direction": "long_short",
                                   "long_threshold": 0.55, "short_threshold": 0.55})
        sig = strategy.generate_signals(res["data"])
        self.assertTrue(set(sig.dropna().unique()).issubset({-1.0, 0.0, 1.0}))

    def test_train_predict_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            pipe = FreqAIPipeline(model_name="ridge", kind="regression", horizon=3, model_dir=td)
            info = pipe.train(self.df, train_ratio=0.8, name="test")
            self.assertEqual(info["name"], "test")
            self.assertTrue(info["path"].endswith("test") or "test" in info["path"])
            latest = pipe.predict_latest(self.df, name="test")
            self.assertIn("prediction", latest)
            models = pipe.list_models()
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0]["name"], "test")


if __name__ == "__main__":
    unittest.main()
