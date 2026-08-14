# -*- coding: utf-8 -*-
"""v1.1 新功能回归测试：资金费率、Token 吊销、监控事件筛选、分页抓取参数校验。"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from quant.backtest.engine import BacktestEngine
from fixture_loader import load_real_ohlcv
from quant.data.fetcher import ExchangeDataFetcher, TIMEFRAME_NANOS
from quant.data.storage import SQLiteStorage
from quant.monitor.service import MarketMonitor
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy
from quant.web.auth import AuthManager
from quant.web.live_manager import LiveManager, load_live_session
from quant.web.state import BacktestManager


class FakeExchange:
    """模拟交易所：单页最多返回 100 根，用于验证分页抓取。"""

    def __init__(self):
        self.calls = 0

    def fetch_ohlcv(self, symbol, timeframe="1h", since=None, limit=None):
        self.calls += 1
        page = limit or 1000
        start = since if since is not None else 1_700_000_000_000
        freq = TIMEFRAME_NANOS.get(timeframe, 3_600_000_000_000) // 1_000_000
        out = []
        for i in range(page):
            ts = start + i * freq
            out.append([ts, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1000.0])
        return out


class TestV11Features(unittest.TestCase):
    def test_funding_rate_applied(self):
        df = generate_fixture_df()
        engine = BacktestEngine(
            strategy=create_strategy("ma_cross", {"fast": 5, "slow": 20, "direction": "long_only"}),
            data=df,
            initial_capital=10000,
            fee_rate=0.001,
            slippage=0.0005,
            risk=RiskManager(max_position_pct=0.9, leverage=1),
            symbol="BTC/USDT",
            funding_rate_8h=0.001,
        )
        result = engine.run()
        metrics = result.metrics
        self.assertIn("funding_paid", metrics)
        self.assertGreaterEqual(metrics["funding_paid"], 0.0)
        # funding 计入总费用
        self.assertGreaterEqual(metrics["total_fees"], metrics["funding_paid"])

    def test_no_funding_when_zero(self):
        df = generate_fixture_df()
        engine = BacktestEngine(
            strategy=create_strategy("ma_cross", {"fast": 5, "slow": 20, "direction": "long_only"}),
            data=df,
            risk=RiskManager(max_position_pct=0.9),
            funding_rate_8h=0.0,
        )
        result = engine.run()
        self.assertEqual(result.metrics["funding_paid"], 0.0)

    def test_paginated_fetch_covers_days(self):
        ex = FakeExchange()
        fetcher = ExchangeDataFetcher.__new__(ExchangeDataFetcher)
        fetcher.exchange = ex
        df = fetcher.fetch_ohlcv_paginated("BTC/USDT", "1h", days=100)
        # 100 days of 1h = 2400 bars, 至少需要 3 页
        self.assertGreaterEqual(len(df), 2400)
        self.assertGreaterEqual(ex.calls, 3)
        self.assertTrue(df.index.is_monotonic_increasing)
        self.assertEqual(df.index.duplicated().sum(), 0)

    def test_auth_revoke_all(self):
        auth = AuthManager()
        t1 = auth.issue("admin")
        t2 = auth.issue("admin")
        self.assertTrue(auth.validate(t1))
        auth.revoke_all()
        self.assertFalse(auth.validate(t1))
        self.assertFalse(auth.validate(t2))

    def test_monitor_events_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = MarketMonitor({"exchange": {"id": "binance"}, "monitor": {}}, db_path=str(Path(tmp) / "monitor.db"))
            mon._record_event("BTC/USDT", "volume_surge", "vol x3", 100.0, 0.01)
            mon._record_event("ETH/USDT", "price_surge_1h", "up 3%", 200.0, 0.03)
            mon._record_event("BTC/USDT", "price_drop_1h", "down 3%", 90.0, -0.03)
            all_events = mon.get_events(limit=50)
            vol_events = mon.get_events(limit=50, type="volume_surge")
            btc_events = mon.get_events(limit=50, symbol="BTC/USDT")
            self.assertEqual(len(all_events), 3)
            self.assertEqual(len(vol_events), 1)
            self.assertEqual(vol_events[0]["symbol"], "BTC/USDT")
            self.assertEqual(len(btc_events), 2)
            mon.conn.close()

    def test_compare_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ohlcv.db")
            storage = SQLiteStorage(db)
            storage.save_ohlcv("BTC/USDT", "1h", load_real_ohlcv("1h", n=400))
            storage.close()
            mgr = BacktestManager("config/config.yaml")
            job_id = mgr.submit_compare({
                "strategies": [
                    {"name": "ma_cross", "params": {"fast": 10, "slow": 30, "direction": "long_only"}, "label": "MA"},
                    {"name": "rsi_reversion", "params": {"period": 14, "oversold": 30, "overbought": 70}, "label": "RSI"},
                ],
                "data": {"source": "db", "symbol": "BTC/USDT", "timeframe": "1h", "days": 30, "seed": 42, "storage_db": db},
                "risk": {"max_position_pct": 0.5, "leverage": 1},
                "backtest": {"initial_capital": 10000, "fee_rate": 0.001, "slippage": 0.0005, "funding_rate_8h": 0},
            })
            deadline = time.time() + 30
            job = None
            while time.time() < deadline:
                job = mgr.get_compare_job(job_id)
                if job and job["status"] != "running":
                    break
                time.sleep(0.2)
            self.assertIsNotNone(job)
            self.assertEqual(job["status"], "done", job.get("error"))
            self.assertEqual(len(job["results"]), 2)
            for r in job["results"]:
                self.assertIsNotNone(r["metrics"])
                self.assertGreater(len(r["equity_curve"]), 0)

    def test_live_session_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "system": {"data_dir": tmp},
                "backtest": {"fee_rate": 0.001, "slippage": 0.0005},
                "exchange": {"id": "binance", "sandbox": False},
                "risk": {},
            }
            lm = LiveManager(cfg)
            lm.mode = "paper"
            lm.symbol = "BTC/USDT"
            lm.timeframe = "1h"
            lm.data_source = "exchange"
            lm.poll_interval = 5.0
            lm.warmup_bars = 200
            lm.strategy_name = "ma_cross"
            lm.strategy = SimpleNamespace(params={"fast": 5, "slow": 20})
            lm.risk = RiskManager(max_position_pct=0.5)
            lm._save_session({"paper_initial_balance": 12345})
            sess = load_live_session(cfg)
            self.assertIsNotNone(sess)
            self.assertEqual(sess["symbol"], "BTC/USDT")
            self.assertEqual(sess["paper_initial_balance"], 12345)
            self.assertEqual(sess["strategy"]["params"]["fast"], 5)
            lm._clear_session()
            self.assertIsNone(load_live_session(cfg))


def generate_fixture_df():
    # 使用交易所真实 K 线 fixture（OKX BTC/USDT 1h）
    return load_real_ohlcv("1h", n=400)


if __name__ == "__main__":
    unittest.main()
