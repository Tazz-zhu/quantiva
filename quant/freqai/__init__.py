"""quant.freqai —— FreqAI 风格机器学习量化模块（移植自 freqtrade FreqAI 核心思想）。

- features:  技术指标特征工程（全部因果，无未来数据）
- targets:   标签工程（前瞻收益 / 涨跌分类 / 波动率缩放）
- split:     带 purge/embargo 的时间序列切分（防标签泄漏）
- models:    模型注册表（sklearn，可选 LightGBM/XGBoost）
- pipeline:  训练 / 滚动样本外预测 / 回测 / 实盘推理 编排
- strategy:  FreqAI 策略（基于预测概率产生信号）
"""
from quant.freqai.features import build_features, FEATURE_GROUPS
from quant.freqai.targets import build_targets
from quant.freqai.split import walk_forward_windows
from quant.freqai.models import AVAILABLE_MODELS, create_model
from quant.freqai.pipeline import FreqAIPipeline
from quant.freqai.strategy import FreqAIStrategy

__all__ = [
    "build_features", "FEATURE_GROUPS",
    "build_targets",
    "walk_forward_windows",
    "AVAILABLE_MODELS", "create_model",
    "FreqAIPipeline",
    "FreqAIStrategy",
]
