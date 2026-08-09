"""??????????????????????"""
from __future__ import annotations

import os

import json
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant.analytics.metrics import max_drawdown
from quant.ai.advisor import AIAdvisor
from quant.backtest.engine import BacktestEngine
from quant.web.audit import AuditLogger
from quant.web.auth import AuthManager
from quant.web.system import SystemService
from quant.evolution.manager import EvolutionManager
from quant.monitor.service import MarketMonitor
from quant.notify.feishu import FeishuNotifier
from quant.report.analysis import analyze
from quant.config import exchange_proxy, load_config
from quant.data.fetcher import ExchangeDataFetcher, generate_synthetic_ohlcv
from quant.data.storage import SQLiteStorage
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy
from quant.utils.logger import setup_logger

logger = setup_logger("web")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _downsample(series: pd.Series, max_points: int = 2500):
    """? Series ???? [[ms, value], ...]?????????"""
    if len(series) == 0:
        return []
    if len(series) <= max_points:
        return [[int(ts.timestamp() * 1000), float(v)] for ts, v in series.items()]
    step = len(series) / max_points
    idx = [int(i * step) for i in range(max_points)]
    return [[int(series.index[i].timestamp() * 1000), float(series.iloc[i])] for i in idx]


class BacktestManager:
    """??????????????????? reports/runs/ ??"""

    MAX_JOBS = 50

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.jobs: dict[str, dict] = {}
        self.compare_jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._runs_dir = Path("reports/runs")
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._load_persisted()

    def submit(self, params: dict) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "status": "running",
            "created_at": _now_iso(),
            "finished_at": None,
            "params": params,
            "metrics": None,
            "error": None,
        }
        with self._lock:
            self.jobs[job_id] = job
        thread = threading.Thread(target=self._run, args=(job_id, params), daemon=True)
        thread.start()
        return job_id

    def _run(self, job_id: str, params: dict) -> None:
        try:
            cfg = load_config(self.config_path)
            strategy_cfg = params.get("strategy") or cfg["strategy"]
            risk_cfg = params.get("risk") or cfg["risk"]
            data_cfg = params.get("data") or cfg["data"]
            bt_cfg = params.get("backtest") or cfg["backtest"]

            strategy = create_strategy(strategy_cfg["name"], strategy_cfg.get("params"))
            risk = RiskManager.from_config(risk_cfg)

            symbol = data_cfg.get("symbol", "BTC/USDT")
            timeframe = data_cfg.get("timeframe", "1h")
            days = int(data_cfg.get("days", 730))
            source = data_cfg.get("source", "synthetic")
            seed = int(data_cfg.get("seed", 42))

            df = self._load_data(source, data_cfg, symbol, timeframe, days, seed)

            engine = BacktestEngine(
                strategy=strategy,
                data=df,
                initial_capital=float(bt_cfg.get("initial_capital", 10000)),
                fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
                slippage=float(bt_cfg.get("slippage", 0.0005)),
                risk=risk,
                symbol=symbol,
                funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
            )
            result = engine.run()
            payload = self._build_payload(job_id, result, strategy, symbol, timeframe, source)
            # 成本敏感性压力测试：0.5x / 2x 手续费与滑点
            try:
                payload["cost_sensitivity"] = self._cost_sensitivity(strategy, df, risk, bt_cfg, symbol)
            except Exception:  # noqa: BLE001
                payload["cost_sensitivity"] = None
            # ???????????????
            if getattr(self, "trade_store", None) and load_config(self.config_path).get("evolution", {}).get("save_backtest_trades", False):
                self.trade_store.save_trades(
                    payload["trades"], source="backtest", strategy=strategy.name,
                    symbol=symbol, timeframe=timeframe, params=strategy.params,
                )

            with self._lock:
                self.jobs[job_id].update(
                    status="done",
                    finished_at=_now_iso(),
                    metrics=result.metrics,
                    result=payload,
                )
            self._persist(job_id, payload)
            # ??????????
            with self._lock:
                while len(self.jobs) > self.MAX_JOBS:
                    oldest = min(self.jobs, key=lambda k: self.jobs[k]["created_at"])
                    if self.jobs[oldest]["status"] == "running":
                        break
                    self.jobs.pop(oldest, None)
        except Exception as exc:  # noqa: BLE001
            logger.exception("???? %s ??", job_id)
            with self._lock:
                self.jobs[job_id].update(
                    status="error", finished_at=_now_iso(), error=str(exc)
                )

    def _load_data(self, source, data_cfg, symbol, timeframe, days, seed) -> pd.DataFrame:
        if source == "synthetic":
            return generate_synthetic_ohlcv(timeframe=timeframe, days=days, seed=seed)
        if source == "db":
            storage = SQLiteStorage(data_cfg.get("storage_db", "data/ohlcv.db"))
            df = storage.load_ohlcv(symbol, timeframe)
            storage.close()
            if df.empty:
                raise ValueError(f"??????? {symbol} {timeframe} ????????")
            return df
        # exchange
        storage = SQLiteStorage(data_cfg.get("storage_db", "data/ohlcv.db"))
        df = storage.load_ohlcv(symbol, timeframe)
        if len(df) < 200:
            fetcher = ExchangeDataFetcher(data_cfg.get("exchange", "binance"), proxy=exchange_proxy(load_config(self.config_path)))
            df = fetcher.fetch_ohlcv_paginated(symbol, timeframe, days=days)
            storage.save_ohlcv(symbol, timeframe, df)
        storage.close()
        if df.empty:
            raise ValueError("???????????????")
        return df

    def _cost_sensitivity(self, strategy, df, risk, bt_cfg, symbol) -> dict:
        """成本敏感性：在 0.5x / 2x 手续费与滑点下重跑回测。"""
        base_fee = float(bt_cfg.get("fee_rate", 0.001))
        base_slip = float(bt_cfg.get("slippage", 0.0005))
        out: dict = {}
        for label, fee_k, slip_k in (("halved", 0.5, 0.5), ("doubled", 2.0, 2.0)):
            engine = BacktestEngine(
                strategy=strategy, data=df,
                initial_capital=float(bt_cfg.get("initial_capital", 10000)),
                fee_rate=base_fee * fee_k,
                slippage=base_slip * slip_k,
                risk=risk, symbol=symbol,
                funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
            )
            m = engine.run().metrics
            out[label] = {
                "total_return": m.get("total_return"),
                "sharpe": m.get("sharpe"),
                "num_trades": m.get("num_trades"),
            }
        return out

    def _build_payload(self, job_id, result, strategy, symbol, timeframe, source) -> dict:
        analysis = analyze(result, timeframe)
        equity = result.equity_curve
        dd, _ = max_drawdown(equity)
        running_max = equity.cummax()
        drawdown = equity / running_max - 1.0
        benchmark = result.data["close"] / result.data["close"].iloc[0] * float(
            result.metrics["initial_capital"]
        )
        trades = [
            {
                "side": t.side,
                "entry_time": t.entry_time.isoformat(),
                "entry_price": round(t.entry_price, 6),
                "exit_time": t.exit_time.isoformat(),
                "exit_price": round(t.exit_price, 6),
                "quantity": round(t.quantity, 8),
                "fees": round(t.fees, 4),
                "pnl": round(t.pnl, 4),
                "return_pct": round(t.return_pct, 6),
                "reason": t.reason,
            }
            for t in result.trades
        ]
        return {
            "id": job_id,
            "strategy": strategy.name,
            "strategy_params": strategy.params,
            "symbol": symbol,
            "timeframe": timeframe,
            "source": source,
            "metrics": result.metrics,
            "equity_curve": _downsample(equity),
            "drawdown": _downsample(drawdown),
            "benchmark": _downsample(benchmark),
            "trades": trades,
            "signals": _downsample(result.data["signal"]),
            "close": _downsample(result.data["close"]),
            "analysis": analysis,
        }

    def _persist(self, job_id: str, payload: dict) -> None:
        path = self._runs_dir / f"{job_id}.json"
        payload["created_at"] = self.jobs[job_id]["created_at"]
        payload["finished_at"] = self.jobs[job_id]["finished_at"]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_persisted(self) -> None:
        """?????? reports/runs ???????"""
        for path in sorted(self._runs_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                job = {
                    "id": payload.get("id", path.stem),
                    "status": "done",
                    "created_at": payload.get("created_at", _now_iso()),
                    "finished_at": payload.get("finished_at"),
                    "params": {"strategy": {"name": payload.get("strategy", "?")}},
                    "metrics": payload.get("metrics"),
                    "result": payload,
                    "error": None,
                }
                self.jobs[job["id"]] = job
            except Exception as exc:  # noqa: BLE001
                logger.warning("???????? %s: %s", path.name, exc)

    def submit_compare(self, params: dict) -> str:
        """多策略对比：并行跑多组策略，返回对比任务 id。"""
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "status": "running",
            "created_at": _now_iso(),
            "finished_at": None,
            "params": params,
            "results": None,
            "error": None,
        }
        with self._lock:
            self.compare_jobs[job_id] = job
        thread = threading.Thread(target=self._run_compare, args=(job_id, params), daemon=True)
        thread.start()
        return job_id

    def _run_compare(self, job_id: str, params: dict) -> None:
        try:
            cfg = load_config(self.config_path)
            data_cfg = params.get("data") or cfg["data"]
            risk_cfg = params.get("risk") or cfg["risk"]
            bt_cfg = params.get("backtest") or cfg["backtest"]
            df = self._load_data(
                data_cfg.get("source", "synthetic"), data_cfg,
                data_cfg.get("symbol", "BTC/USDT"),
                data_cfg.get("timeframe", "1h"),
                int(data_cfg.get("days", 365)),
                int(data_cfg.get("seed", 42)),
            )
            strategies = params.get("strategies") or []

            def run_one(item: dict) -> dict:
                try:
                    name = item.get("name", "ma_cross")
                    strategy = create_strategy(name, item.get("params"))
                    risk = RiskManager.from_config(risk_cfg)
                    if item.get("direction"):
                        risk.trade_direction = item["direction"]
                    engine = BacktestEngine(
                        strategy=strategy, data=df,
                        initial_capital=float(bt_cfg.get("initial_capital", 10000)),
                        fee_rate=float(bt_cfg.get("fee_rate", 0.001)),
                        slippage=float(bt_cfg.get("slippage", 0.0005)),
                        risk=risk, symbol=data_cfg.get("symbol", "BTC/USDT"),
                        funding_rate_8h=float(bt_cfg.get("funding_rate_8h", 0.0)),
                    )
                    res = engine.run()
                    return {
                        "label": item.get("label") or name,
                        "strategy": name,
                        "params": strategy.params,
                        "metrics": res.metrics,
                        "equity_curve": _downsample(res.equity_curve),
                        "error": None,
                    }
                except Exception as exc:  # noqa: BLE001
                    return {
                        "label": item.get("label") or item.get("name", "?"),
                        "strategy": item.get("name", "?"),
                        "params": item.get("params"),
                        "metrics": None,
                        "equity_curve": [],
                        "error": str(exc)[:120],
                    }

            results = []
            if strategies:
                with ThreadPoolExecutor(max_workers=min(4, max(1, len(strategies)))) as pool:
                    results = list(pool.map(run_one, strategies))
            with self._lock:
                job = self.compare_jobs.get(job_id)
                if job:
                    job.update(status="done", finished_at=_now_iso(), results=results)
        except Exception as exc:  # noqa: BLE001
            logger.exception("对比任务失败")
            with self._lock:
                job = self.compare_jobs.get(job_id)
                if job:
                    job.update(status="error", finished_at=_now_iso(), error=str(exc))

    def get_compare_job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self.compare_jobs.get(job_id)
            return dict(job) if job else None

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def list_jobs(self) -> list[dict]:
        with self._lock:
            jobs = []
            for job in sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True):
                jobs.append(
                    {
                        "id": job["id"],
                        "status": job["status"],
                        "created_at": job["created_at"],
                        "finished_at": job["finished_at"],
                        "strategy": (job.get("result") or {}).get("strategy")
                        or (job["params"].get("strategy") or {}).get("name", "?"),
                        "symbol": (job.get("result") or {}).get("symbol")
                        or (job["params"].get("data") or {}).get("symbol", "?"),
                        "timeframe": (job.get("result") or {}).get("timeframe")
                        or (job["params"].get("data") or {}).get("timeframe", "?"),
                        "metrics": job.get("metrics"),
                        "error": job.get("error"),
                    }
                )
            return jobs

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self.jobs:
                return False
            del self.jobs[job_id]
        path = self._runs_dir / f"{job_id}.json"
        if path.exists():
            path.unlink()
        return True


