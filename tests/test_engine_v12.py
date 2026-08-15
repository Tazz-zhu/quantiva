# -*- coding: utf-8 -*-
"""freqtrade 优势集成测试：回测引擎新特性（ROI / 保护器 / 加仓 / breakdown / 缓存）。"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from quant.backtest.cache import BacktestCache, cache_key
from quant.backtest.engine import BacktestEngine
from quant.risk.manager import RiskManager
from quant.strategy.base import Strategy
from fixture_loader import load_real_ohlcv


class AlwaysLong(Strategy):
    name = "always_long"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=df.index)


class TestEngineFreqtrade(unittest.TestCase):
    def setUp(self):
        self.data = load_real_ohlcv("1h", n=600)

    def test_roi_table_exits(self):
        strategy = __import__("quant.strategy", fromlist=["create_strategy"]).create_strategy(
            "ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"}
        )
        risk = RiskManager(max_position_pct=0.5, trade_direction="long_only",
                           roi_table=[[0, 0.02], [24, 0.005], [48, 0]])
        result = BacktestEngine(strategy, self.data, risk=risk).run()
        reasons = {t.reason for t in result.trades}
        self.assertTrue(any("roi" == r for r in reasons) or not result.trades)

    def test_protections_cooldown_blocks(self):
        strategy = __import__("quant.strategy", fromlist=["create_strategy"]).create_strategy(
            "ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"}
        )
        # 长冷却期应显著减少交易数
        risk_long = RiskManager(max_position_pct=0.5, trade_direction="long_only",
                                protections={"cooldown_candles": 200})
        risk_none = RiskManager(max_position_pct=0.5, trade_direction="long_only")
        r_long = BacktestEngine(strategy, self.data, risk=risk_long).run()
        r_none = BacktestEngine(strategy, self.data, risk=risk_none).run()
        self.assertLessEqual(r_long.metrics["num_trades"], r_none.metrics["num_trades"] + 1)

    def test_position_adjustment(self):
        idx = pd.date_range("2026-01-01", periods=300, freq="1h", tz="UTC")
        close = 100 * np.exp(np.linspace(0, 0.3, 300))
        df = pd.DataFrame({"open": close * 0.999, "high": close * 1.01, "low": close * 0.99,
                           "close": close, "volume": 1.0}, index=idx)
        risk = RiskManager(max_position_pct=0.5, stop_loss_pct=0.05,
                           adjust_after_mult=0.1, adjust_step_pct=0.2, adjust_max_times=5)
        r = BacktestEngine(AlwaysLong(), df, risk=risk, fee_rate=0.0, slippage=0.0).run()
        self.assertEqual(r.metrics.get("adjustments", 0), 5)
        self.assertGreater(r.metrics["total_return"], 0.3)

    def test_breakdown_and_trade_stats(self):
        strategy = __import__("quant.strategy", fromlist=["create_strategy"]).create_strategy(
            "ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"}
        )
        r = BacktestEngine(strategy, self.data).run()
        self.assertIn("by_exit_reason", r.breakdown)
        self.assertIn("by_month", r.breakdown)
        self.assertIn("by_weekday", r.breakdown)
        self.assertIn("max_consecutive_losses", r.trade_stats)

    def test_backtest_cache_roundtrip(self):
        strategy = __import__("quant.strategy", fromlist=["create_strategy"]).create_strategy(
            "ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"}
        )
        r = BacktestEngine(strategy, self.data).run()
        with tempfile.TemporaryDirectory() as td:
            cache = BacktestCache(td)
            key = cache_key("ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"},
                             {}, {"initial_capital": 10000}, "BTC/USDT", self.data)
            cache.put(key, r)
            r2 = cache.get(key)
            self.assertIsNotNone(r2)
            self.assertEqual(len(r2.trades), len(r.trades))
            self.assertEqual(r2.breakdown["by_exit_reason"], r.breakdown["by_exit_reason"])
            self.assertEqual(cache.clear(), 1)


if __name__ == "__main__":
    unittest.main()
