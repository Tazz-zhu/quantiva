"""实盘/模拟盘管理器：后台线程运行，支持交易所数据源与离线合成数据源。"""
from __future__ import annotations

import json
import threading
import time
import random
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant.data.fetcher import ExchangeDataFetcher, generate_synthetic_ohlcv, to_pandas_freq
from quant.data.indicators import atr
from quant.execution.ccxt_broker import CCXTBroker
from quant.execution.paper import PaperBroker
from quant.risk.manager import RiskManager
from quant.strategy import create_strategy
from quant.utils.logger import setup_logger

logger = setup_logger("live_web")


def live_session_path(config: dict) -> Path:
    """实盘会话文件路径（重启后用于恢复）。"""
    data_dir = (config or {}).get("system", {}).get("data_dir", "data")
    return Path(data_dir) / "live_session.json"


def load_live_session(config: dict) -> dict | None:
    """读取已保存的实盘会话；不存在或损坏返回 None。"""
    try:
        p = live_session_path(config)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


class SyntheticLiveData:
    """离线模拟行情源：每次轮询在已有数据上追加一根新 K 线（随机游走）。"""

    def __init__(self, symbol: str, timeframe: str, warmup_bars: int = 200, seed: int = 7, base_price: float = 50000.0, days: int = 40):
        self.symbol = symbol
        self.timeframe = timeframe
        self._rng = random.Random(seed)
        df = generate_synthetic_ohlcv(timeframe=timeframe, days=days, seed=seed, base_price=base_price)
        self.df = df.tail(warmup_bars + 5).copy()

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int | None = None):
        freq = pd.tseries.frequencies.to_offset(to_pandas_freq(timeframe))
        last = self.df.iloc[-1]
        new_ts = last.name + freq
        ret = self._rng.gauss(0.0002, 0.004)
        open_ = float(last["close"])
        close = open_ * (1.0 + ret)
        high = max(open_, close) * (1.0 + abs(self._rng.gauss(0.0, 0.0012)))
        low = min(open_, close) * (1.0 - abs(self._rng.gauss(0.0, 0.0012)))
        volume = float(last["volume"]) * (0.8 + 0.4 * self._rng.random())
        row = pd.DataFrame(
            {"open": [open_], "high": [high], "low": [low], "close": [close], "volume": [volume]},
            index=[new_ts],
        )
        self.df = pd.concat([self.df, row]).tail(limit or 2000)
        return self.df