class AppState:
    """Web ???????"""

    def reload_services(self) -> None:
        """??????? AI / ???????????"""
        self.advisor = AIAdvisor(self.config)
        self.notifier = FeishuNotifier(self.config)
        self.evolution = EvolutionManager(self.config_path, self.config)
        self.monitor.update_config(self.config.get("monitor", {}))

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.config = load_config(self.config_path)
        self.backtest = BacktestManager(self.config_path)
        self.live = None  # LiveManager ???????????????
        self.advisor = AIAdvisor(self.config)
        self.notifier = FeishuNotifier(self.config)
        deploy = self.config.get("deployment", {}) or {}
        self.deployment_role = os.getenv("QUANTX_ROLE", deploy.get("role", "all"))
        self.node_id = os.getenv("QUANTX_NODE_ID", deploy.get("node_id", "node-1"))
        self.audit = AuditLogger(self.config.get("system", {}).get("data_dir", "data") + "/audit.db")
        self.auth = AuthManager()
        self.system = SystemService(self.config)
        self.system.start_auto_backup()
        self.evolution = EvolutionManager(self.config_path, self.config)
        self.backtest.trade_store = self.evolution.store
        self.monitor = MarketMonitor(self.config, notifier=self.notifier)
        if self.deployment_role in ("all", "monitor") and self.config.get("monitor", {}).get("enabled", True):
            self.monitor.start()
        evo_cfg = self.config.get("evolution", {})
        if self.deployment_role in ("all", "monitor", "trader") and evo_cfg.get("auto_analyze_enabled", True):
            self.evolution.start_auto_analyzer(float(evo_cfg.get("auto_analyze_interval_hours", 6)))