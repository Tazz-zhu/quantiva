"""交易记录持久化（SQLite）与统计分析。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TradeStore:
    """保存所有交易（回测/实盘），支持按策略/原因聚合统计。"""

    def __init__(self, db_path: str | Path = "data/evolution.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, source TEXT, strategy TEXT, symbol TEXT, timeframe TEXT,
                side TEXT, entry_time TEXT, entry_price REAL, exit_time TEXT, exit_price REAL,
                quantity REAL, fees REAL, pnl REAL, return_pct REAL, reason TEXT, params TEXT
            )"""
        )
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS iterations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, kind TEXT, strategy TEXT, title TEXT,
                params TEXT, metrics TEXT, conclusion TEXT, experience TEXT
            )"""
        )
        self.conn.commit()

    def save_trades(self, trades: list, source: str, strategy: str, symbol: str, timeframe: str, params: dict | None = None) -> int:
        if not trades:
            return 0
        rows = []
        for t in trades:
            rows.append((
                _now(), source, strategy, symbol, timeframe, t.get("side"),
                t.get("entry_time"), t.get("entry_price"), t.get("exit_time"), t.get("exit_price"),
                t.get("quantity"), t.get("fees"), t.get("pnl"), t.get("return_pct"), t.get("reason"),
                json.dumps(params or {}, ensure_ascii=False),
            ))
        with self._lock:
            self.conn.executemany(
                "INSERT INTO trades (ts, source, strategy, symbol, timeframe, side, entry_time, entry_price, exit_time, exit_price, quantity, fees, pnl, return_pct, reason, params) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            self.conn.commit()
        return len(rows)

    def recent_trades(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT ts, source, strategy, symbol, timeframe, side, entry_time, entry_price, exit_time, exit_price, quantity, fees, pnl, return_pct, reason, params FROM trades ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        cols = ["ts", "source", "strategy", "symbol", "timeframe", "side", "entry_time", "entry_price", "exit_time", "exit_price", "quantity", "fees", "pnl", "return_pct", "reason", "params"]
        return [dict(zip(cols, r)) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(pnl),0), COALESCE(SUM(fees),0) FROM trades").fetchone()
            by_strategy = self.conn.execute(
                "SELECT strategy, COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), SUM(pnl), COALESCE(SUM(fees),0) FROM trades GROUP BY strategy ORDER BY COUNT(*) DESC"
            ).fetchall()
            by_reason = self.conn.execute(
                "SELECT reason, COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), SUM(pnl) FROM trades GROUP BY reason ORDER BY COUNT(*) DESC"
            ).fetchall()
            by_source = self.conn.execute("SELECT source, COUNT(*) FROM trades GROUP BY source").fetchall()
        reason_labels = {"signal": "信号", "stop_loss": "止损", "take_profit": "止盈", "eod": "期末"}
        return {
            "total": {"count": total[0], "total_pnl": round(total[1] or 0, 4), "total_fees": round(total[2] or 0, 4)},
            "by_strategy": [
                {"strategy": r[0], "count": r[1], "wins": r[2], "win_rate": round(r[2] / r[1], 4) if r[1] else 0, "pnl": round(r[3] or 0, 4), "fees": round(r[4] or 0, 4)}
                for r in by_strategy
            ],
            "by_reason": [
                {"reason": reason_labels.get(r[0], r[0]), "count": r[1], "wins": r[2], "win_rate": round(r[2] / r[1], 4) if r[1] else 0, "pnl": round(r[3] or 0, 4)}
                for r in by_reason
            ],
            "by_source": [{"source": r[0], "count": r[1]} for r in by_source],
        }

    def save_iteration(self, kind: str, strategy: str, title: str, params: dict | None = None, metrics: dict | None = None, conclusion: str = "", experience: str = "") -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO iterations (ts, kind, strategy, title, params, metrics, conclusion, experience) VALUES (?,?,?,?,?,?,?,?)",
                (_now(), kind, strategy, title,
                 json.dumps(params or {}, ensure_ascii=False),
                 json.dumps(metrics or {}, ensure_ascii=False, default=str),
                 conclusion, experience),
            )
            self.conn.commit()
            return cur.lastrowid

    def list_iterations(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, ts, kind, strategy, title, params, metrics, conclusion, experience FROM iterations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        cols = ["id", "ts", "kind", "strategy", "title", "params", "metrics", "conclusion", "experience"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                d["params"] = json.loads(d["params"] or "{}")
            except Exception:
                d["params"] = {}
            try:
                d["metrics"] = json.loads(d["metrics"] or "{}")
            except Exception:
                d["metrics"] = {}
            out.append(d)
        return out

    def get_iteration(self, iteration_id: int) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT id, ts, kind, strategy, title, params, metrics, conclusion, experience FROM iterations WHERE id = ?",
                (iteration_id,),
            ).fetchone()
        if not row:
            return None
        cols = ["id", "ts", "kind", "strategy", "title", "params", "metrics", "conclusion", "experience"]
        d = dict(zip(cols, row))
        try:
            d["params"] = json.loads(d["params"] or "{}")
            d["metrics"] = json.loads(d["metrics"] or "{}")
        except Exception:
            pass
        return d

    def append_experience(self, iteration_id: int, text: str) -> None:
        with self._lock:
            cur = self.conn.execute("SELECT experience FROM iterations WHERE id = ?", (iteration_id,)).fetchone()
            if not cur:
                return
            old = cur[0] or ""
            new = (old + "\n" + text).strip()
            self.conn.execute("UPDATE iterations SET experience = ? WHERE id = ?", (new, iteration_id))
            self.conn.commit()

    def generate_conclusion(self, stats: dict) -> str:
        """根据交易统计自动生成经验总结。"""
        lines = []
        total = stats.get("total", {})
        n = total.get("count", 0)
        if n == 0:
            return "暂无交易样本，无法生成经验总结。"
        pnl = total.get("total_pnl", 0)
        fees = total.get("total_fees", 0)
        lines.append("累计 " + str(n) + " 笔交易，净盈亏 " + format(pnl, ",.2f") + " USDT，总手续费 " + format(fees, ",.2f") + " USDT。")
        by_reason = stats.get("by_reason", [])
        if by_reason:
            worst = min(by_reason, key=lambda x: x["pnl"])
            best = max(by_reason, key=lambda x: x["pnl"])
            lines.append("亏损主要来自「" + worst["reason"] + "」（" + str(worst["count"]) + " 笔，合计 " + format(worst["pnl"], ",.2f") + "），收益主要来自「" + best["reason"] + "」（" + format(best["pnl"], ",.2f") + "）。")
            stop = next((x for x in by_reason if x["reason"] == "止损"), None)
            if stop and stop["count"] > 0:
                lines.append("止损占比 " + format(stop["count"] / n * 100, ".1f") + "%（" + str(stop["count"]) + " 笔），若止损过于频繁可考虑放宽入场条件或优化止损距离。")
        by_strategy = stats.get("by_strategy", [])
        if by_strategy:
            top = max(by_strategy, key=lambda x: x["pnl"])
            lines.append("当前表现最好的策略是「" + top["strategy"] + "」（" + str(top["count"]) + " 笔，胜率 " + format(top["win_rate"] * 100, ".1f") + "%，盈亏 " + format(top["pnl"], ",.2f") + "）。")
        return "\n".join(lines)
