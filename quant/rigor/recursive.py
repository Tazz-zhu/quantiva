"""递归漂移 / 回测-实盘一致性检测 —— freqtrade recursive-analysis 思想移植。

问题：回测时指标用"全量历史"向量化计算；实盘时指标只能基于"最近一段
预热窗口"滚动计算。若指标/信号对初始化历史敏感（如窗口内重算的 EMA、
rolling.apply 内嵌递归），两者会在同一时点给出不同取值 —— 回测与实盘
信号漂移，导致回测收益不可复现。

检测方法：对抽样时点 t，比较
  (a) 全量数据上的信号值（回测视角）
  (b) 以 t 为终点、长度为 warmup 的滚动窗口上的信号值（实盘视角）
统计差异率，并给出漂移结论。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant.strategy.base import Strategy


def analyze_recursive(
    strategy: Strategy,
    df: pd.DataFrame,
    warmup: int = 200,
    max_checks: int = 20,
    tolerance: float = 1e-6,
    min_samples: int = 300,
    seed: int = 42,
) -> dict[str, Any]:
    """检测信号的回测/实盘递归漂移风险。

    参数
    ----
    warmup:      模拟实盘使用的预热窗口长度（与 live.warmup_bars 对应）
    max_checks:  抽样时点数量

    返回
    ----
    {
      "has_drift": bool, "drifted_checks": n, "total_checks": n,
      "drift_rate": float, "drifted_rows": [...], "verdict": str,
    }
    """
    n = len(df)
    if n < min_samples:
        return {
            "has_drift": False, "drifted_checks": 0, "total_checks": 0,
            "drifted_rows": [], "verdict": f"数据不足（{n} < {min_samples}），跳过检测",
        }
    warmup = max(50, min(int(warmup), n // 2))
    full = strategy.generate_signals(df).astype(float)

    lo = max(int(n * 0.4), warmup + 1)
    hi = n - 2
    if hi <= lo:
        lo, hi = warmup + 1, n - 2
    checks = np.linspace(lo, hi, min(max_checks, max(1, hi - lo + 1))).astype(int)
    checks = sorted(set(int(c) for c in checks))

    drifted_rows: list[dict[str, Any]] = []
    for idx in checks:
        t = df.index[idx]
        window = df.iloc[idx - warmup + 1 : idx + 1]
        try:
            sig_w = strategy.generate_signals(window).astype(float)
        except Exception:  # noqa: BLE001
            continue
        if t not in sig_w.index:
            continue
        full_val = full.loc[t]
        win_val = sig_w.loc[t]
        if not _same(full_val, win_val, tolerance):
            drifted_rows.append(
                {
                    "timestamp": str(t),
                    "full_signal": None if pd.isna(full_val) else float(full_val),
                    "window_signal": None if pd.isna(win_val) else float(win_val),
                }
            )

    has_drift = len(drifted_rows) > 0
    rate = len(drifted_rows) / max(1, len(checks))
    if rate >= 0.2:
        level = "高"
        verdict = "❌ 递归漂移风险高：回测与实盘信号可能显著不一致，建议增加预热或改用因果指标"
    elif rate > 0:
        level = "中"
        verdict = "⚠️ 存在一定递归漂移：部分时点信号不一致，实盘前请加长预热窗口验证"
    else:
        level = "低"
        verdict = "✅ 递归漂移风险低：抽样时点信号在滚动窗口与全量数据上一致"
    return {
        "has_drift": has_drift,
        "drifted_checks": len(drifted_rows),
        "total_checks": len(checks),
        "drift_rate": round(rate, 4),
        "risk_level": level,
        "drifted_rows": drifted_rows[:100],
        "warmup": warmup,
        "verdict": verdict,
    }


def _same(a: float, b: float, tolerance: float) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(float(a) - float(b)) <= tolerance
