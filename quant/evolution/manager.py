"""进化管理器：优化任务、自动分析、迭代日志与前端状态。"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

from quant.evolution.optimizer import Optimizer
from quant.evolution.trade_store import TradeStore
from quant.utils.logger import setup_logger

logger = setup_logger("evolution")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvolutionManager:
    def __init__(self, config_path, config: dict):
        self.config_path = config_path
        self.config = config
        self.store = TradeStore(config.get("evolution", {}).get("db_path", "data/evolution.db"))
        self.optimizer = Optimizer(config_path)
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.auto_thread: threading.Thread | None = None
        self.auto_running = False
        self.last_auto_analyze: str | None = None

    def submit_optimize(self, params: dict) -> str:
        job_id = uuid.uuid4().hex[:10]
        job = {
            "id": job_id,
            "status": "running",
            "created_at": _now_iso(),
            "params": params,
            "result": None,
            "error": None,
        }
        with self._lock:
            self.jobs[job_id] = job
        thread = threading.Thread(target=self._run_optimize, args=(job_id, params), daemon=True)
        thread.start()
        return job_id

    def _run_optimize(self, job_id: str, params: dict) -> None:
        try:
            strategy = params.get("strategy", "ma_cross")
            ranges = params.get("param_ranges", {})
            data = params.get("data", {})
            risk = params.get("risk", {})
            target = params.get("target", "sharpe")
            max_combos = int(params.get("max_combos", 60))
            holdout_ratio = float(params.get("holdout_ratio", 0.25))
            min_trades = int(params.get("min_trades", 0))

            def progress(done, total):
                with self._lock:
                    job = self.jobs.get(job_id)
                    if job:
                        job["progress"] = str(done) + "/" + str(total)

            result = self.optimizer.run(
                strategy, ranges, data, risk_cfg=risk,
                target=target, max_combos=max_combos, progress=progress,
                holdout_ratio=holdout_ratio, min_trades=min_trades,
            )
            best = result.get("best") or {}
            if best.get("metrics"):
                iteration_id = self.store.save_iteration(
                    kind="optimize",
                    strategy=strategy,
                    title="参数优化（" + target + " 最优）",
                    params=best.get("params"),
                    metrics=best.get("metrics"),
                    conclusion=self._optimize_conclusion(result),
                )
                best["iteration_id"] = iteration_id
            with self._lock:
                job = self.jobs.get(job_id)
                if job:
                    job.update(status="done", finished_at=_now_iso(), result=result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("优化任务失败")
            with self._lock:
                job = self.jobs.get(job_id)
                if job:
                    job.update(status="error", finished_at=_now_iso(), error=str(exc))

    def _optimize_conclusion(self, result: dict) -> str:
        best = result.get("best") or {}
        lines = ["完成 " + str(result.get("total_combos", 0)) + " 组参数搜索，目标指标：" + result.get("target", "")
                 + "，样本外验证 " + format(float(result.get("holdout_ratio", 0) or 0) * 100, ".0f") + "%"
                 + "，最小交易数 " + str(result.get("min_trades", 0)) + "。"]
        if best.get("metrics"):
            m = best["metrics"]
            lines.append(
                "最优参数 " + str(best["params"]) + "：总收益 " + format(m.get("total_return", 0) * 100, ".2f") + "%"
                + "，夏普 " + format(m.get("sharpe", 0), ".2f") + "，最大回撤 " + format(m.get("max_drawdown", 0) * 100, ".2f") + "%"
                + "，胜率 " + format(m.get("win_rate", 0) * 100, ".1f") + "%，交易 " + str(m.get("num_trades", 0)) + " 笔。"
            )
        if result.get("oos_metrics"):
            o = result["oos_metrics"]
            lines.append(
                "样本外验证：总收益 " + format((o.get("total_return") or 0) * 100, ".2f") + "%"
                + "，夏普 " + format(o.get("sharpe") or 0, ".2f")
                + "，最大回撤 " + format((o.get("max_drawdown") or 0) * 100, ".2f") + "%"
                + "，交易 " + str(o.get("num_trades", 0)) + " 笔。"
            )
            is_sharpe = (best.get("metrics") or {}).get("sharpe", 0) or 0
            oos_sharpe = o.get("sharpe") or 0
            if is_sharpe > 0 and oos_sharpe < is_sharpe * 0.5:
                lines.append("⚠️ 过拟合警示：样本外夏普明显低于样本内，建议缩小参数网格或增大数据量。")
        if result.get("results"):
            valid = [r for r in result["results"] if r.get("metrics")]
            if valid:
                top = valid[:5]
                lines.append("Top5 参数组合：")
                for i, r in enumerate(top, 1):
                    lines.append(
                        "  " + str(i) + ". " + str(r["params"]) + " → 收益 " + format(r["metrics"]["total_return"] * 100, ".2f") + "% | "
                        + "夏普 " + format(r["metrics"]["sharpe"], ".2f") + " | 回撤 " + format(r["metrics"]["max_drawdown"] * 100, ".2f") + "%"
                    )
        return "\n".join(lines)

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

    def analyze_and_learn(self) -> dict:
        stats = self.store.stats()
        conclusion = self.store.generate_conclusion(stats)
        iteration_id = self.store.save_iteration(
            kind="auto_analysis",
            strategy="all",
            title="定时交易数据分析 · " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            metrics={"total": stats["total"]},
            conclusion=conclusion,
        )
        self.last_auto_analyze = _now_iso()
        return {"iteration_id": iteration_id, "conclusion": conclusion, "stats": stats}

    def start_auto_analyzer(self, interval_hours: float = 6.0) -> None:
        with self._lock:
            if self.auto_running:
                return
            self.auto_running = True
        self.auto_thread = threading.Thread(
            target=self._auto_loop, args=(float(interval_hours),), daemon=True
        )
        self.auto_thread.start()
        logger.info("进化自动分析已启动（每 %.1f 小时）", interval_hours)

    def stop_auto_analyzer(self) -> None:
        with self._lock:
            self.auto_running = False

    def _auto_loop(self, interval_hours: float) -> None:
        while True:
            with self._lock:
                if not self.auto_running:
                    return
            try:
                self.analyze_and_learn()
                logger.info("定时交易分析完成")
            except Exception as exc:  # noqa: BLE001
                logger.warning("定时分析失败: %s", exc)
            time.sleep(interval_hours * 3600)

    def status(self) -> dict:
        return {
            "auto_running": self.auto_running,
            "last_auto_analyze": self.last_auto_analyze,
            "trades_count": self.store.stats()["total"]["count"],
            "iterations_count": len(self.store.list_iterations(limit=1000)),
        }
