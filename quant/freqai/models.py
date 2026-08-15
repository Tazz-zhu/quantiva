"""模型注册表 —— sklearn 基础模型 + 可选 LightGBM/XGBoost。

每个模型封装 train/predict，返回预测值、概率（分类时）、特征重要性。
"""
from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np
import pandas as pd


def _has(pkg: str) -> bool:
    return importlib.util.find_spec(pkg) is not None


def _make_model(model_name: str, kind: str, seed: int = 42, **kwargs: Any):
    model_name = model_name.lower()
    params = dict(kwargs or {})
    params.setdefault("random_state", seed)
    params.setdefault("n_jobs", -1)

    if kind == "classification":
        if model_name == "logistic":
            from sklearn.linear_model import LogisticRegression
            params.setdefault("max_iter", 1000)
            return LogisticRegression(**params)
        if model_name == "random_forest":
            from sklearn.ensemble import RandomForestClassifier
            return RandomForestClassifier(**params)
        if model_name == "extra_trees":
            from sklearn.ensemble import ExtraTreesClassifier
            return ExtraTreesClassifier(**params)
        if model_name == "gradient_boosting":
            from sklearn.ensemble import GradientBoostingClassifier
            params.pop("n_jobs", None)
            return GradientBoostingClassifier(**params)
        if model_name == "lightgbm" and _has("lightgbm"):
            from lightgbm import LGBMClassifier
            return LGBMClassifier(**params)
        if model_name == "xgboost" and _has("xgboost"):
            from xgboost import XGBClassifier
            return XGBClassifier(**params)
        # 默认
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(**params)
    else:
        if model_name == "random_forest":
            from sklearn.ensemble import RandomForestRegressor
            return RandomForestRegressor(**params)
        if model_name == "extra_trees":
            from sklearn.ensemble import ExtraTreesRegressor
            return ExtraTreesRegressor(**params)
        if model_name == "gradient_boosting":
            from sklearn.ensemble import GradientBoostingRegressor
            params.pop("n_jobs", None)
            return GradientBoostingRegressor(**params)
        if model_name == "ridge":
            from sklearn.linear_model import Ridge
            params.pop("n_jobs", None)
            return Ridge(**params)
        if model_name == "lightgbm" and _has("lightgbm"):
            from lightgbm import LGBMRegressor
            return LGBMRegressor(**params)
        if model_name == "xgboost" and _has("xgboost"):
            from xgboost import XGBRegressor
            return XGBRegressor(**params)
        from sklearn.ensemble import RandomForestRegressor
        return RandomForestRegressor(**params)


def train_model(
    model_name: str,
    kind: str,
    features: pd.DataFrame,
    target: pd.Series,
    seed: int = 42,
    **kwargs: Any,
) -> dict[str, Any]:
    """训练模型并返回封装字典。

    返回 {"model", "feature_names", "kind", "train_score", "importance"}
    """
    X = features.astype(float)
    y = target.astype(float)
    # 丢弃含 NaN 的行
    mask = X.notna().all(axis=1) & y.notna()
    X = X[mask]
    y = y[mask]
    if len(X) < 30:
        raise ValueError(f"有效训练样本不足：{len(X)} < 30")

    model = _make_model(model_name, kind, seed=seed, **kwargs)
    model.fit(X, y)

    importance = _feature_importance(model, X.columns)
    train_score = float(model.score(X, y)) if hasattr(model, "score") else None
    return {
        "model": model,
        "feature_names": list(X.columns),
        "kind": kind,
        "train_score": train_score,
        "importance": importance,
    }


def predict_model(bundle: dict[str, Any], features: pd.DataFrame) -> dict[str, Any]:
    """用已训练模型预测。

    返回 {"prediction": np.ndarray, "probability_up": np.ndarray | None, "importance": dict}
    """
    model = bundle["model"]
    kind = bundle.get("kind", "regression")
    X = features.reindex(columns=bundle["feature_names"]).astype(float)
    X = X.fillna(0.0)

    if kind == "classification":
        proba = model.predict_proba(X)
        up_col = model.classes_.tolist().index(1) if 1 in model.classes_ else 1
        prob_up = proba[:, up_col]
        pred = (prob_up >= 0.5).astype(float)
        return {"prediction": pred, "probability_up": prob_up, "importance": bundle.get("importance")}
    pred = model.predict(X)
    return {"prediction": pred, "probability_up": None, "importance": bundle.get("importance")}


def _feature_importance(model: Any, columns: pd.Index) -> dict[str, float]:
    try:
        imp = getattr(model, "feature_importances_", None)
        if imp is not None:
            vals = np.asarray(imp, dtype=float)
            return {str(c): round(float(v), 6) for c, v in zip(columns, vals)}
    except Exception:  # noqa: BLE001
        pass
    try:
        coef = getattr(model, "coef_", None)
        if coef is not None:
            coef = np.asarray(coef).ravel()
            return {str(c): round(float(v), 6) for c, v in zip(columns, coef)}
    except Exception:  # noqa: BLE001
        pass
    return {}


AVAILABLE_MODELS: dict[str, str] = {
    "random_forest": "随机森林（sklearn）",
    "extra_trees": "极端随机树（sklearn）",
    "gradient_boosting": "梯度提升树（sklearn）",
    "ridge": "岭回归（仅回归）",
    "logistic": "逻辑回归（仅分类）",
}
if _has("lightgbm"):
    AVAILABLE_MODELS["lightgbm"] = "LightGBM（已安装）"
if _has("xgboost"):
    AVAILABLE_MODELS["xgboost"] = "XGBoost（已安装）"


def create_model(model_name: str, kind: str, seed: int = 42, **kwargs: Any) -> dict[str, Any]:
    """创建未训练的模型 bundle（供 pipeline 使用）。"""
    return {
        "model": _make_model(model_name, kind, seed=seed, **kwargs),
        "feature_names": None,
        "kind": kind,
        "train_score": None,
        "importance": {},
    }
