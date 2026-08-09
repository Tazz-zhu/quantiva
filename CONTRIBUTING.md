# 贡献指南

感谢你对 Quantiva 感兴趣！无论是修 Bug、加功能、改进文档还是提建议，都欢迎。

## 开发环境

- Python 3.12+
- 依赖：`pip install -r requirements.txt`
- 启动：`python scripts/webui.py`（访问 http://127.0.0.1:8686）

## 提交规范

1. Fork 仓库并创建特性分支：`git checkout -b feat/xxx`
2. 保持改动聚焦：一个 PR 解决一个问题
3. 为新增逻辑补充单元测试（`tests/`）
4. 本地运行全部测试：`python -m unittest discover -s tests`
5. 更新 `README.md` / `CHANGELOG.md` 相关章节

## 代码风格

- Python：遵循 PEP 8，保持现有模块化结构（quant/ 下按领域分包）
- 前端：原生 JS（无构建步骤），CSS 使用设计令牌（:root 变量），新增组件样式追加到 style.css 并标注版本块
- 不引入新的重量级前端框架，保持离线可运行

## 实盘相关改动

任何涉及真实资金交易的改动必须：
- 先在模拟盘（paper）与交易所测试网充分验证
- 默认保持风险熔断与二次确认开关开启
- 在 PR 描述中说明验证过程
