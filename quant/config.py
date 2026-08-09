"""???????????"""
from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "exchange": {"id": "binance", "sandbox": False},
    "data": {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "days": 730,
        "storage_db": "data/ohlcv.db",
        "quote": "USDT",
    },
    "strategy": {
        "name": "ma_cross",
        "params": {"fast": 20, "slow": 50, "direction": "long_only"},
    },
    "risk": {
        "max_position_pct": 0.5,
        "leverage": 1.0,
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "atr_stop_mult": 2.0,
        "max_positions": 1,
        "max_daily_loss_pct": None,
        "trade_direction": "long_only",
    },
    "backtest": {
        "initial_capital": 10000.0,
        "fee_rate": 0.001,
        "slippage": 0.0005,
    },
    "live": {
        "poll_interval_sec": 60,
        "warmup_bars": 200,
        "mode": "paper",
        "paper_initial_balance": 10000.0,
    },
    "report": {"output_dir": "reports"},
    "ai": {
        "enabled": False,
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "temperature": 0.4,
    },
    "monitor": {
        "enabled": True,
        "interval_sec": 30,
        "source": "synthetic",
        "symbols": [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT",
            "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "MATIC/USDT", "LTC/USDT",
            "SHIB/USDT", "UNI/USDT", "ATOM/USDT", "ETC/USDT", "FIL/USDT", "APT/USDT",
            "NEAR/USDT", "OP/USDT", "ARB/USDT", "SUI/USDT", "INJ/USDT", "TIA/USDT",
            "SEI/USDT", "WLD/USDT", "PEPE/USDT", "BONK/USDT", "TRX/USDT", "TON/USDT",
            "HBAR/USDT", "ALGO/USDT",
        ],
        "thresholds": {
            "volume_ratio": 3.0,
            "price_1h": 0.025,
            "price_24h": 0.08,
            "alert_cooldown_min": 15,
        },
    },
    "notify": {
        "feishu": {"enabled": False, "webhook": "", "secret": ""},
        "on_trade": True,
        "on_alert": True,
        "on_backtest": False,
    },
    "evolution": {
        "db_path": "data/evolution.db",
        "auto_analyze_enabled": True,
        "auto_analyze_interval_hours": 6,
        "save_backtest_trades": False,
        "save_live_trades": True,
    },
    "auth": {
        "enabled": True,
        "username": "admin",
        "password": "admin123",  # ??????????????????????
        "password_hash": "",
    },
    "system": {
        "data_dir": "data",
        "log_dir": "data/logs",
        "backup": {"enabled": True, "interval_hours": 24, "keep": 7},
    },
    "deployment": {
        "role": "all",  # all | monitor | trader | web??????? QUANTX_ROLE ???
        "node_id": "node-1",  # ???????????? QUANTX_NODE_ID ???
    },
}


def _deep_merge(base: dict, override: dict | None) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path) -> dict:
    """?? YAML ?????????????????????????"""
    path = Path(path)
    cfg: dict = {}
    if path.exists():
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _deep_merge(DEFAULT_CONFIG, cfg)
