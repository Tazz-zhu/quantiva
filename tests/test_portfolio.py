# -*- coding: utf-8 -*-
"""多币种组合回测测试：开仓上限 / 各币种贡献 / 组合指标。"""
import unittest

import numpy as np
import pandas as pd

from quant.backtest.portfolio import PortfolioBacktester
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy


def _synth(seed, drift, n=800):
    idx = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    r = np.random.default_rng(seed)
    rets = r.normal(drift, 0.02, n)
    close = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {"open": close * 0.998, "high": close * 1.012, "low": close * 0.988,
         "close": close, "volume": r.uniform(100, 500, n)}, index=idx
    )


class TestPortfolioBacktest(unittest.TestCase):
    def setUp(self):
        self.data = {
            "AAA/USDT": _synth(1, 0.0004),
            "BBB/USDT": _synth(2, -0.0001),
            "CCC/USDT": _synth(3, 0.0002),
        }

    def _run(self, max_open=2, direction="long_only", **kw):
        strategies = {
            s: create_strategy("ma_cross", {"fast": 10, "slow": 30, "direction": direction})
            for s in self.data
        }
        risk = RiskManager(max_position_pct=0.4, trade_direction=direction, stop_loss_pct=0.06)
        return PortfolioBacktester(
            strategies, self.data, initial_capital=10000, risk=risk,
            max_open_trades=max_open, **kw,
        ).run()

    def test_runs_and_metrics(self):
        r = self._run()
        self.assertEqual(r.metrics["symbols"], 3)
        self.assertGreaterEqual(r.metrics["num_trades"], 0)
        self.assertIn("total_return", r.metrics)
        self.assertEqual(len(r.equity_curve), len(self.data["AAA/USDT"]))

    def test_max_open_trades_respected(self):
        # 单笔仓位 40% + 3 个标的，若同时开满最多 max_open_trades
        r = self._run(max_open=2)
        # 通过检查每笔交易重叠窗口来验证：任一时刻开仓数 <= 2
        events = []
        for t in r.trades:
            events.append((t.entry_time, 1))
            events.append((t.exit_time, -1))
        events.sort(key=lambda x: x[0])
        cur = 0
        peak = 0
        for _ts, delta in events:
            cur += delta
            peak = max(peak, cur)
        self.assertLessEqual(peak, 2)

    def test_per_symbol_stats(self):
        r = self._run()
        self.assertEqual(set(r.per_symbol.keys()), set(self.data.keys()))
        total_pnl = sum(v["pnl"] for v in r.per_symbol.values())
        self.assertAlmostEqual(total_pnl, r.metrics["total_pnl"], delta=1.0)

    def test_breakdown(self):
        r = self._run()
        self.assertIn("by_exit_reason", r.breakdown)
        self.assertIn("by_month", r.breakdown)


if __name__ == "__main__":
    unittest.main()

