"""FreqAI 定时重训调度器（freqtrade FreqAI 实盘重训移植）。

按固定间隔用最新行情重新训练模型并持久化，保持模型跟随市场漂移。
支持：
- start(interval_hours): 后台线程定时重训
- train_now(): 立即重训
- stop() / status()
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from quant.freqai.pipeline import FreqAIPipeline


class FreqAIRetrainer:
    """定时重训器。loader 返回 (df, corr_data) 或仅 df。"""

    def __init__(
        self,
        pipeline: FreqAIPipeline,
        loader: Callable[[], Any],
        interval_hours: float = 6.0,
        name: str = "live",
        keep_history: int = 3,
    ):
        self.pipeline = pipeline
        self.loader = loader
        self.interval_hours = float(interval_hours)
        self.name = name
        self.keep_history = int(keep_history)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self.last_train_at: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.train_count = 0

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    return
            try:
                self.train_now()
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.last_error = str(exc)[:300]
            time.sleep(self.interval_hours * 3600)

    # ------------------------------------------------------------------ #
    def train_now(self) -> dict[str, Any]:
        """立即用最新数据重训：时间戳命名保留历史，并同步一份固定名供推理加载。"""
        import shutil
        import time as _time

        data = self.loader()
        if isinstance(data, tuple):
            df, corr_data = data
        else:
            df, corr_data = data, None
        ts = _time.strftime("%Y%m%d_%H%M%S") + f"_{int(_time.time() * 1000) % 100000:05d}"
        ts_name = f"{self.name}_{ts}"
        info = self.pipeline.train(df, train_ratio=0.85, name=ts_name, corr_data=corr_data)
        # 同步固定名副本（供 predict_latest(name=self.name) 使用）
        fixed_dir = self.pipeline.model_dir / self.name
        if fixed_dir.exists():
            shutil.rmtree(fixed_dir, ignore_errors=True)
        shutil.copytree(self.pipeline.model_dir / ts_name, fixed_dir)
        self._prune_history()
        with self._lock:
            self.last_train_at = datetime.now(timezone.utc).isoformat()
            self.last_result = info
            self.last_error = None
            self.train_count += 1
        return info

    def _prune_history(self) -> None:
        """保留最新 keep_history 个历史模型目录。"""
        import shutil
        from pathlib import Path

        base = self.pipeline.model_dir
        if not base.exists():
            return
        keep = set()
        prefix = self.name + "_"
        folders = sorted(
            [p for p in base.iterdir() if p.is_dir() and p.name.startswith(prefix)],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        for f in folders[: self.keep_history]:
            keep.add(f.name)
        for f in folders:
            if f.name not in keep:
                shutil.rmtree(f, ignore_errors=True)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "interval_hours": self.interval_hours,
                "name": self.name,
                "last_train_at": self.last_train_at,
                "last_error": self.last_error,
                "train_count": self.train_count,
                "last_result": self.last_result,
            }
