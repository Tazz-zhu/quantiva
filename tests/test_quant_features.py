# -*- coding: utf-8 -*-
"""量化优化回归测试：Sortino/下行偏差、风险预算仓位、同 bar 重入、强平、holdout、R 倍数、月度一致性、波动率突增。"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from quant.backtest.engine import BacktestEngine
from fixture_loader import load_real_ohlcv
from quant.data.storage import SQLiteStorage
from quant.evolution.optimizer import Optimizer
from quant.monitor.service import MarketMonitor
from quant.report.analysis import analyze
from quant.risk.manager import RiskManager
from quant.strategy.base import Strategy
from quant.strategy import create_strategy


class AlwaysLong(Strategy):
    name = "always"

    def __init__(self, params: dict | None = None):
        super().__init__(params)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=df.index)


def fixture_df(n=300, start=100.0, seed=42):
    # 使用交易所真实 K 线 fixture（OKX BTC/USDT 1h）
    return load_real_ohlcv("1h", n=n)


class TestQuantFeatures(unittest.TestCase):
    def test_metrics_quant_extended(self):
        df = fixture_df()
        engine = BacktestEngine(
            strategy=create_strategy("ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"}),
            data=df, initial_capital=10000, fee_rate=0.001, slippage=0.0005,
            risk=RiskManager(max_position_pct=0.5, atr_stop_mult=2.0),
        )
        m = engine.run().metrics
        for key in ("downside_dev", "var95", "cvar95", "skew", "kurtosis", "ulcer",
                    "underwater_time_pct", "max_run_up", "avg_win_loss_ratio", "tail_ratio",
                    "best_day", "worst_day", "alpha_annual", "beta", "excess_return",
                    "avg_risk", "avg_r", "expectancy_r", "r_positive_pct"):
            self.assertIn(key, m, key)
        self.assertGreaterEqual(m["downside_dev"], 0.0)
        self.assertLessEqual(m["var95"], 0.0)
        self.assertLessEqual(m["cvar95"], m["var95"] + 1e-12)
        self.assertIsNotNone(m["beta"])
        self.assertIsNotNone(m["alpha_annual"])

    def test_risk_budget_sizing(self):
        risk = RiskManager(risk_per_trade_pct=0.01, max_position_pct=1.0)
        q_narrow = risk.risk_position_size(10000, 100, stop_distance_pct=0.01)
        q_wide = risk.risk_position_size(10000, 100, stop_distance_pct=0.2)
        self.assertGreater(q_narrow, q_wide)
        # 风险预算应把单笔风险控制在 1% 权益以内
        self.assertAlmostEqual(q_narrow * 100 * 0.01, 100.0, delta=0.01)
        # 上限封顶
        capped = risk.risk_position_size(10000, 100, stop_distance_pct=0.001)
        self.assertLessEqual(capped, risk.position_size(10000, 100) + 1e-9)

    def test_same_bar_reentry_blocked(self):
        # 构造：60 根横盘（100），第 61 根暴跌触发止损，之后维持低位
        n = 80
        idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("1h"), periods=n, freq="1h")
        close = pd.Series(100.0, index=idx)
        close.iloc[60] = 70.0
        close.iloc[61:] = 70.0
        df = pd.DataFrame({
            "open": close.shift(1).fillna(100.0),
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        }, index=idx)
        df.loc[df.index[60], "low"] = 60.0
        df.loc[df.index[60], "high"] = 101.0
        base = dict(strategy=AlwaysLong(), data=df, initial_capital=10000, fee_rate=0.001, slippage=0.0)
        r_no = BacktestEngine(**base, risk=RiskManager(stop_loss_pct=0.02, allow_reentry_same_bar=False)).run()
        r_yes = BacktestEngine(**base, risk=RiskManager(stop_loss_pct=0.02, allow_reentry_same_bar=True)).run()
        crash_ts = df.index[60]
        entries_no = [t for t in r_no.trades if t.entry_time == crash_ts]
        entries_yes = [t for t in r_yes.trades if t.entry_time == crash_ts]
        self.assertEqual(len(entries_no), 0)
        self.assertGreaterEqual(len(entries_yes), 1)

    def test_margin_call_liquidation(self):
        # 高杠杆 + 价格下跌 -> 触发强平
        df = fixture_df(120, start=100.0, seed=3)
        # 制造暴跌（触及强平价但未极端跳空）
        df.loc[df.index[60]:, "close"] = 85.0
        df.loc[df.index[60]:, "open"] = 100.0
        df.loc[df.index[60]:, "low"] = 84.0
        df.loc[df.index[60]:, "high"] = 101.0
        engine = BacktestEngine(
            strategy=AlwaysLong(), data=df, initial_capital=10000, fee_rate=0.0, slippage=0.0,
            risk=RiskManager(max_position_pct=0.5, leverage=20, atr_stop_mult=0.0),
        )
        result = engine.run()
        reasons = [t.reason for t in result.trades]
        self.assertIn("margin_call", reasons)
        self.assertGreater(result.metrics["final_equity"], -1e-6)

    def test_optimizer_holdout_and_min_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ohlcv.db")
            storage = SQLiteStorage(db)
            storage.save_ohlcv("BTC/USDT", "1h", load_real_ohlcv("1h", n=400))
            storage.close()
            opt = Optimizer("config/config.yaml")
            res = opt.run(
                "ma_cross",
                {"fast": [10, 30], "slow": [30, 60]},
                {"source": "db", "symbol": "BTC/USDT", "timeframe": "1h", "days": 150, "seed": 42, "storage_db": db},
                risk_cfg={"max_position_pct": 0.5},
                target="sharpe", max_combos=4, workers=2, holdout_ratio=0.25, min_trades=2,
            )
            self.assertIn("oos_metrics", res)
            self.assertIn("in_sample_metrics", res)
            self.assertAlmostEqual(res["holdout_ratio"], 0.25)
            if res["oos_metrics"] is not None:
                self.assertIn("sharpe", res["oos_metrics"])

    def test_monthly_consistency_and_r(self):
        df = fixture_df(600)
        result = BacktestEngine(
            strategy=create_strategy("ma_cross", {"fast": 10, "slow": 30}),
            data=df, initial_capital=10000, fee_rate=0.001, slippage=0.0005,
            risk=RiskManager(atr_stop_mult=2.0),
        ).run()
        a = analyze(result, "1h")
        self.assertIn("monthly_consistency", a)
        mc = a["monthly_consistency"]
        self.assertIn("positive_months_pct", mc)
        self.assertIn("avg_r", a["trades"])
        self.assertIn("expectancy_r", a["trades"])

    def test_vol_spike_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = MarketMonitor({"exchange": {"id": "binance"}, "monitor": {}}, db_path=str(Path(tmp) / "monitor.db"))
            rng = np.random.default_rng(7)
            idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("1min"), periods=1500, freq="1min")
            close = pd.Series(100.0 + np.cumsum(rng.normal(0, 0.02, 1500)), index=idx)
            close.iloc[-60:] = close.iloc[-61] + np.cumsum(rng.normal(0, 0.12, 60))
            df = pd.DataFrame({
                "open": close.shift(1).fillna(close),
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1000.0,
            }, index=idx)
            mon._process_symbol("TEST/USDT", df)
            events = mon.get_events(limit=50, type="vol_spike")
            self.assertGreaterEqual(len(events), 1)
            mon.conn.close()



    def test_rolling_stability_in_analysis(self):
        df = fixture_df(600)
        result = BacktestEngine(
            strategy=create_strategy("ma_cross", {"fast": 10, "slow": 30}),
            data=df, initial_capital=10000, fee_rate=0.001, slippage=0.0005,
            risk=RiskManager(atr_stop_mult=2.0),
        ).run()
        a = analyze(result, "1h")
        rs = a["rolling_stability"]
        self.assertTrue(rs["available"])
        self.assertGreater(rs["window"], 0)
        self.assertIn("mean", rs["sharpe"])
        self.assertIn("series", rs["sharpe"])
        self.assertGreater(len(rs["sharpe"]["series"]), 0)
        self.assertIn("stability_score", rs)

    def test_paper_broker_exec_quality(self):
        from quant.execution.paper import PaperBroker
        b = PaperBroker(initial_balance=10000, fee_rate=0.0, slippage=0.001)
        b.market_order("BTC/USDT", "buy", 1.0, price=100.0)
        b.market_order("BTC/USDT", "sell", 1.0, price=110.0)
        try:
            b.market_order("BTC/USDT", "buy", 1e9, price=100.0)
        except ValueError:
            pass
        eq = b.exec_quality
        self.assertEqual(eq["orders"], 3)
        self.assertEqual(eq["fills"], 2)
        self.assertEqual(eq["rejects"], 1)
        # 模拟滑点：买入成交价 100.1 / 卖出 109.89，相对参考价各约 10bps
        self.assertGreater(eq["slippage_bps_sum"], 0)
        self.assertGreaterEqual(eq["latency_ms_sum"], 0)
        self.assertEqual(eq["fills"] / eq["orders"] * 100 < 100, True)

if __name__ == "__main__":
    unittest.main()