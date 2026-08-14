"""?????????"""
import unittest

from quant.backtest.engine import BacktestEngine
from fixture_loader import load_real_ohlcv
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy


class TestBacktest(unittest.TestCase):
    def setUp(self):
        self.data = load_real_ohlcv("1h", n=600)

    def test_ma_cross_runs(self):
        strategy = create_strategy("ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"})
        engine = BacktestEngine(
            strategy, self.data, initial_capital=10000,
            risk=RiskManager(max_position_pct=0.5),
        )
        result = engine.run()
        self.assertGreaterEqual(len(result.equity_curve), 1)
        self.assertAlmostEqual(result.equity_curve.iloc[0], 10000.0, places=6)
        self.assertIn("total_return", result.metrics)
        self.assertGreaterEqual(result.metrics["num_trades"], 0)

    def test_entry_fill_matches_next_open(self):
        strategy = create_strategy("ma_cross", {"fast": 10, "slow": 30})
        engine = BacktestEngine(
            strategy, self.data, slippage=0.0, fee_rate=0.0,
            risk=RiskManager(max_position_pct=0.5),
        )
        result = engine.run()
        for trade in result.trades:
            idx = self.data.index.get_loc(trade.entry_time)
            self.assertAlmostEqual(trade.entry_price, float(self.data["open"].iloc[idx]), places=6)

    def test_long_only_no_short(self):
        strategy = create_strategy("ma_cross", {"fast": 10, "slow": 30, "direction": "long_only"})
        engine = BacktestEngine(
            strategy, self.data,
            risk=RiskManager(max_position_pct=0.5, trade_direction="long_only"),
        )
        result = engine.run()
        self.assertTrue((result.positions >= 0).all())

    def test_stop_loss_limits_losses(self):
        data = load_real_ohlcv("1h", n=300)
        strategy = create_strategy("ma_cross", {"fast": 10, "slow": 30})
        engine = BacktestEngine(
            strategy, data,
            risk=RiskManager(max_position_pct=0.5, stop_loss_pct=0.05),
        )
        result = engine.run()
        for trade in result.trades:
            self.assertGreater(trade.return_pct, -0.07)


if __name__ == "__main__":
    unittest.main()
