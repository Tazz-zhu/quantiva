"""回测结果缓存（freqtrade backtest_caching 移植）。

相同策略参数 + 相同数据范围（指纹）的回测直接复用上次结果，避免重复计算。
缓存键 = SHA256(策略名 + 参数 + 风控 + 回测参数 + 数据指纹)。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant.backtest.engine import BacktestResult, Trade


def _data_fingerprint(df: pd.DataFrame) -> str:
    """对数据首尾与关键列做摘要指纹（避免存储全量数据）。"""
    if len(df) == 0:
        return "empty"
    head = df.iloc[0][["open", "high", "low", "close", "volume"]].round(8).tolist()
    tail = df.iloc[-1][["open", "high", "low", "close", "volume"]].round(8).tolist()
    n = len(df)
    mid = df.iloc[n // 2][["open", "high", "low", "close", "volume"]].round(8).tolist()
    return hashlib.sha256(
        json.dumps([str(df.index[0]), str(df.index[-1]), n, head, mid, tail], default=str).encode()
    ).hexdigest()[:16]


def cache_key(strategy_name: str, params: dict, risk_cfg: dict, bt_cfg: dict, symbol: str, df: pd.DataFrame) -> str:
    payload = {
        "strategy": strategy_name,
        "params": params,
        "risk": risk_cfg,
        "bt": bt_cfg,
        "symbol": symbol,
        "data": _data_fingerprint(df),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


class BacktestCache:
    """文件型回测缓存（目录 data/backtest_cache/）。"""

    def __init__(self, cache_dir: str = "data/backtest_cache"):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> BacktestResult | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            equity = pd.Series(obj["equity"], index=pd.to_datetime(obj["equity_index"]), dtype=float)
            positions = pd.Series(obj["positions"], index=pd.to_datetime(obj["equity_index"]), dtype=float)
            trades = [Trade(**t) for t in obj["trades"]]
            data = pd.DataFrame(obj["data"])
            if "index" in data.columns:
                data["index"] = pd.to_datetime(data["index"])
                data = data.set_index("index")
            return BacktestResult(
                equity_curve=equity, trades=trades, metrics=obj.get("metrics", {}),
                positions=positions, data=data,
                breakdown=obj.get("breakdown", {}),
                trade_stats=obj.get("trade_stats", {}),
            )
        except Exception:  # noqa: BLE001
            return None

    def put(self, key: str, result: BacktestResult) -> None:
        obj = {
            "equity": result.equity_curve.astype(float).tolist(),
            "equity_index": [str(ts) for ts in result.equity_curve.index],
            "positions": result.positions.astype(float).tolist(),
            "trades": [
                {
                    "symbol": t.symbol, "side": t.side,
                    "entry_time": str(t.entry_time), "entry_price": float(t.entry_price),
                    "exit_time": str(t.exit_time), "exit_price": float(t.exit_price),
                    "quantity": float(t.quantity), "fees": float(t.fees),
                    "pnl": float(t.pnl), "return_pct": float(t.return_pct),
                    "reason": t.reason, "initial_risk": float(t.initial_risk),
                }
                for t in result.trades
            ],
            "metrics": {k: (v if isinstance(v, (int, float, str, type(None), bool)) else v)
                        for k, v in result.metrics.items()},
            "breakdown": result.breakdown,
            "trade_stats": result.trade_stats,
            "data": result.data[["open", "high", "low", "close", "volume"]].astype(float).reset_index().to_dict(orient="records"),
        }
        self._path(key).write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")

    def clear(self) -> int:
        n = 0
        for p in self.dir.glob("*.json"):
            p.unlink()
            n += 1
        return n