class LiveManager:
    """在后台线程运行交易循环，并向 UI 暴露状态。"""

    def __init__(self, config: dict, notifier=None, trade_store=None):
        self.cfg = config
        self.notifier = notifier
        self.trade_store = trade_store
        self.lock = threading.Lock()
        self.running = False
        self.thread: threading.Thread | None = None
        self.broker = None
        self.strategy = None
        self.risk: RiskManager | None = None
        self.provider = None
        self.symbol = ""
        self.timeframe = "1h"
        self.mode = "paper"
        self.data_source = "synthetic"
        self.poll_interval = 60.0
        self.warmup_bars = 200

        self.events: deque = deque(maxlen=300)
        self.orders: deque = deque(maxlen=300)
        self.signal = 0.0
        self.last_price: float | None = None
        self.last_update: str | None = None
        self.equity: float | None = None
        self.start_time: str | None = None
        self.start_equity: float | None = None
        self.strategy_name = ""
        self.entry_price: float | None = None
        self.entry_side: str | None = None
        self.entry_qty: float | None = None
        self.entry_time = None
        # 日亏损熔断
        self.daily_loss_limit: float | None = None
        self.daily_start_day: str | None = None
        self.daily_realized = 0.0
        self.daily_pnl = 0.0
        self.circuit_breaker_active = False
        self.max_drawdown_pct: float | None = None
        self.peak_equity: float | None = None
        self.drawdown_breaker_active = False

    def _add_event(self, level: str, message: str) -> None:
        self.events.appendleft(
            {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "message": message}
        )
        logger.info("[%s] %s", level, message)

    def start(self, params: dict) -> None:
        with self.lock:
            if self.running:
                raise RuntimeError("交易循环已在运行中")
            self.running = True

        try:
            self.mode = params.get("mode", "paper")
            self.symbol = params.get("symbol", "BTC/USDT")
            self.timeframe = params.get("timeframe", "1h")
            self.data_source = params.get("data_source", "synthetic")
            self.poll_interval = float(params.get("poll_interval_sec", 60))
            self.warmup_bars = int(params.get("warmup_bars", 200))

            strategy_cfg = params.get("strategy") or {"name": "ma_cross", "params": {}}
            self.strategy = create_strategy(strategy_cfg["name"], strategy_cfg.get("params"))
            self.strategy_name = self.strategy.name
            risk_cfg = params.get("risk") or {}
            self.risk = RiskManager.from_config(risk_cfg)
            limit = risk_cfg.get("max_daily_loss_pct") or (self.cfg.get("risk") or {}).get("max_daily_loss_pct")
            self.daily_loss_limit = float(limit) if limit else None
            self.daily_start_day = None
            self.daily_realized = 0.0
            self.daily_pnl = 0.0
            self.circuit_breaker_active = False
            limit_dd = risk_cfg.get("max_drawdown_pct") or (self.cfg.get("risk") or {}).get("max_drawdown_pct")
            self.max_drawdown_pct = float(limit_dd) if limit_dd else None
            self.peak_equity = None
            self.drawdown_breaker_active = False

            if self.mode == "paper":
                self.broker = PaperBroker(
                    initial_balance=float(params.get("paper_initial_balance", 10000)),
                    fee_rate=float(self.cfg["backtest"].get("fee_rate", 0.001)),
                    slippage=float(self.cfg["backtest"].get("slippage", 0.0005)),
                )
            else:
                self.broker = CCXTBroker(
                    self.cfg["exchange"]["id"],
                    sandbox=self.cfg["exchange"].get("sandbox", False),
                )

            if self.data_source == "synthetic" or self.data_source == "auto":
                self.provider = SyntheticLiveData(
                    self.symbol, self.timeframe, self.warmup_bars,
                    seed=int(params.get("seed", 7)),
                )
            else:
                self.provider = ExchangeDataFetcher(
                    self.cfg["exchange"]["id"],
                    self.cfg["exchange"].get("sandbox", False),
                )

            self.events.clear()
            self.orders.clear()
            self.start_time = datetime.now(timezone.utc).isoformat()
            if self.mode == "paper":
                self.start_equity = float(params.get("paper_initial_balance", 10000))
            else:
                # 实盘模式：以真实账户可用权益为基准，避免盈亏百分比失真
                quote = self.cfg.get("data", {}).get("quote", "USDT")
                try:
                    bal = self.broker.get_balance()
                    self.start_equity = float(bal.get(quote, 0.0) or 0.0)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError("读取实盘账户权益失败: " + str(exc)) from exc
                if self.start_equity <= 0:
                    raise RuntimeError("实盘账户可用权益为 0，请检查 API 权限与币种（" + quote + "）")
            self._add_event(
                "info",
                "启动 " + self.mode + " 交易循环 | " + self.symbol + " @ " + self.timeframe + " | "
                + "策略 " + self.strategy_name + " | 数据源 " + self.data_source,
            )
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            self._save_session(params)
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.running = False
            self._add_event("error", "启动失败: " + str(exc))
            raise

    def stop(self) -> None:
        with self.lock:
            if not self.running:
                return
            self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self._add_event("info", "交易循环已停止")
        self._clear_session()

    def _session_payload(self, params: dict) -> dict:
        return {
            "mode": self.mode,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "data_source": self.data_source,
            "poll_interval_sec": self.poll_interval,
            "warmup_bars": self.warmup_bars,
            "paper_initial_balance": float(params.get("paper_initial_balance", 10000)),
            "seed": int(params.get("seed", 7)),
            "strategy": {"name": self.strategy_name, "params": getattr(self.strategy, "params", None) or {}},
            "risk": vars(self.risk) if self.risk else {},
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save_session(self, params: dict) -> None:
        try:
            p = live_session_path(self.cfg)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self._session_payload(params), ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("实盘会话已保存: %s", p)
        except Exception as exc:  # noqa: BLE001
            logger.warning("保存实盘会话失败: %s", exc)

    def _clear_session(self) -> None:
        try:
            p = live_session_path(self.cfg)
            if p.exists():
                p.unlink()
                logger.info("实盘会话已清除")
        except Exception as exc:  # noqa: BLE001
            logger.warning("清除实盘会话失败: %s", exc)

    def _position_qty(self) -> float:
        qty = 0.0
        for pos in self.broker.get_positions():
            if pos.get("symbol") == self.symbol:
                qty += float(pos.get("amount") or 0.0)
        return qty

    def _equity(self, price: float) -> float:
        balance = self.broker.get_balance()
        quote = self.cfg.get("data", {}).get("quote", "USDT")
        cash = float(balance.get(quote, 0.0))
        return cash + self._position_qty() * price

    def _loop(self) -> None:
        while self.running:
            try:
                df = self.provider.fetch_ohlcv(
                    self.symbol, self.timeframe, limit=self.warmup_bars + 5
                )
                if df is None or len(df) < 2:
                    self._add_event("warn", "行情数据不足，等待下一轮")
                    time.sleep(self.poll_interval)
                    continue

                signal = float(self.strategy.generate_signals(df).iloc[-1])
                price = float(df["close"].iloc[-1])
                pos_qty = self._position_qty()
                equity = self._equity(price)
                current_side = 1 if pos_qty > 0 else (-1 if pos_qty < 0 else 0)

                # 实时止损/止盈监控（基于当前 K 线高低点）
                if pos_qty != 0 and self.entry_price is not None and self.entry_side is not None:
                    last = df.iloc[-1]
                    atr_val = float(atr(df, 14).iloc[-1]) if len(df) >= 15 else None
                    stop, target = self.risk.stop_prices(self.entry_side, self.entry_price, atr_val)
                    stop = self.risk.trailing_stop(self.entry_side, self.entry_price, price, atr_val, stop)
                    stop = self.risk.break_even_stop(self.entry_side, self.entry_price, price, atr_val, stop)
                    exit_price: float | None = None
                    reason: str | None = None
                    if self.entry_side == "long":
                        if stop is not None and last["low"] <= stop:
                            exit_price, reason = float(stop), "stop_loss"
                        elif target is not None and last["high"] >= target:
                            exit_price, reason = float(target), "take_profit"
                    else:
                        if stop is not None and last["high"] >= stop:
                            exit_price, reason = float(stop), "stop_loss"
                        elif target is not None and last["low"] <= target:
                            exit_price, reason = float(target), "take_profit"
                    if exit_price is not None:
                        self._close_position(exit_price, reason, equity)
                        pos_qty = 0.0

                # ---------- 日亏损熔断 ----------
                now_dt = datetime.now(timezone.utc)
                day = now_dt.strftime("%Y-%m-%d")
                if day != self.daily_start_day:
                    self.daily_start_day = day
                    self.daily_realized = 0.0
                    self.circuit_breaker_active = False
                    self._add_event("info", "新交易日开始（UTC " + day + "），日盈亏统计已重置")
                unrealized = 0.0
                if pos_qty != 0 and self.entry_price is not None and self.entry_side is not None:
                    if self.entry_side == "long":
                        unrealized = (price - self.entry_price) * abs(pos_qty)
                    else:
                        unrealized = (self.entry_price - price) * abs(pos_qty)
                daily_pnl = self.daily_realized + unrealized
                with self.lock:
                    self.daily_pnl = daily_pnl
                if self.daily_loss_limit and daily_pnl <= -(self.daily_loss_limit * (self.start_equity or equity or 0.0)):
                    if not self.circuit_breaker_active:
                        self.circuit_breaker_active = True
                        self._add_event(
                            "warn",
                            "日亏损熔断触发：今日亏损 " + format(daily_pnl, ".2f")
                            + "（已达 " + format(self.daily_loss_limit * 100, ".1f") + "% 阈值），暂停新开仓并平掉现有持仓",
                        )
                        if self.notifier:
                            try:
                                self.notifier.send_text("⚠️ 日亏损熔断：今日亏损 " + format(daily_pnl, ".2f") + "，Quantiva 已暂停开仓")
                            except Exception:  # noqa: BLE001
                                pass

                # ---------- 组合级回撤熔断 ----------
                if self.peak_equity is None or equity > self.peak_equity:
                    self.peak_equity = equity
                if self.max_drawdown_pct and self.peak_equity and self.peak_equity > 0:
                    dd_now = equity / self.peak_equity - 1.0
                    if dd_now <= -self.max_drawdown_pct:
                        if not self.drawdown_breaker_active:
                            self.drawdown_breaker_active = True
                            self._add_event(
                                "warn",
                                "组合回撤熔断触发：权益从峰值回撤 " + format(dd_now * 100, ".2f")
                                + "%（阈值 " + format(self.max_drawdown_pct * 100, ".1f") + "%），暂停开仓",
                            )
                            if self.notifier:
                                try:
                                    self.notifier.send_text("⚠️ 组合回撤熔断：权益回撤 " + format(dd_now * 100, ".2f") + "%，Quantiva 已暂停开仓")
                                except Exception:  # noqa: BLE001
                                    pass

                direction = self.risk.trade_direction if self.risk else "long_only"
                target = max(0.0, signal) if direction == "long_only" else signal
                target_side = 1 if target > 0 else (-1 if target < 0 else 0)
                if self.circuit_breaker_active or self.drawdown_breaker_active:
                    target_side = 0

                with self.lock:
                    self.signal = signal
                    self.last_price = price
                    self.equity = equity
                    self.last_update = datetime.now(timezone.utc).isoformat()

                if target_side != current_side:
                    if target_side == 0:
                        self._close_position(price, "circuit_breaker" if self.circuit_breaker_active else "signal", equity)
                    else:
                        if pos_qty != 0 and current_side != target_side:
                            self._close_position(price, "reverse", equity)
                        atr_series = atr(df, 14)
                        atr_prev_live = float(atr_series.iloc[-2]) if len(atr_series) >= 16 and pd.notna(atr_series.iloc[-2]) else None
                        sp, _tp = self.risk.stop_prices("long" if target_side > 0 else "short", price, atr_prev_live)
                        stop_pct = abs(price - sp) / price if sp else None
                        qty = self.risk.risk_position_size(equity, price, stop_pct)
                        if qty > 0:
                            order = self.broker.market_order(
                                self.symbol, "buy" if target_side > 0 else "sell",
                                qty, price=price,
                            )
                            side_label = "做多" if target_side > 0 else "做空"
                            self.entry_price = order.avg_price or price
                            self.entry_side = "long" if target_side > 0 else "short"
                            self.entry_qty = qty
                            self.entry_time = datetime.now(timezone.utc)
                            self._add_event(
                                "info",
                                side_label + " " + format(qty, ".6f") + " @ " + format(self.entry_price, ".2f") + " (信号 " + format(signal, "+.0f") + ")",
                            )
                            if self.notifier:
                                self.notifier.send_trade(self.symbol, side_label, self.entry_price, qty, equity)
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001
                self._add_event("error", "循环异常: " + str(exc))
                time.sleep(self.poll_interval)

    def _close_position(self, price: float, reason: str, equity: float) -> None:
        qty = abs(self._position_qty())
        side = self.entry_side
        if qty <= 0 or side is None or self.entry_price is None:
            return
        order = self.broker.market_order(
            self.symbol, "sell" if side == "long" else "buy", qty, price=price
        )
        fill = order.avg_price or price
        fee_rate = float(self.cfg["backtest"].get("fee_rate", 0.001))
        entry_fee = self.entry_price * qty * fee_rate
        exit_fee = fill * qty * fee_rate
        gross = (fill - self.entry_price) * qty if side == "long" else (self.entry_price - fill) * qty
        pnl = gross - entry_fee - exit_fee
        label = {"stop_loss": "止损", "take_profit": "止盈", "reverse": "反向平仓", "signal": "平仓", "circuit_breaker": "熔断平仓", "manual_flatten": "手动平仓"}.get(reason, "平仓")
        self.daily_realized += pnl
        self._add_event(
            "info",
            label + " @ " + format(fill, ".2f") + "（盈亏 " + format(pnl, "+.2f") + "，" + format(pnl / (self.entry_price * qty) * 100, "+.2f") + "%）",
        )
        if self.notifier:
            self.notifier.send_trade(self.symbol, label, fill, qty, equity)
        if self.trade_store:
            trade = {
                "side": side,
                "entry_time": self.entry_time.isoformat() if self.entry_time else None,
                "entry_price": round(self.entry_price, 6),
                "exit_time": datetime.now(timezone.utc).isoformat(),
                "exit_price": round(fill, 6),
                "quantity": round(qty, 8),
                "fees": round(entry_fee + exit_fee, 4),
                "pnl": round(pnl, 4),
                "return_pct": round(pnl / (self.entry_price * qty), 6) if self.entry_price else 0,
                "reason": reason,
            }
            self.trade_store.save_trades([trade], source="live", strategy=self.strategy_name,
                                         symbol=self.symbol, timeframe=self.timeframe, params=None)
        self.entry_price = None
        self.entry_side = None
        self.entry_qty = None
        self.entry_time = None

    def flatten(self) -> dict:
        """一键平仓：市价平掉当前持仓（不停止交易循环）。"""
        with self.lock:
            if not self.running:
                return {"ok": False, "message": "交易循环未运行"}
        try:
            qty = abs(self._position_qty())
            if qty <= 0 or self.entry_side is None or self.entry_price is None:
                return {"ok": False, "message": "当前无持仓，无需平仓"}
            price = self.last_price or 0.0
            if price <= 0:
                return {"ok": False, "message": "暂无最新价格，无法平仓"}
            self._close_position(price, "manual_flatten", self.equity or 0.0)
            return {"ok": True, "message": "已市价平仓"}
        except Exception as exc:  # noqa: BLE001
            self._add_event("error", "一键平仓失败: " + str(exc))
            return {"ok": False, "message": "平仓失败: " + str(exc)}

    def _exec_quality(self) -> dict:
        """聚合执行质量：成交率 / 平均滑点(bps) / 平均延迟(ms) / 拒单数。"""
        try:
            if not self.broker or not hasattr(self.broker, "exec_quality"):
                return {}
            eq = self.broker.exec_quality or {}
            orders = int(eq.get("orders", 0))
            fills = int(eq.get("fills", 0))
            rejects = int(eq.get("rejects", 0))
            return {
                "orders": orders,
                "fills": fills,
                "rejects": rejects,
                "fill_rate": round(fills / orders, 4) if orders else None,
                "avg_slippage_bps": round(eq.get("slippage_bps_sum", 0.0) / fills, 2) if fills else 0.0,
                "avg_latency_ms": round(eq.get("latency_ms_sum", 0.0) / fills, 1) if fills else 0.0,
            }
        except Exception:  # noqa: BLE001
            return {}

    def status(self) -> dict:
        with self.lock:
            positions = []
            try:
                positions = self.broker.get_positions() if self.broker else []
            except Exception:  # noqa: BLE001
                positions = []
            orders = []
            try:
                if self.broker and hasattr(self.broker, "trades"):
                    orders = [
                        {"id": o.id, "side": o.side, "amount": o.amount, "price": o.avg_price, "status": o.status}
                        for o in self.broker.trades[-50:]
                    ]
            except Exception:  # noqa: BLE001
                pass
            return {
                "running": self.running,
                "mode": self.mode,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "data_source": self.data_source,
                "strategy": self.strategy_name,
                "signal": self.signal,
                "last_price": self.last_price,
                "last_update": self.last_update,
                "equity": self.equity,
                "start_equity": self.start_equity,
                "start_time": self.start_time,
                "positions": positions,
                "orders": list(orders),
                "events": list(self.events),
                "poll_interval_sec": self.poll_interval,
                "daily_pnl": self.daily_pnl,
                "daily_loss_limit": self.daily_loss_limit,
                "circuit_breaker_active": self.circuit_breaker_active,
                "max_drawdown_pct": self.max_drawdown_pct,
                "peak_equity": self.peak_equity,
                "drawdown_breaker_active": self.drawdown_breaker_active,
                "exec_quality": self._exec_quality(),
                "entry_price": self.entry_price,
                "entry_side": self.entry_side,
                "entry_qty": self.entry_qty,
                "unrealized_pnl": (round((self.last_price - self.entry_price) * abs(self.entry_qty or self._position_qty()), 2)
                                   if self.entry_side == "long" and self.entry_price is not None and self.last_price
                                   else round((self.entry_price - self.last_price) * abs(self.entry_qty or self._position_qty()), 2)
                                   if self.entry_side == "short" and self.entry_price is not None and self.last_price else None),
            }
