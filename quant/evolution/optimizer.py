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
from quant.rigor.losses import LOSS_FUNCTIONS, loss_score
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
        use_loss = target in LOSS_FUNCTIONS
        if target not in TARGETS and not use_loss:
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
                    "target_value": loss_score(target, result) if use_loss else TARGETS[target](m),
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

    def run_bayesian(
        self,
        strategy_name: str,
        param_space: dict,
        data_cfg: dict,
        risk_cfg: dict | None = None,
        target: str = "sharpe",
        n_trials: int = 50,
        timeout: float = 600.0,
        workers: int = 1,
        progress=None,
        holdout_ratio: float = 0.25,
        min_trades: int = 0,
        seed: int = 42,
    ) -> dict:
        """贝叶斯超参优化（freqtrade optuna 方法论移植）。

        param_space: {参数: 候选列表 或 {"min","max","step"} 数值区间}
        使用 optuna TPE 采样器智能搜索，比穷举网格效率高一个量级；
        若未安装 optuna 则回退为随机搜索。
        """
        use_loss = target in LOSS_FUNCTIONS

        def sample_params(trial):
            params = {}
            for k, space in param_space.items():
                if isinstance(space, dict):
                    lo = float(space.get("min", 0))
                    hi = float(space.get("max", 100))
                    step = space.get("step")
                    if space.get("int", False) or isinstance(space.get("min"), int) and isinstance(space.get("max"), int):
                        if step:
                            params[k] = trial.suggest_int(k, int(lo), int(hi), step=int(step))
                        else:
                            params[k] = trial.suggest_int(k, int(lo), int(hi))
                    else:
                        params[k] = trial.suggest_float(k, lo, hi)
                else:
                    cands = list(space)
                    params[k] = trial.suggest_categorical(k, cands)
            return params

        def evaluate(params: dict) -> float:
            direction = params.pop("direction", None)
            try:
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
                result = engine.run()
                m = result.metrics
                if int(m.get("num_trades", 0)) < min_trades:
                    return -9e9
                return loss_score(target, result) if use_loss else TARGETS[target](m)
            except Exception:  # noqa: BLE001
                return -9e9

        cfg = load_config(self.config_path)
        bt_cfg = {**cfg["backtest"], **(data_cfg.get("backtest") or {})}
        df = self._load_data(data_cfg)
        holdout_ratio = max(0.0, min(0.6, float(holdout_ratio or 0.0)))
        if holdout_ratio > 0 and len(df) > 100:
            split = int(len(df) * (1.0 - holdout_ratio))
            train_df = df.iloc[:split]
            test_df = df.iloc[split:]
        else:
            train_df = df
            test_df = df.iloc[0:0]

        done = 0

        def tick(step=None):
            nonlocal done
            done += 1
            if progress:
                progress(done, n_trials)

        best = None
        results = []
        try:
            import optuna

            optuna.logging.set_verbosity(optuna.logging.WARNING)
            sampler = optuna.samplers.TPESampler(seed=seed)
            study = optuna.create_study(direction="maximize", sampler=sampler)
            study.optimize(
                lambda trial: evaluate(sample_params(trial)),
                n_trials=int(n_trials),
                timeout=float(timeout) if timeout else None,
                show_progress_bar=False,
            )
            for tr in study.trials:
                if tr.value is not None:
                    results.append({"params": tr.params, "target_value": float(tr.value)})
            best_params = dict(study.best_params)
            best_value = float(study.best_value)
            method = "bayesian_optuna"
        except Exception:  # noqa: BLE001（无 optuna 或出错 → 随机搜索回退）
            import random

            rng = random.Random(seed)
            results = []
            best_value = -9e9
            best_params = None
            for _ in range(int(n_trials)):
                params = {}
                for k, space in param_space.items():
                    if isinstance(space, dict):
                        lo, hi = float(space.get("min", 0)), float(space.get("max", 100))
                        if space.get("int", False) or isinstance(space.get("min"), int) and isinstance(space.get("max"), int):
                            params[k] = rng.randint(int(lo), int(hi))
                        else:
                            params[k] = round(rng.uniform(lo, hi), 4)
                    else:
                        params[k] = rng.choice(list(space))
                v = evaluate(dict(params))
                results.append({"params": params, "target_value": v})
                if v > best_value:
                    best_value = v
                    best_params = params
                tick()
            method = "random_fallback"

        results.sort(key=lambda r: r["target_value"], reverse=True)
        best = {"params": best_params, "target_value": best_value}
        if best_params is not None:
            try:
                p2 = dict(best_params)
                direction = p2.pop("direction", None)
                strategy2 = create_strategy(strategy_name, p2)
                risk2 = RiskManager.from_config(risk_cfg or {})
                if direction:
                    risk2.trade_direction = direction
                engine2 = BacktestEngine(
                    strategy=strategy2, data=train_df,
                    initial_capital=float(bt_cfg.get("initial_capital", 10000)),
                    fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
                    slippage=float(bt_cfg.get("slippage", 0.0005)),
                    risk=risk2, symbol=data_cfg.get("symbol", "BTC/USDT"),
                    funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
                )
                best["metrics"] = engine2.run().metrics
            except Exception:  # noqa: BLE001
                best["metrics"] = None

        oos_metrics = None
        if best and best.get("metrics") and len(test_df) >= 50:
            try:
                p3 = dict(best["params"])
                direction = p3.pop("direction", None)
                strategy3 = create_strategy(strategy_name, p3)
                risk3 = RiskManager.from_config(risk_cfg or {})
                if direction:
                    risk3.trade_direction = direction
                engine3 = BacktestEngine(
                    strategy=strategy3, data=test_df,
                    initial_capital=float(bt_cfg.get("initial_capital", 10000)),
                    fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
                    slippage=float(bt_cfg.get("slippage", 0.0005)),
                    risk=risk3, symbol=data_cfg.get("symbol", "BTC/USDT"),
                    funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
                )
                m3 = engine3.run().metrics
                oos_metrics = {
                    "total_return": m3.get("total_return"),
                    "annual_return": m3.get("annual_return"),
                    "sharpe": m3.get("sharpe"),
                    "max_drawdown": m3.get("max_drawdown"),
                    "win_rate": m3.get("win_rate"),
                    "profit_factor": m3.get("profit_factor"),
                    "num_trades": m3.get("num_trades"),
                    "calmar": m3.get("calmar"),
                    "sqn": m3.get("sqn"),
                }
            except Exception:  # noqa: BLE001
                oos_metrics = None

        return {
            "strategy": strategy_name,
            "target": target,
            "method": method,
            "total_combos": len(results),
            "n_trials": int(n_trials),
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