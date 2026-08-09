"""市场监控服务：多币种涨跌 / 成交量异动检测，24 小时常驻运行。

- 支持合成数据（离线演示）与真实交易所两种数据源
- 事件检测：放量、1小时急涨/急跌、24小时大涨/大跌
- 事件持久化到 SQLite（data/monitor.db），重启不丢失
- 异动实时推送到飞书（可选）
"""
from __future__ import annotations

import random
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant.data.fetcher import ExchangeDataFetcher
from quant.utils.logger import setup_logger
from quant.web.live_manager import SyntheticLiveData

logger = setup_logger("monitor")

DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "MATIC/USDT", "LTC/USDT",
    "SHIB/USDT", "UNI/USDT", "ATOM/USDT", "ETC/USDT", "FIL/USDT", "APT/USDT",
    "NEAR/USDT", "OP/USDT", "ARB/USDT", "SUI/USDT", "INJ/USDT", "TIA/USDT",
    "SEI/USDT", "WLD/USDT", "PEPE/USDT", "BONK/USDT", "TRX/USDT", "TON/USDT",
    "HBAR/USDT", "ALGO/USDT",
]
BASE_PRICES = {
    "BTC/USDT": 65000.0, "ETH/USDT": 3500.0, "SOL/USDT": 160.0, "BNB/USDT": 590.0,
    "XRP/USDT": 0.55, "DOGE/USDT": 0.13, "ADA/USDT": 0.45, "AVAX/USDT": 28.0,
    "LINK/USDT": 14.0, "DOT/USDT": 6.0, "MATIC/USDT": 0.7, "LTC/USDT": 70.0,
    "SHIB/USDT": 0.000018, "UNI/USDT": 8.0, "ATOM/USDT": 8.5, "ETC/USDT": 22.0,
    "FIL/USDT": 5.0, "APT/USDT": 8.0, "NEAR/USDT": 5.0, "OP/USDT": 1.8,
    "ARB/USDT": 1.0, "SUI/USDT": 1.2, "INJ/USDT": 20.0, "TIA/USDT": 7.0,
    "SEI/USDT": 0.4, "WLD/USDT": 2.5, "PEPE/USDT": 0.000011, "BONK/USDT": 0.000026,
    "TRX/USDT": 0.12, "TON/USDT": 5.5, "HBAR/USDT": 0.08, "ALGO/USDT": 0.2,
}

EVENT_TYPES = {
    "volume_surge": "放量异动",
    "price_surge_1h": "1小时急涨",
    "price_drop_1h": "1小时急跌",
    "price_surge_24h": "24小时大涨",
    "price_drop_24h": "24小时大跌",
    "vol_spike": "波动率突增",
}


class MarketSyntheticSource:
    """多币种合成行情源：按概率注入放量 / 跳价异动，模拟真实市场。"""

    def __init__(self, symbols: list[str], seed: int = 7, warmup_bars: int = 1500):
        self.symbols = symbols
        self._rng = random.Random(seed)
        self.providers = {}
        for i, sym in enumerate(symbols):
            self.providers[sym] = SyntheticLiveData(
                sym, "1m", warmup_bars=warmup_bars, seed=seed + i * 13,
                base_price=BASE_PRICES.get(sym, 100.0), days=3,
            )

    def next_bars(self) -> dict[str, pd.DataFrame]:
        out = {}
        for sym, prov in self.providers.items():
            df = prov.fetch_ohlcv(sym, "1m", limit=2000)
            if self._rng.random() < 0.04:
                shock = self._rng.random()
                last_idx = df.index[-1]
                if shock < 0.55:
                    df.loc[last_idx, "volume"] = df.loc[last_idx, "volume"] * self._rng.uniform(3.0, 8.0)
                elif shock < 0.8:
                    m = 1.0 + self._rng.uniform(0.012, 0.045)
                    df.loc[last_idx, "close"] *= m
                    df.loc[last_idx, "high"] = max(df.loc[last_idx, "high"] * 1.001, df.loc[last_idx, "close"])
                else:
                    m = 1.0 - self._rng.uniform(0.012, 0.045)
                    df.loc[last_idx, "close"] *= m
                    df.loc[last_idx, "low"] = min(df.loc[last_idx, "low"] * 0.999, df.loc[last_idx, "close"])
            out[sym] = df
        return out


