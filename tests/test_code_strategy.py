"""代码策略单元测试。"""
import unittest

from quant.backtest.engine import BacktestEngine
from quant.data.fetcher import generate_synthetic_ohlcv
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy

GOOD_CODE = '''
def generate_signals(df, params):
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 30))
    return (sma(df["close"], fast) > sma(df["close"], slow)).astype(float)
'''

RSI_CODE = '''
def generate_signals(df, params):
    r = rsi(df["close"], 14)
    signal = (r < 30).astype(float)
    return signal
'''


class TestCodeStrategy(unittest.TestCase):
    def setUp(self):
        self.data = generate_synthetic_ohlcv(timeframe="4h", days=200, seed=9)

    def test_code_runs(self):
        strategy = create_strategy("code", {"code": GOOD_CODE, "fast": 10, "slow": 30})
        engine = BacktestEngine(strategy, self.data, initial_capital=10000,
                                risk=RiskManager(max_position_pct=0.5))
        result = engine.run()
        self.assertGreaterEqual(result.metrics["num_trades"], 0)
        self.assertTrue((result.positions >= 0).all())

    def test_code_with_indicators(self):
        strategy = create_strategy("code", {"code": RSI_CODE})
        engine = BacktestEngine(strategy, self.data, risk=RiskManager(max_position_pct=0.5))
        result = engine.run()
        self.assertGreaterEqual(result.metrics["num_trades"], 0)

    def test_invalid_code(self):
        strategy = create_strategy("code", {"code": "def generate_signals(df): return 1"})
        # 返回非 Series 应报错
        with self.assertRaises(Exception):
            strategy.generate_signals(self.data)

    def test_syntax_error(self):
        strategy = create_strategy("code", {"code": "def generate_signals(df): ???"})
        with self.assertRaises(Exception):
            strategy.generate_signals(self.data)

    def test_wrong_length(self):
        bad = "def generate_signals(df, params):\n    return pd.Series([1.0])\n"
        strategy = create_strategy("code", {"code": bad})
        with self.assertRaises(ValueError):
            strategy.generate_signals(self.data)


if __name__ == "__main__":
    unittest.main()
