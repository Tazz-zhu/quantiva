"""飞书群机器人推送（自定义机器人 Webhook，支持签名校验）。

配置示例（config.yaml）:
notify:
  feishu:
    enabled: false
    webhook: https://open.feishu.cn/open-apis/bot/v2/hook/xxx
    secret: ""        # 机器人安全设置中的签名密钥（可选）
  on_trade: true      # 交易开平仓推送
  on_alert: true      # 市场异动推送
  on_backtest: false  # 回测完成推送
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import httpx


class FeishuNotifier:
    def __init__(self, config: dict):
        f_cfg = (config.get("notify") or {}).get("feishu") or {}
        self.enabled = bool(f_cfg.get("enabled", False))
        self.webhook = f_cfg.get("webhook") or os.getenv("FEISHU_WEBHOOK", "")
        self.secret = f_cfg.get("secret") or ""
        self.on_trade = bool((config.get("notify") or {}).get("on_trade", True))
        self.on_alert = bool((config.get("notify") or {}).get("on_alert", True))
        self.on_backtest = bool((config.get("notify") or {}).get("on_backtest", False))

    def is_configured(self) -> bool:
        return self.enabled and bool(self.webhook)

    def config_hint(self) -> str:
        return "请在「系统设置」中填写飞书机器人 Webhook（群设置 → 群机器人 → 添加自定义机器人）"

    def _sign(self, timestamp: str) -> str | None:
        if not self.secret:
            return None
        string_to_sign = timestamp + "\n" + self.secret
        digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _payload(self, msg_type: str, content) -> dict:
        payload = {"msg_type": msg_type, "content": content}
        if self.secret:
            ts = str(int(time.time()))
            payload["timestamp"] = ts
            payload["sign"] = self._sign(ts)
        return payload

    def send_text(self, text: str) -> dict:
        if not self.is_configured():
            raise RuntimeError(self.config_hint())
        return self._post(self._payload("text", {"text": text}))

    def send_card(self, title: str, lines: list[str], note: str = "") -> dict:
        if not self.is_configured():
            raise RuntimeError(self.config_hint())
        elements = []
        for line in lines:
            if line:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": line}})
        if note:
            elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": note}]})
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": elements,
        }
        return self._post({"msg_type": "interactive", "card": card})

    def _post(self, payload: dict) -> dict:
        resp = httpx.post(self.webhook, json=payload, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError("飞书接口返回 " + str(resp.status_code) + ": " + resp.text[:200])
        data = resp.json()
        if data.get("code") not in (0, None):
            raise RuntimeError("飞书返回错误: " + str(data))
        return data

    def send_trade(self, symbol: str, action: str, price: float, qty: float, equity: float | None = None) -> None:
        if not self.on_trade or not self.is_configured():
            return
        try:
            lines = ["**操作**: " + action, "**价格**: " + format(price, ",.4f"), "**数量**: " + format(qty, ".6f")]
            if equity:
                lines.append("**账户权益**: " + format(equity, ",.2f") + " USDT")
            self.send_card("🤖 交易信号 · " + symbol, lines, note="Quantiva 量化交易系统 · 自动推送")
        except Exception as exc:  # noqa: BLE001
            print("[feishu] 交易推送失败: " + str(exc))

    def send_alert(self, symbol: str, alert_type: str, title: str, detail: str, price: float | None = None) -> None:
        if not self.on_alert or not self.is_configured():
            return
        try:
            lines = ["**" + title + "**", detail]
            if price:
                lines.append("**价格**: " + format(price, ",.4f"))
            self.send_card("🚨 市场异动 · " + symbol, lines, note="Quantiva 市场监控 · 自动推送")
        except Exception as exc:  # noqa: BLE001
            print("[feishu] 异动推送失败: " + str(exc))

    def send_backtest_done(self, summary: str) -> None:
        if not self.on_backtest or not self.is_configured():
            return
        try:
            self.send_text("📊 回测完成\n" + summary)
        except Exception as exc:  # noqa: BLE001
            print("[feishu] 回测推送失败: " + str(exc))
