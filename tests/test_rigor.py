# -*- coding: utf-8 -*-
"""quant.rigor 抗过拟合工具测试：损失函数 / 过滤器 / 显著性 / 前视 / 递归 / 滚动样本外。"""
import os
import tempfile
import unittest
import unittest.mock as mock

import numpy as np
import pandas as pd

from quant.backtest.engine import BacktestEngine
from quant.rigor.filters import EpochFilterOptions, filter_epochs
from quant.rigor.lookahead import analyze_lookahead
from quant.rigor.losses import LOSS_FUNCTIONS, compute_loss
from quant.rigor.recursive import analyze_recursive
from quant.rigor.significance import (
    bootstrap_p_value,
    deflated_sharpe,
    parameter_stability,
    permutation_test,
    strategy_verdict,
)
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy
from quant.strategy.base import Strategy
from fixture_loader import load_real_ohlcv


class AlwaysLong(Strategy):
    name = "always_long"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=df.index)


class NoTrade(Strategy):
    name = "no_trade"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(0.0, index=df.index)


class BiasedStrategy(Strategy):
    """故意使用未来数据的策略（shift(-1)）用于前视检测。"""

    name = "biased"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fut = close.shift(-1)  # 未来数据
        sig = (fut > close).astype(float)
        return sig.reindex(df.index).fillna(0.0)


class TestRigor(unittest.TestCase):
    def setUp(self):
        self.data = load_real_ohlcv("1h", n=600)

    def _result(self, name="ma_cross", params=None):
        strategy = create_strategy(name, params or {"fast": 10, "slow": 30, "direction": "long_only"})
        return BacktestEngine(strategy, self.data, risk=RiskManager(max_position_pct=0.5)).run()

    def test_loss_functions_work(self):
        r = self._result()
        for name in LOSS_FUNCTIONS:
            loss = compute_loss(name, r)
            self.assertIsInstance(loss, float)

    def test_loss_lower_better(self):
        idx = pd.date_range("2026-01-01", periods=300, freq="1h", tz="UTC")
        close = 100 * np.exp(np.linspace(0, 0.2, 300))
        up = pd.DataFrame({"open": close * 0.999, "high": close * 1.01, "low": close * 0.99,
                           "close": close, "volume": 1.0}, index=idx)
        good = BacktestEngine(AlwaysLong(), up, risk=RiskManager(max_position_pct=0.5)).run()
        bad = BacktestEngine(NoTrade(), up).run()
        self.assertLess(compute_loss("total_profit", good), compute_loss("total_profit", bad))

    def test_filter_epochs(self):
        epochs = [
            {"params": {"a": 1}, "metrics": {"num_trades": 3, "total_return": 0.01, "sharpe": 0.5,
                                             "max_drawdown": -0.1, "profit_factor": 1.2, "win_rate": 0.5}, "loss": -0.5},
            {"params": {"a": 2}, "metrics": {"num_trades": 20, "total_return": -0.02, "sharpe": -0.3,
                                             "max_drawdown": -0.3, "profit_factor": 0.6, "win_rate": 0.3}, "loss": 0.3},
        ]
        kept, stats = filter_epochs(
            epochs,
            EpochFilterOptions(filter_min_trades=10, filter_min_sharpe=0.0, only_profitable=True),
        )
        self.assertEqual(len(kept), 0)
        self.assertEqual(stats["total"], 2)

    def test_significance_functions(self):
        rng = np.random.default_rng(7)
        rets = rng.normal(0.0005, 0.01, 400)
        bs = bootstrap_p_value(rets, n_boot=150)
        self.assertIn("p_value", bs)
        dsr = deflated_sharpe(rets, n_trials=20)
        self.assertIn("deflated_sharpe", dsr)
        perm = permutation_test(rets, n_perm=100)
        self.assertIn("p_value", perm)
        stab = parameter_stability([
            {"params": {"a": 1}, "metrics": {"x": 1}, "target_value": 1.0},
            {"params": {"a": 1}, "metrics": {"x": 1}, "target_value": 0.99},
            {"params": {"a": 2}, "metrics": {"x": 1}, "target_value": 0.5},
        ], top_k=3)
        self.assertIn("verdict", stab)
        v = strategy_verdict({"sharpe": 1.0}, {"total_return": 0.05, "sharpe": 0.8},
                             significance=bs, stability=stab)
        self.assertIn("passed", v)

    def test_lookahead_detects_biased_strategy(self):
        r = analyze_lookahead(BiasedStrategy(), self.data, max_checks=15)
        self.assertTrue(r["has_bias"])
        self.assertGreater(r["biased_checks"], 0)

    def test_lookahead_clean_strategy(self):
        strategy = create_strategy("ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"})
        r = analyze_lookahead(strategy, self.data, max_checks=15)
        self.assertFalse(r["has_bias"])

    def test_recursive_analysis_runs(self):
        strategy = create_strategy("ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"})
        r = analyze_recursive(strategy, self.data, warmup=100, max_checks=10)
        self.assertIn("verdict", r)
        self.assertIn("drift_rate", r)

    def test_optimizer_supports_loss_target(self):
        import os
        import tempfile
        from quant.evolution.optimizer import Optimizer

        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, "config.yaml")
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write("backtest:\n  initial_capital: 10000\n  fee_rate: 0.001\n  slippage: 0.0005\n")
            opt = Optimizer(cfg_path)
            opt._load_data = lambda data_cfg: load_real_ohlcv("1h", n=500)
            r = opt.run(
                "ma_cross", {"fast": [5, 10], "slow": [20, 30]},
                {"symbol": "BTC/USDT"}, risk_cfg={"max_position_pct": 0.5},
                target="multi_metric", max_combos=10, workers=2, min_trades=3,
            )
            self.assertIn("best", r)
            self.assertIsNotNone(r["best"])
            with self.assertRaises(ValueError):
                opt.run("ma_cross", {"fast": [5]}, {}, target="not_a_loss")

    def test_walkforward_runs(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, "config.yaml")
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write("backtest:\n  initial_capital: 10000\n  fee_rate: 0.001\n  slippage: 0.0005\n"
                        "risk:\n  max_position_pct: 0.5\n")
            with mock.patch("quant.rigor.walkforward.load_ohlcv_for_analysis", return_value=self.data):
                from quant.rigor.walkforward import run_walkforward
                result = run_walkforward(
                    cfg_path,
                    strategy_name="ma_cross",
                    param_ranges={"fast": [5, 10], "slow": [20, 30]},
                    data_cfg={"symbol": "BTC/USDT"},
                    loss="sharpe",
                    n_splits=3,
                    min_trades=2,
                    max_combos=10,
                    workers=2,
                )
            self.assertIn("folds", result)
            self.assertIn("oos_metrics_combined", result)
            self.assertIn("verdict", result)
            self.assertGreaterEqual(len(result["folds"]), 1)


if __name__ == "__main__":
    unittest.main()
