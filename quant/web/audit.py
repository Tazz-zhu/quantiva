"""操作审计日志：记录登录、配置、交易、备份等敏感操作，SQLite 持久化。"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SENSITIVE_GET = {"/api/config", "/api/system/status", "/api/audit/logs"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLogger:
    """审计日志存储（追加写入，不提供删除接口）。"""

    def __init__(self, db_path: str | Path = "data/audit.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, username TEXT, action TEXT, method TEXT,
                path TEXT, detail TEXT, ip TEXT, status INTEGER
            )"""
        )
        self.conn.commit()

    def log(self, username: str, action: str, method: str, path: str,
            detail: str = "", ip: str = "", status: int = 200) -> None:
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO audit_log (ts, username, action, method, path, detail, ip, status) VALUES (?,?,?,?,?,?,?,?)",
                    (_now(), username or "-", action, method, path, detail[:500], ip or "-", status),
                )
                self.conn.commit()
        except Exception:  # noqa: BLE001
            pass  # 审计失败不阻断业务

    def list_logs(self, limit: int = 200, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, ts, username, action, method, path, detail, ip, status FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        cols = ["id", "ts", "username", "action", "method", "path", "detail", "ip", "status"]
        return [dict(zip(cols, r)) for r in rows]

    def status(self) -> dict:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*), MAX(ts) FROM audit_log").fetchone()
        return {"count": row[0], "last": row[1]}

    def action_label(self, path: str, method: str) -> str:
        """根据路径生成动作标签。"""
        mapping = [
            ("/api/auth/login", "登录"), ("/api/auth/logout", "登出"),
            ("/api/auth/change-password", "修改密码"), ("/api/config", "修改配置"),
            ("/api/backtest/run", "运行回测"), ("/api/live/start", "启动实盘"),
            ("/api/live/stop", "停止实盘"), ("/api/evolution/optimize", "参数优化"),
            ("/api/evolution/analyze", "交易分析"), ("/api/system/backup", "数据备份"),
            ("/api/data/fetch", "抓取数据"), ("/api/ai/advice", "AI 分析"),
            ("/api/notify/test", "飞书测试"), ("/api/exchange/test", "交易所测试"),
            ("/api/monitor/start", "启动监控"), ("/api/monitor/stop", "停止监控"),
            ("/api/monitor/config", "修改监控配置"),
        ]
        for p, label in mapping:
            if path.startswith(p):
                return label
        return "API 操作"
