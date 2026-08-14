"""??????????"""
from __future__ import annotations

import itertools
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from quant.backtest.engine import BacktestEngine
from quant.config import exchange_proxy, load_config
from quant.data.fetcher import ExchangeDataFetcher
from quant.data.storage import SQLiteStorage
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy

TARGETS = {
    "sharpe": lambda m: m.get("sharpe", -99),
    "total_return": lambda m: m.get("total_return", -99),
    "annual_return": lambda m: m.get("annual_return", -99),
    "win_rate": lambda m: m.get("win_rate", -1),
    "profit_factor": lambda m: m.get("profit_factor", -99),
    "calmar": lambda m: m.get("calmar", -99),
    "sqn": lambda m: m.get("sqn", -99),
}


def expand_ranges(param_ranges: dict) -> list[dict]:
    """? {param: [values]} ??????????"""
    keys = list(param_ranges.keys())
    if not keys:
        return [{}]
    combos = list(itertools.product(*[param_ranges[k] for k in keys]))
    return [dict(zip(keys, c)) for c in combos]


class Optimizer:
    """????????????????????????"""

    def __init__(self, config_path):
        self.config_path = config_path

    def run(self, strategy_name: str, param_ranges: dict, data_cfg: dict, risk_cfg: dict | None = None,
            target: str = "sharpe", max_combos: int = 100, workers: int = 4, progress=None,
            holdout_ratio: float = 0.25, min_trades: int = 0) -> dict:
        if target not in TARGETS:
            raise ValueError(f"??????: {target}??? {list(TARGETS)}")
        combos = expand_ranges(param_ranges)
        if len(combos) > max_combos:
            combos = combos[:max_combos]
        cfg = load_config(self.config_path)
        bt_cfg = {**cfg["backtest"], **(data_cfg.get("backtest") or {})}

        df = self._load_data(data_cfg)
        # 样本外验证：训练段选优，样本外段验证（防过拟合）
        holdout_ratio = max(0.0, min(0.6, float(holdout_ratio or 0.0)))
        if holdout_ratio > 0 and len(df) > 100:
            split = int(len(df) * (1.0 - holdout_ratio))
            train_df = df.iloc[:split]
            test_df = df.iloc[split:]
        else:
            train_df = df
            test_df = df.iloc[0:0]
        results = []
        done = 0
        lock = threading.Lock()

        def one(combo):
            params = dict(combo)
            direction = params.pop("direction", None)
            strategy = create_strategy(strategy_name, params)
            risk = RiskManager.from_config(risk_cfg or {})
            if direction:
                risk.trade_direction = direction
            engine = BacktestEngine(
                strategy=strategy, data=train_df,
                initial_capital=float(bt_cfg.get("initial_capital", 10000)),
                fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
                slippage=float(bt_cfg.get("slippage", 0.0005)),
                risk=risk, symbol=data_cfg.get("symbol", "BTC/USDT"),
                funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
            )
            try:
                result = engine.run()
                m = result.metrics
                if int(m.get("num_trades", 0)) < min_trades:
                    return {
                        "params": combo,
                        "target_value": -999,
                        "metrics": None,
                        "error": "交易数不足（" + str(m.get("num_trades", 0)) + " < " + str(min_trades) + "）",
                    }
                return {
                    "params": combo,
                    "target_value": TARGETS[target](m),
                    "metrics": {
                        "total_return": m.get("total_return"),
                        "annual_return": m.get("annual_return"),
                        "sharpe": m.get("sharpe"),
                        "max_drawdown": m.get("max_drawdown"),
                        "win_rate": m.get("win_rate"),
                        "profit_factor": m.get("profit_factor"),
                        "num_trades": m.get("num_trades"),
                        "calmar": m.get("calmar"),
                        "sqn": m.get("sqn"),
                        "final_equity": m.get("final_equity"),
                    },
                    "error": None,
                }
            except Exception as exc:  # noqa: BLE001
                return {"params": combo, "target_value": -999, "metrics": None, "error": str(exc)[:120]}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, c) for c in combos]
            for fut in as_completed(futures):
                results.append(fut.result())
                done += 1
                if progress:
                    progress(done, len(combos))

        results.sort(key=lambda r: r["target_value"], reverse=True)
        best = results[0] if results else None
        oos_metrics = None
        if best and best.get("metrics") and len(test_df) >= 50:
            try:
                params = dict(best["params"])
                direction = params.pop("direction", None)
                strategy2 = create_strategy(strategy_name, params)
                risk2 = RiskManager.from_config(risk_cfg or {})
                if direction:
                    risk2.trade_direction = direction
                engine2 = BacktestEngine(
                    strategy=strategy2, data=test_df,
                    initial_capital=float(bt_cfg.get("initial_capital", 10000)),
                    fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
                    slippage=float(bt_cfg.get("slippage", 0.0005)),
                    risk=risk2, symbol=data_cfg.get("symbol", "BTC/USDT"),
                    funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
                )
                m2 = engine2.run().metrics
                oos_metrics = {
                    "total_return": m2.get("total_return"),
                    "annual_return": m2.get("annual_return"),
                    "sharpe": m2.get("sharpe"),
                    "max_drawdown": m2.get("max_drawdown"),
                    "win_rate": m2.get("win_rate"),
                    "profit_factor": m2.get("profit_factor"),
                    "num_trades": m2.get("num_trades"),
                    "calmar": m2.get("calmar"),
                    "sqn": m2.get("sqn"),
                }
            except Exception:  # noqa: BLE001
                oos_metrics = None
        return {
            "strategy": strategy_name,
            "target": target,
            "total_combos": len(combos),
            "holdout_ratio": holdout_ratio,
            "min_trades": min_trades,
            "in_sample_metrics": best.get("metrics") if best else None,
            "oos_metrics": oos_metrics,
            "best": best,
            "results": results,
        }

    def _load_data(self, data_cfg: dict):
        source = data_cfg.get("source", "exchange")
        symbol = data_cfg.get("symbol", "BTC/USDT")
        timeframe = data_cfg.get("timeframe", "4h")
        days = int(data_cfg.get("days", 300))
        seed = int(data_cfg.get("seed", 42))
        if source == "synthetic":
            raise ValueError("合成数据已停用，系统仅使用交易所真实行情")
        if source == "db":
            storage = SQLiteStorage(data_cfg.get("storage_db", "data/ohlcv.db"))
            df = storage.load_ohlcv(symbol, timeframe)
            storage.close()
            if df.empty:
                raise ValueError("?????")
            return df
        fetcher = ExchangeDataFetcher(data_cfg.get("exchange", "binance"), proxy=exchange_proxy(load_config(self.config_path)))
        since = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) - days * 86_400_000
        return fetcher.fetch_ohlcv(symbol, timeframe, since=since)
