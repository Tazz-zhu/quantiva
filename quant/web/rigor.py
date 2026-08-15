"""RigorManager —— 抗过拟合工具与 FreqAI 的 Web 任务管理。

- walkforward: 滚动样本外验证（异步任务）
- lookahead / recursive: 前视 / 递归漂移检测（同步）
- significance: 对某策略回测结果做统计显著性检验（同步）
- freqai: FreqAI 训练 / 滚动样本外回测（异步）、状态 / 实时推理（同步）
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from quant.backtest.engine import BacktestEngine
from quant.config import exchange_proxy, load_config
from quant.data.fetcher import ExchangeDataFetcher
from quant.data.storage import SQLiteStorage
from quant.freqai import FreqAIPipeline, FreqAIStrategy
from quant.freqai.retrainer import FreqAIRetrainer
from quant.rigor.lookahead import analyze_lookahead
from quant.rigor.recursive import analyze_recursive
from quant.rigor.significance import (
    bootstrap_p_value,
    deflated_sharpe,
    parameter_stability,
    permutation_test,
    strategy_verdict,
)
from quant.rigor.walkforward import run_walkforward
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy
from quant.utils.logger import setup_logger

logger = setup_logger("rigor")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ohlcv(config_path: str | Path, data_cfg: dict) -> pd.DataFrame:
    """加载 K 线：优先本地库，不足则从交易所抓取（与 BacktestManager 一致）。"""
    storage = SQLiteStorage(data_cfg.get("storage_db", "data/ohlcv.db"))
    try:
        df = storage.load_ohlcv(data_cfg.get("symbol", "BTC/USDT"), data_cfg.get("timeframe", "1h"))
    finally:
        storage.close()
    if len(df) < 200:
        fetcher = ExchangeDataFetcher(
            data_cfg.get("exchange", "binance"),
            proxy=exchange_proxy(load_config(config_path)),
        )
        df = fetcher.fetch_ohlcv_paginated(
            data_cfg.get("symbol", "BTC/USDT"),
            data_cfg.get("timeframe", "1h"),
            days=int(data_cfg.get("days", 730)),
        )
        storage = SQLiteStorage(data_cfg.get("storage_db", "data/ohlcv.db"))
        try:
            storage.save_ohlcv(data_cfg.get("symbol", "BTC/USDT"), data_cfg.get("timeframe", "1h"), df)
        finally:
            storage.close()
    if df.empty:
        raise ValueError("行情数据为空，请先在「数据管理」抓取或检查网络")
    return df


class RigorManager:
    """抗过拟合 / FreqAI 任务管理。"""

    MAX_JOBS = 30

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.retrainer: FreqAIRetrainer | None = None

    # ------------------------------------------------------------------ #
    def _submit(self, name: str, params: dict, fn: Callable[[dict], dict]) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "kind": name,
            "status": "running",
            "created_at": _now_iso(),
            "finished_at": None,
            "params": params,
            "result": None,
            "error": None,
        }
        with self._lock:
            self.jobs[job_id] = job

        def runner():
            try:
                res = fn(params)
                with self._lock:
                    if job_id in self.jobs:
                        self.jobs[job_id].update(status="done", finished_at=_now_iso(), result=res)
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s 任务失败", name)
                with self._lock:
                    if job_id in self.jobs:
                        self.jobs[job_id].update(status="error", finished_at=_now_iso(), error=str(exc)[:300])

        threading.Thread(target=runner, daemon=True).start()
        return job_id

    # ------------------------------------------------------------------ #
    # Walk-Forward
    # ------------------------------------------------------------------ #
    def submit_walkforward(self, body: dict) -> str:
        def fn(p: dict) -> dict:
            return run_walkforward(
                self.config_path,
                strategy_name=p["strategy"],
                param_ranges=p.get("param_ranges") or {},
                data_cfg=p.get("data") or {},
                risk_cfg=p.get("risk"),
                bt_cfg=p.get("backtest"),
                loss=p.get("loss", "sharpe"),
                n_splits=int(p.get("n_splits", 4)),
                train_ratio=float(p.get("train_ratio", 0.6)),
                expanding=bool(p.get("expanding", False)),
                min_trades=int(p.get("min_trades", 5)),
                max_combos=int(p.get("max_combos", 100)),
                workers=int(p.get("workers", 4)),
            )

        return self._submit("walkforward", body, fn)

    # ------------------------------------------------------------------ #
    # 同步分析
    # ------------------------------------------------------------------ #
    def lookahead(self, body: dict) -> dict:
        df = load_ohlcv(self.config_path, body.get("data") or {})
        strategy = create_strategy(body["strategy"], body.get("params") or {})
        return analyze_lookahead(
            strategy, df,
            max_checks=int(body.get("max_checks", 20)),
        )

    def recursive(self, body: dict) -> dict:
        df = load_ohlcv(self.config_path, body.get("data") or {})
        strategy = create_strategy(body["strategy"], body.get("params") or {})
        return analyze_recursive(
            strategy, df,
            warmup=int(body.get("warmup", 200)),
            max_checks=int(body.get("max_checks", 20)),
        )

    def significance(self, body: dict) -> dict:
        """对指定策略参数做回测，并输出统计显著性检验。"""
        cfg = load_config(self.config_path)
        data_cfg = body.get("data") or cfg.get("data", {})
        risk_cfg = body.get("risk") or cfg.get("risk", {})
        bt_cfg = {**cfg.get("backtest", {}), **(body.get("backtest") or {})}
        df = load_ohlcv(self.config_path, data_cfg)
        strategy = create_strategy(body["strategy"], body.get("params") or {})
        risk = RiskManager.from_config(risk_cfg)
        engine = BacktestEngine(
            strategy=strategy, data=df,
            initial_capital=float(bt_cfg.get("initial_capital", 10000)),
            fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
            slippage=float(bt_cfg.get("slippage", 0.0005)),
            risk=risk,
            symbol=data_cfg.get("symbol", "BTC/USDT"),
            funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
        )
        result = engine.run()
        returns = result.equity_curve.pct_change().dropna()
        trade_rets = [t.return_pct for t in result.trades]

        n_trials = int(body.get("n_trials", 1))
        # 参数寻优试验次数估计：若来自优化，用组合数近似
        if n_trials <= 1 and body.get("trials_from_params"):
            ranges = body.get("param_ranges") or {}
            prod = 1
            for v in ranges.values():
                prod *= max(1, len(v))
            n_trials = max(1, prod)

        sig = (
            bootstrap_p_value(returns.tolist(), n_boot=int(body.get("n_boot", 1000)), seed=int(body.get("seed", 42)))
            if len(returns) >= 20 else None
        )
        dsr = (
            deflated_sharpe(returns.tolist(), n_trials=n_trials, seed=int(body.get("seed", 42)))
            if len(returns) >= 20 else None
        )
        perm = (
            permutation_test(trade_rets, n_perm=int(body.get("n_perm", 1000)), seed=int(body.get("seed", 42)))
            if len(trade_rets) >= 5 else None
        )
        verdict = strategy_verdict(result.metrics, result.metrics, significance=sig)
        return {
            "metrics": result.metrics,
            "bootstrap": sig,
            "deflated_sharpe": dsr,
            "permutation": perm,
            "verdict": verdict,
            "num_trades": len(result.trades),
        }

    # ------------------------------------------------------------------ #
    # FreqAI
    # ------------------------------------------------------------------ #
    def _load_corr_data(self, body: dict) -> dict[str, pd.DataFrame] | None:
        """按 corr_symbols 加载关联对 K 线（用于横截面特征）。"""
        corr_symbols = body.get("corr_symbols") or []
        if not corr_symbols:
            return None
        cfg = load_config(self.config_path)
        data_cfg = body.get("data") or cfg.get("data", {})
        out = {}
        for sym in corr_symbols:
            try:
                d = load_ohlcv(self.config_path, {**data_cfg, "symbol": sym})
                if len(d) >= 100:
                    out[sym] = d
            except Exception:  # noqa: BLE001
                continue
        return out or None

    def _freqai_pipe(self, body: dict) -> FreqAIPipeline:
        fc = body.get("freqai") or {}
        return FreqAIPipeline(
            model_name=fc.get("model", body.get("model", "random_forest")),
            kind=fc.get("kind", body.get("kind", "regression")),
            horizon=int(fc.get("horizon", body.get("horizon", 5))),
            include_volume=bool(fc.get("include_volume", True)),
            seed=int(fc.get("seed", 42)),
            model_dir=fc.get("model_dir", "data/freqai"),
        )

    def submit_freqai_backtest(self, body: dict) -> str:
        def fn(p: dict) -> dict:
            cfg = load_config(self.config_path)
            data_cfg = p.get("data") or cfg.get("data", {})
            risk_cfg = p.get("risk") or cfg.get("risk", {})
            bt_cfg = {**cfg.get("backtest", {}), **(p.get("backtest") or {})}
            df = load_ohlcv(self.config_path, data_cfg)
            pipe = self._freqai_pipe(p)
            corr = self._load_corr_data(p)
            bt = pipe.backtest(
                df,
                n_windows=int(p.get("n_windows", 5)),
                min_train=int(p.get("min_train", 100)),
                corr_data=corr,
            )
            pred_df = bt["data"]
            strategy = FreqAIStrategy(p.get("strategy_params") or {})
            risk = RiskManager.from_config(risk_cfg)
            engine = BacktestEngine(
                strategy=strategy, data=pred_df,
                initial_capital=float(bt_cfg.get("initial_capital", 10000)),
                fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
                slippage=float(bt_cfg.get("slippage", 0.0005)),
                risk=risk,
                symbol=data_cfg.get("symbol", "BTC/USDT"),
                funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
            )
            result = engine.run()
            return {
                "metrics": result.metrics,
                "prediction_coverage": bt["prediction_coverage"],
                "correlation": bt["correlation"],
                "windows": bt["windows"],
                "horizon": bt["horizon"],
                "model": bt["model"],
                "kind": bt["kind"],
                "equity_curve": [[int(ts.timestamp() * 1000), float(v)] for ts, v in result.equity_curve.items()],
                "predictions": [[int(ts.timestamp() * 1000), None if pd.isna(v) else float(v)]
                                for ts, v in pred_df["freqai_pred"].items()],
                "breakdown": result.breakdown,
                "trade_stats": result.trade_stats,
            }

        return self._submit("freqai_backtest", body, fn)

    def submit_freqai_train(self, body: dict) -> str:
        def fn(p: dict) -> dict:
            cfg = load_config(self.config_path)
            data_cfg = p.get("data") or cfg.get("data", {})
            df = load_ohlcv(self.config_path, data_cfg)
            pipe = self._freqai_pipe(p)
            return pipe.train(
                df,
                train_ratio=float(p.get("train_ratio", 0.8)),
                name=p.get("name"),
                corr_data=self._load_corr_data(p),
            )

        return self._submit("freqai_train", body, fn)

    # ---- FreqAI 定时重训调度 ----
    def freqai_schedule(self, body: dict) -> dict:
        action = body.get("action", "status")
        if self.retrainer is None:
            fc = self.config_freqai()
            pipe = FreqAIPipeline(
                model_name=fc.get("model", "random_forest"),
                kind=fc.get("kind", "regression"),
                horizon=int(fc.get("horizon", 5)),
                seed=int(fc.get("seed", 42)),
                model_dir=fc.get("model_dir", "data/freqai"),
            )
            self.retrainer = FreqAIRetrainer(
                pipe,
                loader=lambda: self._retrain_loader(),
                interval_hours=float(body.get("interval_hours", fc.get("retrain_interval_hours", 6))),
                name="live",
            )
        if action == "start":
            if body.get("interval_hours"):
                self.retrainer.interval_hours = float(body["interval_hours"])
            self.retrainer.start()
        elif action == "stop":
            self.retrainer.stop()
        elif action == "train_now":
            return {"trained": self.retrainer.train_now()}
        return self.retrainer.status()

    def _retrain_loader(self):
        cfg = load_config(self.config_path)
        data_cfg = cfg.get("freqai", {}).get("data") or cfg.get("data", {})
        df = load_ohlcv(self.config_path, data_cfg)
        corr_symbols = (cfg.get("freqai", {}) or {}).get("corr_symbols") or []
        corr = None
        if corr_symbols:
            corr = {}
            for sym in corr_symbols:
                try:
                    d = load_ohlcv(self.config_path, {**data_cfg, "symbol": sym})
                    if len(d) >= 100:
                        corr[sym] = d
                except Exception:  # noqa: BLE001
                    continue
            corr = corr or None
        return df, corr

    def freqai_retrainer_status(self) -> dict:
        if self.retrainer is None:
            return {"running": False, "name": None}
        return self.retrainer.status()

    def freqai_status(self) -> dict:
        fc = self.config_freqai()
        pipe = FreqAIPipeline(model_dir=fc.get("model_dir", "data/freqai"))
        return {"models": pipe.list_models(), "config": fc}

    def config_freqai(self) -> dict:
        cfg = load_config(self.config_path)
        return cfg.get("freqai", {}) or {}

    def freqai_predict(self, body: dict) -> dict:
        cfg = load_config(self.config_path)
        data_cfg = body.get("data") or cfg.get("data", {})
        df = load_ohlcv(self.config_path, data_cfg)
        pipe = self._freqai_pipe(body)
        return pipe.predict_latest(df, name=body.get("name"), corr_data=self._load_corr_data(body))

    # ------------------------------------------------------------------ #
    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [
                {k: v for k, v in job.items() if k != "result"}
                for job in sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)
            ]

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self.jobs:
                return False
            del self.jobs[job_id]
        return True

    def prune(self) -> None:
        with self._lock:
            while len(self.jobs) > self.MAX_JOBS:
                oldest = min(self.jobs, key=lambda k: self.jobs[k]["created_at"])
                if self.jobs[oldest]["status"] == "running":
                    break
                self.jobs.pop(oldest, None)
