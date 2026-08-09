"""FastAPI Web 服务：行情、回测、实盘、监控、进化、审计、配置等 API。"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:  # noqa: BLE001
    pass

import ccxt
import pandas as pd
import yaml
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from quant.config import exchange_proxy, load_config
from quant.data.fetcher import ExchangeDataFetcher, TIMEFRAME_NANOS, generate_synthetic_ohlcv, to_pandas_freq
from quant.data.indicators import bollinger, macd, rsi, sma
from quant.data.storage import SQLiteStorage
from quant.report.html_report import generate_html_report
from quant.strategy import STRATEGIES
from quant.strategy.code_strategy import CODE_DOC, DEFAULT_CODE
from quant.strategy.custom_rules import DEFAULT_PARAMS, INDICATOR_LABELS, OPS
from quant.strategy.library import SCHOOL_ICONS, get_library
from quant.utils.logger import setup_file_logging
from quant.web.audit import SENSITIVE_GET
from quant.web.auth import PUBLIC_PATHS, AuthManager, hash_password, verify_password
from quant.web.live_manager import LiveManager, live_session_path, load_live_session
from quant.web.state import AppState

logger = setup_file_logging  # noqa: F841  (统一在 create_app 中配置)

ROOT = Path(__file__).resolve().parents[2]
WEBUI_DIR = ROOT / "webui"
CONFIG_PATH = ROOT / "config" / "config.yaml"

state = AppState(CONFIG_PATH)

APP_VERSION = "1.4.0"

_ticker_cache: dict = {"ts": 0.0, "data": {}}
_account_cache: dict = {"ts": 0.0, "data": None}

# 登录防爆破：按 用户名|IP 记录失败次数，5 次失败锁定 15 分钟
MAX_LOGIN_FAILS = 5
LOGIN_LOCK_MINUTES = 15
_login_attempts: dict[str, dict] = {}


def _login_lock_key(username: str, request: Request | None) -> str:
    ip = request.client.host if request and request.client else "-"
    return username + "|" + ip


def _check_login_lock(key: str) -> None:
    rec = _login_attempts.get(key)
    if not rec or not rec.get("locked_until"):
        return
    if time.time() < rec["locked_until"]:
        remain = int((rec["locked_until"] - time.time()) / 60) + 1
        raise HTTPException(status_code=403, detail="尝试次数过多，已锁定 " + str(remain) + " 分钟，请稍后再试")
    _login_attempts.pop(key, None)


def _fetch_account() -> dict:
    """读取交易所真实账户：余额 / 持仓 / USD 估值（密钥来自 .env 或环境变量）。"""
    try:
        key = os.getenv("CCXT_API_KEY") or ""
        secret = os.getenv("CCXT_API_SECRET") or ""
        passphrase = os.getenv("CCXT_API_PASSPHRASE") or os.getenv("CCXT_PASSWORD") or ""
        if not key or not secret:
            return {"ok": False, "reason": "no_keys", "message": "未配置交易所密钥（请写入项目根目录 .env）"}
        proxy = exchange_proxy(state.config)
        params = {
            "apiKey": key,
            "secret": secret,
            "enableRateLimit": True,
            "timeout": 12000,
            "sandbox": bool(state.config.get("exchange", {}).get("sandbox", False)),
        }
        if passphrase:
            params["password"] = passphrase
        if proxy:
            params["proxies"] = {"http": proxy, "https": proxy}
        ex = getattr(ccxt, state.config["exchange"]["id"])(params)
        bal = ex.fetch_balance()
        totals = {k: float(v) for k, v in (bal.get("total") or {}).items() if v}
        free = {k: float(v) for k, v in (bal.get("free") or {}).items() if v}
        usdt = float(totals.get("USDT", 0) or 0)
        estimate = usdt
        coins = []
        for sym, amount in totals.items():
            if sym == "USDT":
                continue
            try:
                t = ex.fetch_ticker(sym + "/USDT")
                px = float(t.get("last") or 0)
                estimate += px * amount
                coins.append({"coin": sym, "amount": round(amount, 8), "price": px, "value_usd": round(px * amount, 2)})
            except Exception:  # noqa: BLE001
                coins.append({"coin": sym, "amount": round(amount, 8), "price": None, "value_usd": None})
        positions = []
        try:
            for p in (ex.fetch_positions() or []):
                sym = p.get("symbol")
                if not sym:
                    continue
                positions.append({
                    "symbol": sym,
                    "side": p.get("side"),
                    "contracts": p.get("contracts"),
                    "notional": p.get("notional"),
                    "entry_price": p.get("entryPrice"),
                    "mark_price": p.get("markPrice"),
                    "unrealized_pnl": p.get("unrealizedPnl"),
                })
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True,
            "exchange": state.config["exchange"]["id"],
            "sandbox": bool(state.config.get("exchange", {}).get("sandbox", False)),
            "total_usdt": round(estimate, 2),
            "free_usdt": round(float(free.get("USDT", 0) or 0), 2),
            "balances": coins,
            "positions": positions,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "error", "message": str(exc)[:200]}


def _masked(value: str) -> bool:
    return value.endswith("***")


def _unmask(merged: dict, old: dict) -> dict:
    """前端传回的脱敏字段（***）不覆盖原值。"""
    for key in ("webhook", "secret", "api_key", "password_hash"):
        if isinstance(merged.get(key), str) and _masked(merged[key]) and isinstance(old.get(key), str):
            merged[key] = old[key]
    return merged


def _save_config(cfg: dict) -> dict:
    """合并默认值后写回 config.yaml。"""
    base = load_config(CONFIG_PATH)

    def merge(a: dict, b: dict) -> dict:
        out = dict(a)
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = merge(out[k], v)
            else:
                out[k] = v
        return out

    merged = _unmask(merge(base, cfg), base)
    CONFIG_PATH.write_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    state.config = merged
    state.reload_services()
    return merged


def _mask_config(cfg: dict) -> dict:
    """敏感字段脱敏后再返回前端。"""
    import copy

    out = copy.deepcopy(cfg)
    try:
        fs = out["notify"]["feishu"]
        if fs.get("webhook"):
            fs["webhook"] = fs["webhook"][:24] + "***"
        if fs.get("secret"):
            fs["secret"] = "***"
    except Exception:  # noqa: BLE001
        pass
    try:
        if out["ai"].get("api_key"):
            out["ai"]["api_key"] = "***"
    except Exception:  # noqa: BLE001
        pass
    try:
        auth = out["auth"]
        auth.pop("password", None)
        if auth.get("password_hash"):
            auth["password_hash"] = "***"
    except Exception:  # noqa: BLE001
        pass
    return out


def _compute_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    mid, upper, lower = bollinger(close, 20, 2.0)
    dif, dea, hist = macd(close, 12, 26, 9)
    return {
        "sma20": sma(close, 20),
        "sma50": sma(close, 50),
        "boll_upper": upper,
        "boll_mid": mid,
        "boll_lower": lower,
        "rsi14": rsi(close, 14),
        "macd_dif": dif,
        "macd_dea": dea,
        "macd_hist": hist,
    }


def _bars_payload(df: pd.DataFrame, symbol: str, timeframe: str, source: str) -> dict:
    inds = _compute_indicators(df)
    bars = [
        {
            "time": int(ts.timestamp() * 1000),
            "open": round(float(r["open"]), 6),
            "high": round(float(r["high"]), 6),
            "low": round(float(r["low"]), 6),
            "close": round(float(r["close"]), 6),
            "volume": round(float(r["volume"]), 4),
        }
        for ts, r in df.iterrows()
    ]
    indicators = {}
    for name, series in inds.items():
        indicators[name] = [None if pd.isna(v) else round(float(v), 6) for v in series]
    return {"symbol": symbol, "timeframe": timeframe, "source": source, "bars": bars, "indicators": indicators}


def _load_ohlcv(symbol: str, timeframe: str, limit: int, source: str) -> tuple[pd.DataFrame, str]:
    freq_sec = pd.tseries.frequencies.to_offset(to_pandas_freq(timeframe)).nanos / 1e9
    days = max(30, int(limit * freq_sec / 86400 * 1.6))
    if source == "synthetic":
        return generate_synthetic_ohlcv(timeframe=timeframe, days=days).tail(limit), "synthetic"
    storage = SQLiteStorage(state.config["data"]["storage_db"])
    df = storage.load_ohlcv(symbol, timeframe)
    storage.close()
    if source == "db":
        if df.empty:
            raise HTTPException(status_code=404, detail="本地数据库没有 " + symbol + " " + timeframe + " 数据")
        return df.tail(limit), "db"
    if len(df) >= min(limit, 300):
        return df.tail(limit), "db"
    try:
        fetcher = ExchangeDataFetcher(state.config["exchange"]["id"], proxy=exchange_proxy(state.config))
        df = fetcher.fetch_ohlcv_paginated(symbol, timeframe, days=days)
        storage = SQLiteStorage(state.config["data"]["storage_db"])
        storage.save_ohlcv(symbol, timeframe, df)
        storage.close()
        return df.tail(limit), "exchange"
    except Exception as exc:  # noqa: BLE001
        if source == "exchange":
            raise HTTPException(status_code=502, detail="交易所数据获取失败: " + str(exc)) from exc
        return generate_synthetic_ohlcv(timeframe=timeframe, days=days).tail(limit), "synthetic-fallback"


def _fetch_tickers(symbols: list[str], exchange_id: str) -> dict:
    proxy = exchange_proxy(state.config)

    def one(sym: str) -> tuple[str, dict]:
        try:
            t_params = {"enableRateLimit": True, "timeout": 4000}
            if proxy:
                t_params["proxies"] = {"http": proxy, "https": proxy}
            ex = getattr(ccxt, exchange_id)(t_params)
            t = ex.fetch_ticker(sym)
            return sym, {"ok": True, "last": t.get("last"), "bid": t.get("bid"), "ask": t.get("ask"), "change_pct": t.get("percentage")}
        except Exception as exc:  # noqa: BLE001
            return sym, {"ok": False, "error": str(exc)[:80]}

    result: dict = {}
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as pool:
        futures = {pool.submit(one, s): s for s in symbols}
        for fut in as_completed(futures, timeout=30):
            sym, data = fut.result()
            result[sym] = data
    return result


def _build_ai_context(payload: dict) -> dict:
    m = payload.get("metrics") or {}
    a = payload.get("analysis") or {}
    tr = a.get("trades") or {}
    return {
        "strategy": payload.get("strategy"),
        "strategy_params": payload.get("strategy_params"),
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "total_return": m.get("total_return"),
        "annual_return": m.get("annual_return"),
        "buy_hold_return": m.get("buy_hold_return"),
        "sharpe": m.get("sharpe"),
        "sortino": m.get("sortino"),
        "calmar": a.get("performance", {}).get("calmar"),
        "max_drawdown": m.get("max_drawdown"),
        "volatility": m.get("volatility"),
        "exposure": m.get("exposure"),
        "num_trades": m.get("num_trades"),
        "win_rate": m.get("win_rate"),
        "profit_factor": m.get("profit_factor"),
        "avg_win": m.get("avg_win"),
        "avg_loss": m.get("avg_loss"),
        "avg_holding_hours": m.get("avg_holding_hours"),
        "max_win_streak": tr.get("streaks", {}).get("max_consecutive_wins"),
        "max_loss_streak": tr.get("streaks", {}).get("max_consecutive_losses"),
        "exit_reasons": {k: v.get("count") for k, v in (tr.get("by_reason") or {}).items()},
        "num_drawdowns": a.get("drawdown", {}).get("num_drawdowns"),
        "longest_dd_days": a.get("drawdown", {}).get("longest_drawdown_days"),
        "market_summary": _market_summary(),
    }


def _market_summary() -> str:
    try:
        markets = state.monitor.status().get("markets", [])
        if not markets:
            return "暂无市场快照"
        parts = []
        for x in markets[:8]:
            c1 = x.get("change_1h")
            parts.append(x["symbol"] + " " + str(x["price"]) + " (1h " + format(c1 * 100, "+.2f") + "%)" if c1 is not None else x["symbol"] + " " + str(x["price"]))
        return "；".join(parts)
    except Exception:  # noqa: BLE001
        return "无市场数据"


def create_app() -> FastAPI:
    app = FastAPI(title="Crypto Quant Console", version="1.0.0")
    app.mount("/static", StaticFiles(directory=str(WEBUI_DIR / "static")), name="static")

    sys_cfg = state.config.get("system", {})
    setup_file_logging(sys_cfg.get("log_dir", "data/logs"))

    @app.middleware("http")
    async def auth_middleware(request, call_next):
        path = request.url.path
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        username = None
        if path.startswith("/api/") and path not in PUBLIC_PATHS:
            auth_cfg = state.config.get("auth", {})
            if auth_cfg.get("enabled", True):
                if not token or not state.auth.validate(token):
                    return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期"})
            username = state.auth.username(token) if token else None
        response = await call_next(request)
        if path.startswith("/api/") and path not in PUBLIC_PATHS and (
            request.method in ("POST", "PUT", "DELETE") or path in SENSITIVE_GET
        ):
            ip = request.client.host if request.client else "-"
            action = state.audit.action_label(path, request.method)
            state.audit.log(username or "system", action, request.method, path,
                            detail=request.url.query[:200], ip=ip, status=response.status_code)
        return response

    # ---------------- 基础 ----------------
    @app.get("/")
    def index():
        return FileResponse(str(WEBUI_DIR / "index.html"))

    @app.get("/api/health")
    def health():
        return {"ok": True, "time": time.time(), "version": APP_VERSION}

    @app.get("/api/strategies")
    def list_strategies():
        return [{"name": name, "defaults": _strategy_defaults(name)} for name in STRATEGIES]

    def _strategy_defaults(name: str):
        defaults = {
            "ma_cross": {"fast": 20, "slow": 50, "direction": "long_only"},
            "rsi_reversion": {"period": 14, "oversold": 30, "overbought": 70},
            "bollinger": {"period": 20, "num_std": 2.0},
        }
        return defaults.get(name, {})

    @app.get("/api/strategies/library")
    def strategy_library():
        library = []
        for s in get_library():
            item = dict(s)
            item["icon"] = SCHOOL_ICONS.get(s.get("school"), "📊")
            library.append(item)
        return {"library": library}

    @app.get("/api/strategies/code-template")
    def code_template():
        return {"code": DEFAULT_CODE, "doc": CODE_DOC}

    @app.get("/api/strategies/custom-schema")
    def custom_schema():
        return {
            "indicators": [
                {"name": name, "label": INDICATOR_LABELS.get(name, name), "params": DEFAULT_PARAMS.get(name, {})}
                for name in INDICATOR_LABELS
            ],
            "ops": list(OPS.keys()),
        }

    # ---------------- 配置 ----------------
    @app.get("/api/config")
    def get_config():
        return _mask_config(state.config)

    @app.post("/api/config")
    def save_config(body: dict, request: Request = None):
        """保存配置：合并默认值、保护脱敏字段、热重载服务并写入审计。"""
        merged = _save_config(body)
        token = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip() if request else ""
        username = state.auth.username(token) or "admin"
        ip = request.client.host if request and request.client else "-"
        state.audit.log(username, "保存配置", "POST", "/api/config", ip=ip, status=200)
        return {"ok": True, "config": _mask_config(merged)}

    @app.post("/api/config/reset")
    def config_reset(request: Request = None):
        """恢复内置默认配置（config/config.default.yaml），不影响环境变量密钥。"""
        default_path = ROOT / "config" / "config.default.yaml"
        if not default_path.exists():
            raise HTTPException(status_code=404, detail="默认配置文件不存在")
        default = yaml.safe_load(default_path.read_text(encoding="utf-8")) or {}
        _save_config(default)
        token = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip() if request else ""
        username = state.auth.username(token) or "admin"
        ip = request.client.host if request and request.client else "-"
        state.audit.log(username, "恢复默认配置", "POST", "/api/config/reset", ip=ip, status=200)
        return {"ok": True, "config": _mask_config(state.config)}

    # ---------------- 认证 ----------------
    @app.post("/api/auth/login")
    def auth_login(body: dict, request: Request = None):
        auth_cfg = state.config.get("auth", {})
        ip = request.client.host if request.client else "-"
        lock_key = _login_lock_key(body.get("username", ""), request)
        _check_login_lock(lock_key)
        if not auth_cfg.get("enabled", True):
            token = state.auth.issue(body.get("username", "admin"))
            return {"ok": True, "token": token, "username": auth_cfg.get("username", "admin")}
        token = state.auth.login(
            body.get("username", ""), body.get("password", ""),
            auth_cfg.get("username", "admin"),
            auth_cfg.get("password"), auth_cfg.get("password_hash"),
        )
        if not token:
            rec = _login_attempts.setdefault(lock_key, {"fails": 0, "locked_until": 0})
            rec["fails"] = rec.get("fails", 0) + 1
            if rec["fails"] >= MAX_LOGIN_FAILS:
                rec["locked_until"] = time.time() + LOGIN_LOCK_MINUTES * 60
                rec["fails"] = 0
            state.audit.log(body.get("username", "?"), "登录失败", "POST", "/api/auth/login", ip=ip, status=401)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        _login_attempts.pop(lock_key, None)
        state.audit.log(body.get("username", "admin"), "登录成功", "POST", "/api/auth/login", ip=ip, status=200)
        return {"ok": True, "token": token, "username": auth_cfg.get("username", "admin")}

    @app.get("/api/auth/status")
    def auth_status():
        auth_cfg = state.config.get("auth", {})
        return {
            "enabled": bool(auth_cfg.get("enabled", True)),
            "username": auth_cfg.get("username", "admin"),
            "has_password_hash": bool(auth_cfg.get("password_hash")),
            "default_password": not bool(auth_cfg.get("password_hash")) and auth_cfg.get("password") == "admin123",
        }

    @app.post("/api/auth/logout")
    def auth_logout(authorization: str = Header(""), request: Request = None):
        token = authorization.replace("Bearer ", "").strip()
        username = state.auth.username(token) or "system"
        state.auth.revoke(token)
        state.audit.log(username, "登出", "POST", "/api/auth/logout", ip=request.client.host if request else "-")
        return {"ok": True}

    @app.post("/api/auth/change-password")
    def auth_change_password(body: dict, authorization: str = Header("")):
        old_pwd = body.get("old_password", "")
        new_pwd = body.get("new_password", "")
        if len(new_pwd) < 6:
            raise HTTPException(status_code=400, detail="新密码至少 6 位")
        auth_cfg = state.config.get("auth", {})
        ok = False
        if auth_cfg.get("password_hash"):
            ok = verify_password(old_pwd, auth_cfg["password_hash"])
        else:
            ok = auth_cfg.get("password") == old_pwd
        if not ok:
            raise HTTPException(status_code=400, detail="原密码错误")
        _save_config({"auth": {"password_hash": hash_password(new_pwd), "password": ""}})
        username = state.auth.username(authorization.replace("Bearer ", "").strip()) or "admin"
        state.auth.revoke_all()
        state.audit.log(username, "修改密码", "POST", "/api/auth/change-password")
        return {"ok": True, "message": "密码已更新，请重新登录"}

    # ---------------- 系统状态 / 审计 ----------------
    @app.get("/api/system/status")
    def system_status():
        status = state.system.status()
        status["auth"] = state.auth.status()
        status["audit"] = state.audit.status()
        status["node"] = {"role": state.deployment_role, "node_id": state.node_id}
        try:
            status["monitor"] = {"running": state.monitor.running, "scans": state.monitor.scan_count, "markets": len(state.monitor.markets)}
        except Exception:  # noqa: BLE001
            status["monitor"] = {}
        try:
            status["evolution"] = state.evolution.status()
        except Exception:  # noqa: BLE001
            status["evolution"] = {}
        return status

    @app.post("/api/system/backup")
    def system_backup():
        try:
            return state.system.backup_now()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/audit/logs")
    def audit_logs(limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
        return {"logs": state.audit.list_logs(limit=limit, offset=offset), "status": state.audit.status()}

    @app.get("/api/audit/logs.csv")
    def audit_logs_csv(limit: int = Query(2000, ge=1, le=10000)):
        logs = state.audit.list_logs(limit=limit, offset=0)
        rows = [["时间", "用户", "操作", "方法", "路径", "详情", "IP", "状态"]]
        for l in logs:
            rows.append([l.get("ts", ""), l.get("username", ""), l.get("action", ""), l.get("method", ""),
                         l.get("path", ""), l.get("detail", ""), l.get("ip", ""), l.get("status", "")])
        csv_text = "\ufeff" + "\n".join(",".join('"' + str(c).replace('"', '""') + '"' for c in row) for row in rows)
        return Response(content=csv_text, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="audit_logs.csv"'})

    @app.get("/api/audit/status")
    def audit_status():
        return state.audit.status()

    # ---------------- 行情 ----------------
    @app.get("/api/ohlcv")
    def ohlcv(symbol: str = Query("BTC/USDT"), timeframe: str = Query("1h"), limit: int = Query(500, ge=50, le=5000), source: str = Query("auto")):
        df, used_source = _load_ohlcv(symbol, timeframe, limit, source)
        return _bars_payload(df, symbol, timeframe, used_source)

    @app.get("/api/tickers")
    def tickers(symbols: str = Query("BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT")):
        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        now = time.time()
        if now - _ticker_cache["ts"] < 30 and _ticker_cache["data"]:
            return _ticker_cache["data"]
        result = _fetch_tickers(syms, state.config["exchange"]["id"])
        _ticker_cache.update({"ts": now, "data": result})
        return result

    # ---------------- 交易所真实账户 ----------------
    @app.get("/api/account/status")
    def account_status(force: bool = Query(False)):
        now = time.time()
        if not force and _account_cache["data"] and now - _account_cache["ts"] < 30:
            return _account_cache["data"]
        data = _fetch_account()
        _account_cache.update({"ts": now, "data": data})
        return data

    # ---------------- 实时推送（SSE） ----------------
    @app.get("/api/stream")
    def stream(scope: str = Query("live"), token: str = Query("")):
        """Server-Sent Events：实时推送实盘 / 监控状态，前端 EventSource 订阅。"""
        auth_cfg = state.config.get("auth", {})
        if auth_cfg.get("enabled", True) and not state.auth.validate(token):
            return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期"})
        if scope not in ("live", "monitor"):
            return JSONResponse(status_code=400, content={"detail": "scope 仅支持 live / monitor"})

        def gen():
            try:
                while True:
                    if scope == "live":
                        payload = state.live.status() if state.live else {"running": False}
                    else:
                        payload = {
                            "status": state.monitor.status(),
                            "rankings": state.monitor.rankings(),
                        }
                    yield "data: " + json.dumps(payload, ensure_ascii=False, default=str) + "\n\n"
                    time.sleep(2.0 if scope == "live" else 4.0)
            except GeneratorExit:  # noqa: PERF203
                return

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---------------- 数据管理 ----------------
    @app.post("/api/data/fetch")
    def fetch_data(body: dict):
        symbol = body.get("symbol", "BTC/USDT")
        timeframe = body.get("timeframe", "1h")
        days = int(body.get("days", 730))
        synthetic = bool(body.get("synthetic", False))
        if synthetic:
            df = generate_synthetic_ohlcv(timeframe=timeframe, days=days, seed=int(body.get("seed", 42)))
        else:
            try:
                fetcher = ExchangeDataFetcher(state.config["exchange"]["id"], proxy=exchange_proxy(state.config))
                df = fetcher.fetch_ohlcv_paginated(symbol, timeframe, days=days)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=502, detail="交易所数据获取失败: " + str(exc)) from exc
        if df.empty:
            raise HTTPException(status_code=404, detail="未获取到任何数据")
        storage = SQLiteStorage(state.config["data"]["storage_db"])
        n = storage.save_ohlcv(symbol, timeframe, df)
        storage.close()
        return {"ok": True, "symbol": symbol, "timeframe": timeframe, "rows": n, "first": str(df.index[0]), "last": str(df.index[-1]), "source": "synthetic" if synthetic else "exchange"}

    @app.delete("/api/data")
    def data_delete(symbol: str = Query(...), timeframe: str = Query(...)):
        """删除指定标的+周期的本地数据（操作留审计）。"""
        storage = SQLiteStorage(state.config["data"]["storage_db"])
        try:
            cur = storage.conn.execute(
                "DELETE FROM ohlcv WHERE symbol=? AND timeframe=?", (symbol, timeframe)
            )
            storage.conn.commit()
            n = cur.rowcount
        finally:
            storage.close()
        if n <= 0:
            raise HTTPException(status_code=404, detail="本地数据库中没有 " + symbol + " " + timeframe + " 数据")
        return {"ok": True, "deleted": n, "symbol": symbol, "timeframe": timeframe}

    @app.get("/api/data/stats")
    def data_stats():
        storage = SQLiteStorage(state.config["data"]["storage_db"])
        rows = storage.conn.execute(
            "SELECT symbol, timeframe, COUNT(*) AS n, MIN(timestamp) AS t0, MAX(timestamp) AS t1 "
            "FROM ohlcv GROUP BY symbol, timeframe ORDER BY symbol, timeframe"
        ).fetchall()
        storage.close()
        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        out = []
        for r in rows:
            symbol, timeframe, n, t0, t1 = r[0], r[1], r[2], r[3], r[4]
            freq_nanos = TIMEFRAME_NANOS.get(timeframe)
            expected = None
            gap_ratio = None
            freshness_h = None
            if t0 is not None and t1 is not None and freq_nanos:
                expected = int((t1 - t0) / (freq_nanos // 1_000_000)) + 1
                gap_ratio = 1.0 - (n / expected) if expected > 0 else None
                freshness_h = (now_ms - t1) / 3_600_000.0
            out.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": n,
                "expected_bars": expected,
                "gap_ratio": round(gap_ratio, 4) if gap_ratio is not None else None,
                "freshness_hours": round(freshness_h, 2) if freshness_h is not None else None,
                "first": pd.Timestamp(t0, unit="ms", tz="UTC").isoformat() if t0 else None,
                "last": pd.Timestamp(t1, unit="ms", tz="UTC").isoformat() if t1 else None,
            })
        return out

    # ---------------- 回测 ----------------
    @app.post("/api/backtest/run")
    def backtest_run(body: dict):
        return {"id": state.backtest.submit(body)}

    @app.get("/api/backtest/jobs")
    def backtest_jobs():
        return {"jobs": state.backtest.list_jobs()}

    @app.get("/api/backtest/result/{job_id}")
    def backtest_result(job_id: str):
        job = state.backtest.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job

    @app.delete("/api/backtest/result/{job_id}")
    def backtest_delete(job_id: str):
        if not state.backtest.delete_job(job_id):
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"ok": True}

    @app.post("/api/backtest/compare")
    def backtest_compare(body: dict):
        """多策略对比：并行回测多组策略，权益曲线同图展示。"""
        if not body.get("strategies"):
            raise HTTPException(status_code=400, detail="至少选择一个策略")
        return {"id": state.backtest.submit_compare(body)}

    @app.post("/api/backtest/rerun/{job_id}")
    def backtest_rerun(job_id: str):
        """用历史任务的原始参数重新回测。"""
        job = state.backtest.get_job(job_id)
        if not job or not job.get("params"):
            raise HTTPException(status_code=404, detail="回测任务不存在或缺少参数")
        return {"id": state.backtest.submit(job["params"])}

    @app.get("/api/backtest/compare/{job_id}")
    def backtest_compare_result(job_id: str):
        job = state.backtest.get_compare_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="对比任务不存在")
        return job

    # ---------------- 分析报告 ----------------
    @app.get("/api/report/{job_id}")
    def report_analysis(job_id: str):
        job = state.backtest.get_job(job_id)
        if not job or job.get("status") != "done" or not job.get("result"):
            raise HTTPException(status_code=404, detail="回测任务不存在或未完成")
        return {"id": job_id, "analysis": job["result"].get("analysis"), "metrics": job["result"].get("metrics")}

    @app.get("/api/backtest/result/{job_id}/trades.csv")
    def backtest_trades_csv(job_id: str):
        job = state.backtest.get_job(job_id)
        if not job or job.get("status") != "done" or not job.get("result"):
            raise HTTPException(status_code=404, detail="回测任务不存在或未完成")
        trades = job["result"].get("trades") or []
        rows = [["方向", "开仓时间", "开仓价", "平仓时间", "平仓价", "数量", "手续费", "盈亏", "收益率%", "平仓原因"]]
        for t in trades:
            rows.append([
                "多" if t.get("side") == "long" else "空",
                t.get("entry_time", ""), t.get("entry_price", ""), t.get("exit_time", ""),
                t.get("exit_price", ""), t.get("quantity", ""), t.get("fees", ""),
                t.get("pnl", ""), "" if t.get("return_pct") is None else round(t.get("return_pct", 0) * 100, 4),
                t.get("reason", ""),
            ])
        csv_text = "\ufeff" + "\n".join(",".join('"' + str(c).replace('"', '""') + '"' for c in row) for row in rows)
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="trades_' + job_id + '.csv"'},
        )

    @app.get("/api/evolution/trades.csv")
    def evolution_trades_csv(limit: int = Query(5000, ge=1, le=50000)):
        trades = state.evolution.store.recent_trades(limit)
        rows = [["时间", "方向", "标的", "周期", "策略", "开仓价", "平仓价", "数量", "手续费", "盈亏", "收益率%", "原因"]]
        for t in trades:
            rows.append([
                t.get("exit_time", t.get("entry_time", "")), t.get("side", ""), t.get("symbol", ""),
                t.get("timeframe", ""), t.get("strategy", ""), t.get("entry_price", ""),
                t.get("exit_price", ""), t.get("quantity", ""), t.get("fees", ""),
                t.get("pnl", ""), "" if t.get("return_pct") is None else round(t.get("return_pct", 0) * 100, 4),
                t.get("reason", ""),
            ])
        csv_text = "\ufeff" + "\n".join(",".join('"' + str(c).replace('"', '""') + '"' for c in row) for row in rows)
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="evolution_trades.csv"'},
        )

    @app.get("/api/report/{job_id}/html")
    def report_html(job_id: str):
        job = state.backtest.get_job(job_id)
        if not job or job.get("status") != "done" or not job.get("result"):
            raise HTTPException(status_code=404, detail="回测任务不存在或未完成")
        payload = job["result"]
        doc = generate_html_report(payload, strategy_name=payload.get("strategy", ""), source=payload.get("source", ""), timeframe=payload.get("timeframe", "1h"))
        return Response(content=doc, media_type="text/html; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="backtest_report_' + job_id + '.html"'})

    # ---------------- AI 建议 ----------------
    @app.get("/api/ai/status")
    def ai_status():
        return {"configured": state.advisor.is_configured(), "model": state.advisor.model, "base_url": state.advisor.base_url,
                "hint": "" if state.advisor.is_configured() else state.advisor.config_hint()}

    @app.post("/api/ai/advice")
    def ai_advice(body: dict):
        job_id = body.get("job_id")
        job = state.backtest.get_job(job_id) if job_id else None
        if not job or job.get("status") != "done" or not job.get("result"):
            raise HTTPException(status_code=404, detail="请先完成一次回测")
        if not state.advisor.is_configured():
            raise HTTPException(status_code=400, detail=state.advisor.config_hint())
        try:
            advice = state.advisor.advice(_build_ai_context(job["result"]))
            return {"ok": True, "advice": advice}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail="AI 调用失败: " + str(exc)) from exc

    # ---------------- 实盘 / 模拟盘 ----------------
    @app.get("/api/live/status")
    def live_status():
        if state.live is None:
            return {"running": False, "events": [], "positions": [], "orders": []}
        return state.live.status()

    @app.post("/api/live/start")
    def live_start(body: dict):
        mode = body.get("mode", "paper")
        risk_cfg = state.config.get("risk", {}) or {}
        if mode == "live" and risk_cfg.get("require_live_confirm", True) and not bool(body.get("confirm_live")):
            raise HTTPException(status_code=400, detail="实盘模式需要二次确认：请在弹窗中勾选确认并输入 CONFIRM")
        if state.live is None:
            state.live = LiveManager(state.config, notifier=state.notifier, trade_store=state.evolution.store)
        try:
            state.live.start(body)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="启动失败: " + str(exc)) from exc
        return state.live.status()

    @app.post("/api/live/stop")
    def live_stop():
        if state.live is not None:
            state.live.stop()
            return state.live.status()
        return {"running": False}

    @app.get("/api/live/session")
    def live_session():
        """读取上次保存的实盘会话（服务重启后可恢复）。"""
        return {"session": load_live_session(state.config)}

    @app.post("/api/live/recover")
    def live_recover(body: dict):
        """一键恢复上次实盘/模拟盘会话（实盘需二次确认）。"""
        sess = load_live_session(state.config)
        if not sess:
            raise HTTPException(status_code=404, detail="没有可恢复的实盘会话")
        if state.live is not None and state.live.running:
            raise HTTPException(status_code=400, detail="交易循环已在运行中")
        mode = sess.get("mode", "paper")
        risk_cfg = state.config.get("risk", {}) or {}
        if mode == "live" and risk_cfg.get("require_live_confirm", True) and not bool(body.get("confirm_live")):
            raise HTTPException(status_code=400, detail="实盘会话恢复需要二次确认（confirm_live）")
        params = {
            "mode": mode,
            "symbol": sess.get("symbol", "BTC/USDT"),
            "timeframe": sess.get("timeframe", "1h"),
            "data_source": sess.get("data_source", "synthetic"),
            "poll_interval_sec": sess.get("poll_interval_sec", 60),
            "warmup_bars": sess.get("warmup_bars", 200),
            "paper_initial_balance": sess.get("paper_initial_balance", 10000),
            "seed": sess.get("seed", 7),
            "strategy": sess.get("strategy") or {"name": "ma_cross", "params": {}},
            "risk": sess.get("risk") or {},
            "confirm_live": mode == "live",
        }
        if state.live is None:
            state.live = LiveManager(state.config, notifier=state.notifier, trade_store=state.evolution.store)
        try:
            state.live.start(params)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="恢复失败: " + str(exc)) from exc
        return {"ok": True, "status": state.live.status()}

    @app.post("/api/live/flatten")
    def live_flatten():
        """一键平仓：市价平掉当前持仓（不停止循环）。"""
        if state.live is None:
            raise HTTPException(status_code=400, detail="交易循环未运行")
        result = state.live.flatten()
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("message", "平仓失败"))
        return {"ok": True, "message": result.get("message", "已平仓"), "status": state.live.status()}

    @app.delete("/api/live/session")
    def live_session_clear():
        """清除已保存的实盘会话（不停止当前循环）。"""
        try:
            p = live_session_path(state.config)
            if p.exists():
                p.unlink()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="清除失败: " + str(exc)) from exc
        return {"ok": True}

    # ---------------- 策略进化 ----------------
    @app.get("/api/evolution/status")
    def evolution_status():
        return state.evolution.status()

    @app.post("/api/evolution/optimize")
    def evolution_optimize(body: dict):
        return {"id": state.evolution.submit_optimize(body)}

    @app.get("/api/evolution/jobs")
    def evolution_jobs():
        return {"jobs": state.evolution.list_jobs()}

    @app.get("/api/evolution/result/{job_id}")
    def evolution_result(job_id: str):
        job = state.evolution.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job

    @app.get("/api/evolution/trades")
    def evolution_trades(limit: int = Query(200, ge=1, le=1000)):
        return {"trades": state.evolution.store.recent_trades(limit)}

    @app.get("/api/evolution/trades/stats")
    def evolution_trade_stats():
        return state.evolution.store.stats()

    @app.post("/api/evolution/analyze")
    def evolution_analyze():
        try:
            result = state.evolution.analyze_and_learn()
            return {"ok": True, **result}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/evolution/iterations")
    def evolution_iterations(limit: int = Query(100, ge=1, le=500)):
        return {"iterations": state.evolution.store.list_iterations(limit)}

    @app.get("/api/evolution/iterations/{iteration_id}")
    def evolution_iteration(iteration_id: int):
        it = state.evolution.store.get_iteration(iteration_id)
        if not it:
            raise HTTPException(status_code=404, detail="迭代不存在")
        return it

    @app.post("/api/evolution/iterations/{iteration_id}/experience")
    def evolution_experience(iteration_id: int, body: dict):
        text = body.get("text", "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="经验内容不能为空")
        state.evolution.store.append_experience(iteration_id, text)
        return {"ok": True}

    # ---------------- 市场监控 ----------------
    @app.get("/api/monitor/status")
    def monitor_status():
        return state.monitor.status()

    @app.post("/api/monitor/start")
    def monitor_start():
        state.monitor.start()
        return state.monitor.status()

    @app.post("/api/monitor/stop")
    def monitor_stop():
        state.monitor.stop()
        return state.monitor.status()

    @app.get("/api/monitor/events")
    def monitor_events(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                       type: str | None = Query(None), symbol: str | None = Query(None)):
        return {"events": state.monitor.get_events(limit=limit, offset=offset, type=type, symbol=symbol)}

    @app.get("/api/monitor/events.csv")
    def monitor_events_csv(limit: int = Query(2000, ge=1, le=10000),
                           type: str | None = Query(None), symbol: str | None = Query(None)):
        events = state.monitor.get_events(limit=limit, offset=0, type=type, symbol=symbol)
        rows = [["时间", "币种", "类型", "标题", "详情", "价格", "变化"]]
        for e in events:
            rows.append([e.get("ts", ""), e.get("symbol", ""), e.get("type", ""), e.get("title", ""),
                         e.get("detail", ""), e.get("price", ""), e.get("change", "")])
        csv_text = "\ufeff" + "\n".join(",".join('"' + str(c).replace('"', '""') + '"' for c in row) for row in rows)
        return Response(content=csv_text, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="monitor_events.csv"'})

    @app.post("/api/monitor/config")
    def monitor_config(body: dict):
        state.monitor.update_config(body)
        return state.monitor.status()

    @app.get("/api/monitor/rankings")
    def monitor_rankings():
        return state.monitor.rankings()

    # ---------------- 交易所测试 ----------------
    @app.get("/api/exchange/status")
    def exchange_status():
        """密钥/代理加载状态（只返回是否存在，不返回真实值）。"""
        return {
            "exchange": state.config.get("exchange", {}).get("id"),
            "sandbox": state.config.get("exchange", {}).get("sandbox", False),
            "has_api_key": bool(os.getenv("CCXT_API_KEY")),
            "has_api_secret": bool(os.getenv("CCXT_API_SECRET")),
            "has_passphrase": bool(os.getenv("CCXT_API_PASSPHRASE") or os.getenv("CCXT_PASSWORD")),
            "proxy": exchange_proxy(state.config),
            "proxy_configured": bool(exchange_proxy(state.config)),
        }

    @app.post("/api/exchange/test")
    def exchange_test(body: dict):
        exchange_id = body.get("exchange_id") or state.config["exchange"]["id"]
        api_key = body.get("api_key") or os.getenv("CCXT_API_KEY") or ""
        api_secret = body.get("api_secret") or os.getenv("CCXT_API_SECRET") or ""
        api_passphrase = body.get("api_passphrase") or os.getenv("CCXT_API_PASSPHRASE") or os.getenv("CCXT_PASSWORD") or ""
        proxy = body.get("proxy") or exchange_proxy(state.config)
        try:
            ex_cls = getattr(ccxt, exchange_id)
            ex_params = {"enableRateLimit": True, "timeout": 8000}
            if proxy:
                ex_params["proxies"] = {"http": proxy, "https": proxy}
            ex = ex_cls(ex_params)
            t = ex.fetch_ticker("BTC/USDT")
            public_ok = t.get("last") is not None
            detail = "公开行情连接成功（BTC/USDT 最新价 " + str(t.get("last")) + "）"
            if exchange_id == "okx" and not api_passphrase:
                detail += "；提示：OKX 私密接口需要口令（passphrase），请填写 API Passphrase"
            balance_ok = None
            if api_key and api_secret:
                try:
                    ex2_params = {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True, "timeout": 8000}
                    if api_passphrase:
                        ex2_params["password"] = api_passphrase
                    if proxy:
                        ex2_params["proxies"] = {"http": proxy, "https": proxy}
                    ex2 = ex_cls(ex2_params)
                    bal = ex2.fetch_balance()
                    totals = {k: v for k, v in (bal.get("total") or {}).items() if v}
                    balance_ok = True
                    detail += "；账户验证成功，余额币种: " + (", ".join(list(totals)[:8]) or "无")
                except Exception as exc:  # noqa: BLE001
                    balance_ok = False
                    detail += "；账户验证失败: " + str(exc)[:120]
            return {"ok": True, "exchange": exchange_id, "public": public_ok, "balance": balance_ok, "detail": detail}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "exchange": exchange_id, "detail": "连接失败: " + str(exc)[:150]}

    # ---------------- 飞书 ----------------
    @app.get("/api/notify/status")
    def notify_status():
        cfg = state.notifier
        return {"configured": cfg.is_configured(), "enabled": cfg.enabled,
                "webhook": (cfg.webhook[:60] + "...") if len(cfg.webhook) > 60 else cfg.webhook,
                "has_secret": bool(cfg.secret), "on_trade": cfg.on_trade, "on_alert": cfg.on_alert,
                "on_backtest": cfg.on_backtest, "hint": "" if cfg.is_configured() else cfg.config_hint()}

    @app.post("/api/notify/test")
    def notify_test(body: dict):
        message = body.get("message") or "🧪 Quantiva 测试消息：飞书推送已接通！"
        try:
            state.notifier.send_text(message)
            return {"ok": True, "message": "测试消息已发送"}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="发送失败: " + str(exc)) from exc

    return app


app = create_app()
