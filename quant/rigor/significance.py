"""统计显著性工具（抗过拟合核心）。

实现：
- bootstrap_p_value:  平稳 bootstrap 检验夏普 > 0 的 p 值
- deflated_sharpe:    Bailey & Lopez de Prado 缩水夏普（校正多次试验选择偏差）
- permutation_test:   交易收益置换检验（策略能力 vs 随机）
- parameter_stability: Top-K 参数稳定性 / 敏感性分析
- strategy_verdict:   综合判定（是否过拟合 / 是否可上线）
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import pandas as pd

_EULER_GAMMA = 0.5772156649015329


def _sharpe_from_returns(returns: np.ndarray, ppy: float = 8760.0) -> float:
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        return 0.0
    sd = float(r.std(ddof=1))
    if sd <= 0:
        return 0.0
    return float(r.mean() / sd * math.sqrt(ppy))


def bootstrap_p_value(
    returns: Sequence[float],
    n_boot: int = 2000,
    seed: int = 42,
    periods_per_year: float = 8760.0,
) -> dict[str, Any]:
    """平稳块 bootstrap 检验策略夏普 > 0。

    对收益率序列做块重采样（块长几何分布，期望 = block_len），
    重放 N 次得到夏普的零假设分布，p 值 = P(Sharpe_boot <= 0)。

    返回 {"sharpe", "p_value", "n_boot", "ci_low", "ci_high", "significant"}
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 10:
        return {"sharpe": 0.0, "p_value": 1.0, "n_boot": n_boot, "ci_low": 0.0, "ci_high": 0.0,
                "significant": False, "reason": "样本过少"}

    sharpe_obs = _sharpe_from_returns(r, periods_per_year)
    rng = np.random.default_rng(seed)
    block_len = max(5, int(math.sqrt(n)))
    boot_sharpes = np.empty(n_boot)
    for b in range(n_boot):
        # 平稳 bootstrap：从原始序列随机起点按几何块长抽样
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n)
            blen = rng.geometric(1.0 / block_len)
            idx.extend((start + np.arange(blen)) % n)
        sample = r[idx[:n]]
        boot_sharpes[b] = _sharpe_from_returns(sample, periods_per_year)

    p_value = float((boot_sharpes <= 0.0).mean())
    ci_low, ci_high = float(np.percentile(boot_sharpes, 2.5)), float(np.percentile(boot_sharpes, 97.5))
    return {
        "sharpe": round(sharpe_obs, 4),
        "p_value": round(p_value, 4),
        "n_boot": n_boot,
        "ci_low": round(ci_low, 4),
        "ci_high": round(ci_high, 4),
        "significant": bool(p_value < 0.05),
    }


