"""AI 策略优化建议（兼容 OpenAI / DeepSeek / 通义 / Ollama 等接口）。

配置示例（config.yaml）:
ai:
  enabled: false
  api_key_env: OPENAI_API_KEY
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  temperature: 0.4
"""
from __future__ import annotations

import os

import httpx


class AIAdvisor:
    def __init__(self, config: dict):
        ai_cfg = config.get("ai") or {}
        self.enabled = bool(ai_cfg.get("enabled", False))
        self.base_url = str(ai_cfg.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        self.model = str(ai_cfg.get("model", "gpt-4o-mini"))
        self.temperature = float(ai_cfg.get("temperature", 0.4))
        env_key = str(ai_cfg.get("api_key_env", "OPENAI_API_KEY"))
        self.api_key = ai_cfg.get("api_key") or os.getenv(env_key, "")

    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.base_url)

    def config_hint(self) -> str:
        return "请在「系统设置」中启用 AI 并配置 API Key（支持 OpenAI / DeepSeek / 通义 / Ollama 等 OpenAI 兼容接口）"

    def build_prompt(self, context: dict) -> str:
        return f"""你是一位资深的量化交易策略分析师。请根据以下回测数据，对策略给出专业、可执行的分析与优化建议。

【策略信息】
- 策略: {context.get("strategy", "?")}
- 参数: {context.get("strategy_params", "?")}
- 标的: {context.get("symbol", "?")}  周期: {context.get("timeframe", "?")}

【绩效指标】
- 总收益 {context.get("total_return")}, 年化 {context.get("annual_return")}, 买入持有 {context.get("buy_hold_return")}
- 夏普 {context.get("sharpe")}, 索提诺 {context.get("sortino")}, 卡玛 {context.get("calmar")}
- 最大回撤 {context.get("max_drawdown")}, 年化波动 {context.get("volatility")}, 仓位暴露 {context.get("exposure")}

【交易统计】
- 交易次数 {context.get("num_trades")}, 胜率 {context.get("win_rate")}, 盈亏比 {context.get("profit_factor")}
- 平均盈利 {context.get("avg_win")}, 平均亏损 {context.get("avg_loss")}
- 平均持仓 {context.get("avg_holding_hours")} 小时, 最大连胜 {context.get("max_win_streak")}, 最大连亏 {context.get("max_loss_streak")}
- 平仓原因分布: {context.get("exit_reasons", "?")}

【回撤分析】
- 回撤次数 {context.get("num_drawdowns")}, 最长回撤 {context.get("longest_dd_days")} 天

【市场背景】
{context.get("market_summary", "无")}

请输出以下四部分（总计 500 字以内，中文，不要客套）：
1. 【诊断】策略当前的主要问题（2-3 条，用数据说话）
2. 【风险】最大风险点
3. 【优化建议】至少 3 条具体可执行的优化方向（含具体参数调整建议）
4. 【风控建议】仓位/止损/止盈层面的建议"""

    async def advice_async(self, context: dict) -> str:
        if not self.is_configured():
            raise RuntimeError(self.config_hint())
        prompt = self.build_prompt(context)
        url = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是量化交易策略分析专家，回复严谨简洁。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": 1200,
        }
        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError("AI 接口返回 " + str(resp.status_code) + ": " + resp.text[:200])
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    def advice(self, context: dict) -> str:
        import asyncio

        return asyncio.run(self.advice_async(context))
