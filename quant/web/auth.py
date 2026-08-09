"""????????Token ??/???API ??????

- ???? PBKDF2-HMAC-SHA256 ????????????????
- ????????? Token??? 12 ?????
- ?? /api/* ??????/???????? Authorization: Bearer <token>
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time

PUBLIC_PATHS = {"/api/auth/login", "/api/health", "/api/auth/status", "/api/stream"}

TOKEN_TTL_SECONDS = 12 * 3600


def hash_password(password: str, salt: bytes | None = None) -> str:
    """?? salt$hash ????????"""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


class AuthManager:
    """Token 签发与校验：登录签发、改密吊销全部会话。"""

    def __init__(self):
        self._tokens: dict[str, tuple[float, str]] = {}  # token -> (expiry, username)
        self._lock = threading.Lock()

    def login(self, username: str, password: str, cfg_username: str, cfg_password: str | None, cfg_hash: str | None) -> str | None:
        if username != cfg_username:
            return None
        if cfg_hash and verify_password(password, cfg_hash):
            return self.issue(username)
        if cfg_password and hmac.compare_digest(password.encode(), cfg_password.encode()):
            return self.issue(username)
        return None

    def issue(self, username: str = "system") -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = (time.time() + TOKEN_TTL_SECONDS, username)
        return token

    def validate(self, token: str) -> bool:
        entry = self._tokens.get(token)
        if entry is None:
            return False
        exp, _ = entry
        if time.time() > exp:
            self._tokens.pop(token, None)
            return False
        return True

    def username(self, token: str) -> str | None:
        entry = self._tokens.get(token)
        return entry[1] if entry else None

    def revoke(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)

    def revoke_all(self) -> None:
        """吊销全部 Token（修改密码后调用，强制重新登录）。"""
        with self._lock:
            self._tokens.clear()

    def status(self) -> dict:
        now = time.time()
        active = sum(1 for exp, _ in self._tokens.values() if exp > now)
        return {"active_tokens": active, "ttl_seconds": TOKEN_TTL_SECONDS}