def deflated_sharpe(
    returns: Sequence[float],
    n_trials: int = 1,
    seed: int = 42,
    periods_per_year: float = 8760.0,
) -> dict[str, Any]:
    """Bailey & Lopez de Prado (2014) 缩水夏普比率。

    校正参数寻优中"多次试验挑最优"带来的选择偏差：
    - SR*      : 观测夏普
    - E[maxSR] : 零假设下 N 次独立试验期望最大夏普
    - V        : 夏普估计方差（含偏度/峰度修正）
    - DSR      : (SR* - E[maxSR]) / sqrt(V)
    - p 值     : 标准正态单尾

    返回 {"deflated_sharpe", "expected_max_sharpe", "p_value", "significant", ...}
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 10:
        return {"deflated_sharpe": 0.0, "expected_max_sharpe": 0.0, "p_value": 1.0,
                "significant": False, "reason": "样本过少"}

    sharpe = _sharpe_from_returns(r, periods_per_year)
    skew = float(pd.Series(r).skew()) if n > 2 else 0.0
    kurt = float(pd.Series(r).kurtosis()) if n > 3 else 3.0  # pandas kurtosis 已超额（excess）

    # 夏普估计方差（Bailey & LdP eq.）
    var_sr = (1.0 - skew * sharpe + ((kurt + 3.0) - 1.0) / 4.0 * sharpe ** 2) / (n - 1)
    var_sr = max(var_sr, 1e-12)
    sd_sr = math.sqrt(var_sr)

    n_trials = max(1, int(n_trials))
    if n_trials == 1:
        e_max = 0.0
    else:
        z1 = 1.0 - 1.0 / n_trials
        z2 = 1.0 - 1.0 / (n_trials * math.e)
        # 标准正态分位数近似
        e_max = math.sqrt(var_sr) * (
            (1.0 - _EULER_GAMMA) * _norm_ppf(z1) + _EULER_GAMMA * _norm_ppf(z2)
        )

    dsr = (sharpe - e_max) / sd_sr
    p_value = 1.0 - _norm_cdf(dsr)
    return {
        "sharpe": round(sharpe, 4),
        "n_trials": n_trials,
        "expected_max_sharpe": round(e_max, 4),
        "sr_variance": round(var_sr, 6),
        "deflated_sharpe": round(dsr, 4),
        "p_value": round(float(p_value), 4),
        "significant": bool(p_value < 0.05),
    }


def permutation_test(
    trade_returns: Sequence[float],
    n_perm: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """交易收益置换检验。

    将每笔交易收益随机置换符号/位置，比较观测均值在随机分布中的位置，
    检验策略能力是否显著区别于随机交易。

    返回 {"observed_mean", "p_value", "n_perm", "significant", ...}
    """
    r = np.asarray(trade_returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 5:
        return {"observed_mean": 0.0, "p_value": 1.0, "n_perm": n_perm,
                "significant": False, "reason": "交易样本过少"}

    obs_mean = float(r.mean())
    rng = np.random.default_rng(seed)
    perm_means = np.empty(n_perm)
    for p in range(n_perm):
        # 随机置换收益位置（打乱交易顺序，等价于随机入场时点）
        perm = rng.permutation(r)
        perm_means[p] = perm.mean()
    p_value = float((perm_means >= obs_mean).mean())
    return {
        "observed_mean": round(obs_mean, 6),
        "mean_random": round(float(perm_means.mean()), 6),
        "p_value": round(p_value, 4),
        "n_perm": n_perm,
        "significant": bool(p_value < 0.05),
    }


def parameter_stability(results: list[dict], top_k: int = 10) -> dict[str, Any]:
    """Top-K 参数稳定性分析。

    观察最优 K 个组合：
    - 目标值离散度（最优与第 K 优的差距）
    - 参数唯一取值数（越小越稳定/越集中在同一区域）
    - 平台大小（目标值在最优值一定比例内的组合数）

    返回 {"top_k", "spread", "distinct_param_fraction", "plateau_size", "verdict", ...}
    """
    valid = [r for r in results if r.get("metrics") and r.get("target_value") is not None]
    if not valid:
        return {"top_k": 0, "spread": 0.0, "distinct_param_fraction": 1.0,
                "plateau_size": 0, "verdict": "无有效结果"}
    valid = sorted(valid, key=lambda r: r["target_value"], reverse=True)
    top = valid[: max(1, top_k)]
    values = [r["target_value"] for r in top]
    best = values[0]
    worst = values[-1]
    span = best - worst if best != worst else 0.0
    spread = abs(span) / (abs(best) + 1e-9) if best != 0 else 0.0

    # 参数唯一取值数占比（对所有参数取平均）
    param_sets = [tuple(sorted((r.get("params") or {}).items())) for r in top]
    distinct = len(set(param_sets))
    distinct_fraction = distinct / max(1, len(top))

    # 平台：目标值在最优值 95% 以内的组合数
    threshold = best * 0.95 if best > 0 else best * 1.05
    plateau = 0
    for v in values:
        if best > 0 and v >= threshold:
            plateau += 1
        elif best <= 0 and v <= threshold:
            plateau += 1
    plateau = max(plateau, 1)

    if spread > 0.5:
        verdict = "不稳定：最优组合显著优于其余组合，参数敏感，易过拟合"
    elif distinct_fraction > 0.7:
        verdict = "较稳定：Top 参数分散但目标接近，存在多个等价解"
    else:
        verdict = "稳定：Top 参数聚集，目标差异小，过拟合风险低"
    return {
        "top_k": len(top),
        "best": best,
        "worst": worst,
        "spread": round(spread, 4),
        "distinct_param_fraction": round(distinct_fraction, 4),
        "plateau_size": plateau,
        "verdict": verdict,
    }


def strategy_verdict(
    is_metrics: dict | None,
    oos_metrics: dict | None,
    significance: dict | None = None,
    stability: dict | None = None,
) -> dict[str, Any]:
    """综合判定策略是否通过抗过拟合检查。

    规则：
    1. 样本外必须有正收益
    2. 样本外夏普未显著劣化（>= 样本内 50%）
    3. 显著性 p 值 < 0.05（若提供）
    4. 参数稳定性非"不稳定"（若提供）
    """
    checks: list[dict[str, Any]] = []

    if oos_metrics is not None:
        oos_ret = float(oos_metrics.get("total_return", 0) or 0)
        checks.append({
            "name": "样本外正收益",
            "ok": oos_ret > 0,
            "detail": f"样本外收益 {oos_ret * 100:.2f}%",
        })
        is_sharpe = float((is_metrics or {}).get("sharpe", 0) or 0)
        oos_sharpe = float(oos_metrics.get("sharpe", 0) or 0)
        if is_sharpe > 0:
            ok = oos_sharpe >= is_sharpe * 0.5
            checks.append({
                "name": "样本外夏普未严重劣化",
                "ok": bool(ok),
                "detail": f"样本内 {is_sharpe:.2f} → 样本外 {oos_sharpe:.2f}",
            })
    if significance is not None:
        pv = float(significance.get("p_value", 1.0) or 1.0)
        checks.append({
            "name": "统计显著（p<0.05）",
            "ok": bool(significance.get("significant", pv < 0.05)),
            "detail": f"p 值 = {pv:.4f}",
        })
    if stability is not None:
        verdict = stability.get("verdict", "")
        ok = "不稳定" not in verdict
        checks.append({"name": "参数稳定性", "ok": bool(ok), "detail": verdict})

    passed = all(c["ok"] for c in checks) if checks else False
    return {
        "passed": passed,
        "checks": checks,
        "summary": "✅ 通过抗过拟合检查" if passed else "⚠️ 未通过抗过拟合检查，不建议直接上实盘",
    }


# --------------------------------------------------------------------- #
# 标准正态工具
# --------------------------------------------------------------------- #
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """标准正态分位数的有理近似（Abramowitz & Stegun 26.2.23）。"""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    if p < 0.5:
        return -_norm_ppf(1.0 - p)
    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2, c3, c4, c5 = 2.515517, 0.802853, 0.010328, 1.432788, 0.189269, 0.001308
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t ** 2) / (1.0 + d1 * t + d2 * t ** 2 + d3 * t ** 3)
