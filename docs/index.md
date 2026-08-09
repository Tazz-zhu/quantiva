---
layout: default
title: Quantiva · AI 加密货币量化交易终端
description: 模块化、可上线部署的加密货币量化交易系统：回测 / 策略 / 监控 / 模拟盘 / 实盘
---

# Quantiva · AI 加密货币量化交易终端

> 模块化、可正式上线部署的加密货币量化交易系统（Python 3.12 + ccxt + FastAPI + pandas）。
> 覆盖 **数据抓取 → 指标计算 → 策略 → 回测 → 深度分析 → AI 优化 → 市场监控 → 模拟/实盘 → 进化** 完整闭环。

[![GitHub](https://img.shields.io/badge/GitHub-quantiva-181717?logo=github)](https://github.com/Tazz-zhu/quantiva)
![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![CI](https://github.com/Tazz-zhu/quantiva/actions/workflows/ci.yml/badge.svg)

## 界面预览

登录页 | 仪表盘
--- | ---
![登录页](screenshots/ui_login.png) | ![仪表盘](screenshots/ui_dashboard.png)

行情图表 | 策略回测
--- | ---
![行情图表](screenshots/ui_chart.png) | ![策略回测](screenshots/ui_backtest.png)

## 核心能力

- **回测引擎**：信号在下一根 K 线开盘执行（无前视偏差）、止损/止盈/移动止损/保本、杠杆强平、资金费率
- **风控模型**：单笔风险预算仓位、日亏损熔断、组合回撤熔断、实盘二次确认
- **绩效体系**：Sharpe / Sortino / VaR / CVaR / R 倍数 / Alpha-Beta / 月度一致性 / 滚动稳定性
- **参数优化**：网格搜索 + 样本外验证（Holdout），防过拟合
- **市场监控**：32 币种异动检测（放量 / 急涨急跌 / 波动率突增），SSE 实时推送
- **实盘/模拟盘**：一键平仓、执行质量统计、会话持久化恢复
- **体验**：深/浅/跟随系统主题、全局搜索、移动端适配、浏览器通知

## 快速开始

```powershell
pip install -r requirements.txt
python scripts/webui.py        # http://127.0.0.1:8686
```

默认账号 `admin` / `admin123`，登录后请在系统设置中修改密码。

> 离线优先：无法直连交易所时选择「合成数据」即可完整演示全部功能。

## 文档

- [README](https://github.com/Tazz-zhu/quantiva#readme)
- [CHANGELOG](https://github.com/Tazz-zhu/quantiva/blob/main/CHANGELOG.md)
- [贡献指南](https://github.com/Tazz-zhu/quantiva/blob/main/CONTRIBUTING.md)
- [安全说明](https://github.com/Tazz-zhu/quantiva/blob/main/SECURITY.md)

> ⚠️ 本项目的代码与文档仅用于学习与研究，不构成任何投资建议。加密货币交易风险极高，实盘前请务必用模拟盘充分验证。
