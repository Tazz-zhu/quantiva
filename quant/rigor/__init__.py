"""quant.rigor —— 严谨的抗过拟合工具包（移植自 freqtrade 的核心思想）。

提供：
- losses:     多种超参寻优损失函数（Sharpe / Sortino / Calmar / 盈亏比 / 多指标组合…）
- filters:    优化纪元过滤器（交易数 / 收益 / 回撤 / 目标值门槛）
- significance: 统计显著性（bootstrap p 值 / 缩水夏普 / 参数稳定性 / 置换检验）
- walkforward: 滚动样本外（Walk-Forward）验证
- lookahead:  前视偏差（Lookahead Bias）检测
- recursive:  递归指标（Recursive Indicator）偏差检测
"""
from quant.rigor.losses import LOSS_FUNCTIONS, compute_loss, loss_score
from quant.rigor.filters import filter_epochs, EpochFilterOptions
from quant.rigor.significance import (
    bootstrap_p_value,
    deflated_sharpe,
    parameter_stability,
    permutation_test,
    strategy_verdict,
)
from quant.rigor.walkforward import run_walkforward, WalkForwardFold
from quant.rigor.lookahead import analyze_lookahead
from quant.rigor.recursive import analyze_recursive

__all__ = [
    "LOSS_FUNCTIONS", "compute_loss", "loss_score",
    "filter_epochs", "EpochFilterOptions",
    "bootstrap_p_value", "deflated_sharpe", "parameter_stability",
    "permutation_test", "strategy_verdict",
    "run_walkforward", "WalkForwardFold",
    "analyze_lookahead", "analyze_recursive",
]
