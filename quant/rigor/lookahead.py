"""前视偏差（Lookahead Bias）检测 —— freqtrade lookahead-analysis 移植。

原理：策略在完整数据上计算的信号，若在"截断到 t 时刻的数据"上重新计算
后在 t 时刻取值不同，说明该信号使用了 t 之后（未来）的信息 —— 前视偏差。

回测时这种偏差会制造虚假的完美信号，实盘无法复现。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant.strategy.base import Strategy


def _same(a: float, b: float, tolerance: float) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(float(a) - float(b)) <= tolerance


def analyze_lookahead(
    strategy: Strategy,
    df: pd.DataFrame,
    max_checks: int = 20,
    tolerance: float = 1e-9,
    min_samples: int = 50,
    seed: int = 42,
) -> dict[str, Any]:
    """检测策略信号是否存在前视偏差。

    参数
    ----
    max_checks: 最多检测的时点数量（对每个时点做一次全量截断重算，控制耗时）
    tolerance:  数值比较容差

    返回
    ----
    {
      "has_bias": bool, "biased_checks": n, "total_checks": n,
      "biased_rows": [{timestamp, full_signal, truncated_signal}],
      "verdict": str,
    }
    """
    n = len(df)
    if n < min_samples:
        return {
            "has_bias": False, "biased_checks": 0, "total_checks": 0,
            "biased_rows": [], "verdict": f"数据不足（{n} < {min_samples}），跳过检测",
        }
    full = strategy.generate_signals(df).astype(float)

    # 均匀采样检测时点（跳过前 1/4 数据，避免指标预热期干扰）
    lo = max(int(n * 0.25), 1)
    hi = n - 2
    if hi <= lo:
        lo, hi = 1, n - 2
    checks = np.linspace(lo, hi, min(max_checks, hi - lo + 1)).astype(int)
    checks = sorted(set(int(c) for c in checks))

    biased_rows: list[dict[str, Any]] = []
    for idx in checks:
        t = df.index[idx]
        truncated = df.iloc[: idx + 1]
        try:
            sig_t = strategy.generate_signals(truncated).astype(float)
        except Exception:  # noqa: BLE001
            continue
        if t not in sig_t.index:
            continue
        full_val = full.loc[t]
        trunc_val = sig_t.loc[t]
        if not _same(full_val, trunc_val, tolerance):
            biased_rows.append(
                {
                    "timestamp": str(t),
                    "full_signal": None if pd.isna(full_val) else float(full_val),
                    "truncated_signal": None if pd.isna(trunc_val) else float(trunc_val),
                }
            )

    has_bias = len(biased_rows) > 0
    rate = len(biased_rows) / max(1, len(checks))
    verdict = (
        "❌ 检测到前视偏差：信号依赖未来数据，回测结果不可信"
        if has_bias
        else "✅ 未检测到前视偏差：抽样时点信号在截断数据上保持一致"
    )
    return {
        "has_bias": has_bias,
        "biased_checks": len(biased_rows),
        "total_checks": len(checks),
        "bias_rate": round(rate, 4),
        "biased_rows": biased_rows[:100],
        "verdict": verdict,
    }
