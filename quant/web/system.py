"""????????????????????"""
from __future__ import annotations

import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from quant import __version__
from quant.utils.logger import setup_logger

logger = setup_logger("system")

DB_FILES = ["ohlcv.db", "evolution.db", "monitor.db"]


class SystemService:
    def __init__(self, config: dict):
        self.config = config
        self.started_at = time.time()
        sys_cfg = config.get("system", {})
        self.data_dir = Path(sys_cfg.get("data_dir", "data"))
        self.log_dir = Path(sys_cfg.get("log_dir", "data/logs"))
        self.backup_cfg = sys_cfg.get("backup", {}) or {}
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._backup_thread: threading.Thread | None = None
        self._backup_running = False
        self.last_backup: str | None = None
        self.backup_count = 0

    # ---------------- ?? ---------------- #
    def _db_size(self, name: str) -> int | None:
        p = self.data_dir / name
        return p.stat().st_size if p.exists() else None

    def status(self) -> dict:
        uptime = time.time() - self.started_at
        dbs = {}
        for name in DB_FILES:
            size = self._db_size(name)
            if size is not None:
                dbs[name] = size
        log_size = 0
        for f in self.log_dir.glob("*.log*"):
            log_size += f.stat().st_size
        return {
            "version": __version__,
            "uptime_seconds": round(uptime, 1),
            "started_at": datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat(),
            "dbs": dbs,
            "log_size": log_size,
            "backup_dir": str(self.backup_dir),
            "last_backup": self.last_backup,
            "backup_count": self.backup_count,
        }

    # ---------------- ?? ---------------- #
    def backup_now(self) -> dict:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = self.backup_dir / f"backup_{ts}"
        dest.mkdir(parents=True, exist_ok=True)
        saved = []
        for name in DB_FILES:
            src = self.data_dir / name
            if src.exists():
                target = dest / name
                shutil.copy2(str(src), str(target))
                saved.append(name)
        self.last_backup = ts
        self.backup_count += 1
        self._cleanup_old()
        logger.info("????: %s (%s)", dest, ", ".join(saved))
        return {"ok": True, "dir": str(dest), "files": saved, "count": self.backup_count}

    def _cleanup_old(self) -> None:
        keep = int(self.backup_cfg.get("keep", 7))
        dirs = sorted([d for d in self.backup_dir.iterdir() if d.is_dir() and d.name.startswith("backup_")], reverse=True)
        for d in dirs[keep:]:
            shutil.rmtree(str(d), ignore_errors=True)
            logger.info("?????: %s", d.name)

    def start_auto_backup(self) -> None:
        if self._backup_running:
            return
        if not self.backup_cfg.get("enabled", True):
            return
        self._backup_running = True
        interval = float(self.backup_cfg.get("interval_hours", 24)) * 3600
        self._backup_thread = threading.Thread(target=self._backup_loop, args=(interval,), daemon=True)
        self._backup_thread.start()
        logger.info("????????? %.0f ???", interval / 3600)

    def _backup_loop(self, interval: float) -> None:
        # ????????????????
        try:
            self.backup_now()
        except Exception as exc:  # noqa: BLE001
            logger.warning("??????: %s", exc)
        while self._backup_running:
            time.sleep(interval)
            try:
                self.backup_now()
            except Exception as exc:  # noqa: BLE001
                logger.warning("??????: %s", exc)