class MarketMonitor:
    def __init__(self, config: dict, db_path: str | Path = "data/monitor.db", notifier=None):
        self.cfg = config
        mon_cfg = config.get("monitor") or {}
        self.symbols = mon_cfg.get("symbols") or DEFAULT_SYMBOLS
        self.interval = float(mon_cfg.get("interval_sec", 30))
        self.source_type = mon_cfg.get("source", "synthetic")
        th = mon_cfg.get("thresholds") or {}
        self.thresholds = {
            "volume_ratio": float(th.get("volume_ratio", 3.0)),
            "price_1h": float(th.get("price_1h", 0.025)),
            "price_24h": float(th.get("price_24h", 0.08)),
            "alert_cooldown_min": float(th.get("alert_cooldown_min", 15)),
            "vol_spike_ratio": float(th.get("vol_spike_ratio", 2.0)),
        }
        self.notifier = notifier
        self.running = False
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.markets: dict[str, dict] = {}
        self.events: deque = deque(maxlen=500)
        self.scan_count = 0
        self.last_scan: str | None = None
        self.started_at: str | None = None
        self.source_error: str | None = None
        self._last_alert: dict[tuple[str, str], float] = {}
        self._source = MarketSyntheticSource(self.symbols) if self.source_type == "synthetic" else None
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.Lock()
        self.conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS monitor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, symbol TEXT, type TEXT, title TEXT,
                detail TEXT, price REAL, change REAL
            )"""
        )
        self.conn.commit()

    def start(self) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("市场监控启动: %d 个标的, 间隔 %.0fs, 数据源 %s", len(self.symbols), self.interval, self.source_type)

    def stop(self) -> None:
        with self.lock:
            if not self.running:
                return
            self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("市场监控已停止")

    def _loop(self) -> None:
        while self.running:
            try:
                self._scan()
            except Exception as exc:  # noqa: BLE001
                self.source_error = str(exc)[:200]
                logger.exception("监控扫描异常: %s", exc)
            time.sleep(self.interval)

    def _scan(self) -> None:
        if self._source is not None:
            bars_map = self._source.next_bars()
        else:
            bars_map = self._fetch_exchange()
        self.source_error = None
        for sym, df in bars_map.items():
            self._process_symbol(sym, df)
        self.scan_count += 1
        self.last_scan = datetime.now(timezone.utc).isoformat()

    def _fetch_exchange(self) -> dict[str, pd.DataFrame]:
        fetcher = ExchangeDataFetcher(self.cfg["exchange"]["id"])
        out = {}
        for sym in self.symbols:
            try:
                out[sym] = fetcher.fetch_ohlcv(sym, "1m", limit=1500)
            except Exception as exc:  # noqa: BLE001
                logger.warning("获取 %s 失败: %s", sym, exc)
        if not out:
            raise RuntimeError("交易所行情获取失败")
        return out

    def _process_symbol(self, sym: str, df: pd.DataFrame) -> None:
        if len(df) < 62:
            return
        close = float(df["close"].iloc[-1])
        change_1h = float(close / df["close"].iloc[-61] - 1.0)
        change_24h = float(close / df["close"].iloc[-1441] - 1.0) if len(df) >= 1441 else None
        vol_now = float(df["volume"].iloc[-1])
        vol_mean = float(df["volume"].iloc[-61:-1].mean())
        vol_ratio = vol_now / vol_mean if vol_mean > 0 else None
        vol_mean_24 = float(df["volume"].iloc[-1441:-1].mean()) if len(df) >= 1441 else vol_mean
        volume_24h = vol_mean_24 * 1440.0

        market = {
            "symbol": sym,
            "price": round(close, 6),
            "change_1h": round(change_1h, 5),
            "change_24h": round(change_24h, 5) if change_24h is not None else None,
            "volume": round(vol_now, 2),
            "volume_24h": round(volume_24h, 2),
            "volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.lock:
            self.markets[sym] = market

        alerts = []
        if vol_ratio is not None and vol_ratio >= self.thresholds["volume_ratio"]:
            alerts.append(("volume_surge", "成交量达 24h 均量的 " + format(vol_ratio, ".1f") + " 倍"))
        if change_1h >= self.thresholds["price_1h"]:
            alerts.append(("price_surge_1h", "1 小时上涨 " + format(change_1h * 100, ".2f") + "%"))
        if change_1h <= -self.thresholds["price_1h"]:
            alerts.append(("price_drop_1h", "1 小时下跌 " + format(abs(change_1h) * 100, ".2f") + "%"))
        if change_24h is not None and change_24h >= self.thresholds["price_24h"]:
            alerts.append(("price_surge_24h", "24 小时上涨 " + format(change_24h * 100, ".2f") + "%"))
        if change_24h is not None and change_24h <= -self.thresholds["price_24h"]:
            alerts.append(("price_drop_24h", "24 小时下跌 " + format(abs(change_24h) * 100, ".2f") + "%"))
        if len(df) >= 1441:
            rets1h = df["close"].pct_change().tail(61).dropna()
            rets24 = df["close"].pct_change().tail(1441).dropna()
            vol1h = float(rets1h.std())
            vol24 = float(rets24.std())
            if vol24 > 0 and vol1h >= vol24 * self.thresholds["vol_spike_ratio"]:
                alerts.append(("vol_spike", "1h 波动率达 24h 均值的 " + format(vol1h / vol24, ".1f") + " 倍"))

        now = time.time()
        for atype, detail in alerts:
            last = self._last_alert.get((sym, atype), 0.0)
            if now - last < self.thresholds["alert_cooldown_min"] * 60:
                continue
            self._last_alert[(sym, atype)] = now
            self._record_event(sym, atype, detail, close, change_1h)
            if self.notifier:
                self.notifier.send_alert(sym, atype, EVENT_TYPES[atype], detail, close)

    def _record_event(self, sym: str, atype: str, detail: str, price: float, change: float) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": sym,
            "type": atype,
            "title": EVENT_TYPES.get(atype, atype),
            "detail": detail,
            "price": round(price, 6),
            "change": round(change, 5),
        }
        with self.lock:
            self.events.appendleft(event)
        try:
            with self._db_lock:
                self.conn.execute(
                    "INSERT INTO monitor_events (ts, symbol, type, title, detail, price, change) VALUES (?,?,?,?,?,?,?)",
                    (event["ts"], sym, atype, event["title"], detail, event["price"], event["change"]),
                )
                self.conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("事件落库失败: %s", exc)

    def status(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "symbols": self.symbols,
                "interval_sec": self.interval,
                "source": self.source_type,
                "scan_count": self.scan_count,
                "last_scan": self.last_scan,
                "started_at": self.started_at,
                "source_error": self.source_error,
                "thresholds": self.thresholds,
                "markets": list(self.markets.values()),
                "events": list(self.events)[:100],
            }

    def get_events(self, limit: int = 100, offset: int = 0, type: str | None = None, symbol: str | None = None) -> list[dict]:
        where, params = [], []
        if type:
            where.append("type = ?")
            params.append(type)
        if symbol:
            where.append("symbol = ?")
            params.append(symbol)
        sql = "SELECT ts, symbol, type, title, detail, price, change FROM monitor_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._db_lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [
            {"ts": r[0], "symbol": r[1], "type": r[2], "title": r[3], "detail": r[4], "price": r[5], "change": r[6]}
            for r in rows
        ]

    def update_config(self, patch: dict) -> None:
        if "interval_sec" in patch:
            self.interval = float(patch["interval_sec"])
        th = patch.get("thresholds")
        if th:
            for k, v in th.items():
                if k in self.thresholds:
                    self.thresholds[k] = float(v)

    def rankings(self) -> dict:
        with self.lock:
            markets = list(self.markets.values())
        valid = [m for m in markets if m.get("change_24h") is not None]
        by_vol = sorted(markets, key=lambda m: m.get("volume_24h") or 0, reverse=True)[:10]
        by_gain = sorted(valid, key=lambda m: m["change_24h"], reverse=True)[:10]
        by_drop = sorted(valid, key=lambda m: m["change_24h"])[:10]

        def slim(m):
            return {
                "symbol": m["symbol"], "price": m["price"],
                "change_1h": m.get("change_1h"), "change_24h": m.get("change_24h"),
                "volume_24h": m.get("volume_24h"), "volume_ratio": m.get("volume_ratio"),
            }

        return {
            "volume_top10": [slim(m) for m in by_vol],
            "gain_top10": [slim(m) for m in by_gain],
            "drop_top10": [slim(m) for m in by_drop],
            "updated_at": self.last_scan,
        }
