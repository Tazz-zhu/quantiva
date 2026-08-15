"""FreqAIPipeline —— FreqAI 风格训练 / 滚动样本外预测 / 回测 / 实盘推理。

回测方法（与 freqtrade FreqAI backtesting 一致）：
1. 构造特征 + 标签
2. 用带 purge/embargo 的滚动窗口切分
3. 每折：仅用该折之前的数据训练模型 → 预测该折测试窗口
4. 拼接全部样本外预测（保证全程无泄漏）
5. 把预测列合并回 OHLCV，交给 FreqAIStrategy 生成信号并回测
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from quant.freqai.features import build_features
from quant.freqai.models import train_model, predict_model
from quant.freqai.split import walk_forward_windows
from quant.freqai.targets import build_targets


class FreqAIPipeline:
    """FreqAI 编排管线。"""

    def __init__(
        self,
        model_name: str = "random_forest",
        kind: str = "regression",
        horizon: int = 5,
        lookbacks: tuple[int, ...] = (5, 10, 20, 50),
        include_volume: bool = True,
        purge: int | None = None,
        embargo: int = 0,
        seed: int = 42,
        model_dir: str = "data/freqai",
        **model_kwargs: Any,
    ):
        self.model_name = model_name
        self.kind = kind
        self.horizon = int(horizon)
        self.lookbacks = tuple(lookbacks)
        self.include_volume = include_volume
        self.purge = horizon if purge is None else int(purge)
        self.embargo = int(embargo)
        self.seed = int(seed)
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.model_kwargs = dict(model_kwargs or {})

    # ------------------------------------------------------------------ #
    def build_dataset(self, df: pd.DataFrame, corr_data: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
        """构造特征 + 标签数据集（与 OHLCV 对齐）。corr_data 为关联对 K 线。"""
        feat = build_features(df, lookbacks=self.lookbacks, include_volume=self.include_volume, corr_data=corr_data)
        tgt = build_targets(df, horizon=self.horizon, kind=self.kind, scale_by_atr=(self.kind == "regression"))
        out = df.copy()
        for c in feat.columns:
            out[c] = feat[c]
        out["target"] = tgt["target"]
        return out

    # ------------------------------------------------------------------ #
    def backtest(
        self,
        df: pd.DataFrame,
        n_windows: int = 5,
        test_size: int | None = None,
        min_train: int = 100,
        progress: Callable[[int, int], None] | None = None,
        corr_data: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, Any]:
        """滚动样本外预测回测：返回含 freqai_pred / freqai_prob 列的 df 与元数据。"""
        data = self.build_dataset(df, corr_data=corr_data)
        n = len(data)
        if n < min_train + 50:
            raise ValueError(f"数据量不足（{n}），FreqAI 回测至少需要 {min_train + 50} 根 K 线")

        feature_cols = [c for c in data.columns if c not in ("target", "open", "high", "low", "close", "volume")]
        pred = pd.Series(np.nan, index=data.index, dtype=float)
        prob = pd.Series(np.nan, index=data.index, dtype=float)
        windows_meta: list[dict[str, Any]] = []
        total = n_windows
        done = 0

        for train_idx, test_idx in walk_forward_windows(
            n, n_windows=n_windows, test_size=test_size,
            purge=self.purge, embargo=self.embargo, min_train=min_train,
        ):
            tr = data.iloc[train_idx]
            te = data.iloc[test_idx]
            X_tr = tr[feature_cols]
            y_tr = tr["target"]
            mask = X_tr.notna().all(axis=1) & y_tr.notna()
            X_tr, y_tr = X_tr[mask], y_tr[mask]
            if len(X_tr) < min_train:
                done += 1
                if progress:
                    progress(done, total)
                continue
            try:
                bundle = train_model(
                    self.model_name, self.kind, X_tr, y_tr,
                    seed=self.seed, **self.model_kwargs,
                )
                out = predict_model(bundle, te[feature_cols])
                pred.iloc[test_idx] = out["prediction"]
                if out["probability_up"] is not None:
                    prob.iloc[test_idx] = out["probability_up"]
                windows_meta.append({
                    "train_rows": int(len(X_tr)),
                    "test_rows": int(len(te)),
                    "train_score": bundle["train_score"],
                    "importance_top": dict(
                        sorted(bundle["importance"].items(), key=lambda kv: -abs(kv[1]))[:10]
                    ),
                })
            except Exception as exc:  # noqa: BLE001
                windows_meta.append({"train_rows": int(len(X_tr)), "test_rows": int(len(te)), "error": str(exc)[:150]})
            done += 1
            if progress:
                progress(done, total)

        result = data.copy()
        result["freqai_pred"] = pred
        result["freqai_prob"] = prob

        # 预测质量：样本外预测与真实前瞻收益的相关性
        valid = result[["freqai_pred", "target"]].replace([np.inf, -np.inf], np.nan).dropna()
        corr = float(valid["freqai_pred"].corr(valid["target"])) if len(valid) > 10 else None
        pred_trades = int(valid["freqai_pred"].notna().sum())

        return {
            "data": result,
            "prediction_coverage": float(result["freqai_pred"].notna().mean()),
            "correlation": round(corr, 4) if corr is not None else None,
            "windows": windows_meta,
            "n_windows": len(windows_meta),
            "horizon": self.horizon,
            "model": self.model_name,
            "kind": self.kind,
        }

    # ------------------------------------------------------------------ #
    def train(
        self,
        df: pd.DataFrame,
        train_ratio: float = 0.8,
        name: str | None = None,
        corr_data: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, Any]:
        """在最近 train_ratio 数据上训练最终模型并持久化。"""
        data = self.build_dataset(df, corr_data=corr_data)
        split = int(len(data) * train_ratio)
        tr = data.iloc[:split]
        feature_cols = [c for c in data.columns if c not in ("target", "open", "high", "low", "close", "volume")]
        X = tr[feature_cols]
        y = tr["target"]
        mask = X.notna().all(axis=1) & y.notna()
        X, y = X[mask], y[mask]
        if len(X) < 50:
            raise ValueError(f"有效训练样本不足：{len(X)} < 50")

        bundle = train_model(self.model_name, self.kind, X, y, seed=self.seed, **self.model_kwargs)
        name = name or f"{self.model_name}_{int(time.time())}"
        path = self.save_model(bundle, name)
        # 样本内评估
        eval_pred = predict_model(bundle, tr[feature_cols].iloc[mask.values])["prediction"]
        eval_y = y.values
        return {
            "name": name,
            "path": str(path),
            "train_score": bundle["train_score"],
            "train_rows": int(len(X)),
            "importance_top": dict(sorted(bundle["importance"].items(), key=lambda kv: -abs(kv[1]))[:15]),
            "model": self.model_name,
            "kind": self.kind,
            "horizon": self.horizon,
        }

    # ------------------------------------------------------------------ #
    def predict_latest(self, df: pd.DataFrame, name: str | None = None, corr_data: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
        """对最新一根 K 线做实盘推理。

        name 指定模型名；否则加载最新的已保存模型。
        """
        bundle = self.load_model(name) if name else self.load_latest_model()
        if bundle is None:
            raise ValueError("未找到已训练的 FreqAI 模型，请先执行训练")
        data = self.build_dataset(df, corr_data=corr_data)
        feature_cols = [c for c in data.columns if c not in ("target", "open", "high", "low", "close", "volume")]
        out = predict_model(bundle, data[feature_cols].tail(1))
        return {
            "timestamp": str(data.index[-1]),
            "prediction": float(out["prediction"][0]),
            "probability_up": float(out["probability_up"][0]) if out["probability_up"] is not None else None,
            "model": bundle.get("model_name", self.model_name),
        }

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #
    def save_model(self, bundle: dict[str, Any], name: str) -> Path:
        try:
            import joblib
        except ImportError:  # pragma: no cover
            raise RuntimeError("需要 joblib 才能保存模型")
        folder = self.model_dir / name
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle["model"], folder / "model.joblib")
        meta = {
            "model_name": self.model_name,
            "kind": bundle["kind"],
            "feature_names": bundle["feature_names"],
            "horizon": self.horizon,
            "train_score": bundle["train_score"],
            "importance": bundle.get("importance", {}),
            "seed": self.seed,
        }
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return folder

    def load_model(self, name: str) -> dict[str, Any] | None:
        try:
            import joblib
        except ImportError:  # pragma: no cover
            return None
        folder = self.model_dir / name
        model_file = folder / "model.joblib"
        if not model_file.exists():
            return None
        model = joblib.load(model_file)
        meta = {}
        meta_file = folder / "meta.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        return {
            "model": model,
            "feature_names": meta.get("feature_names"),
            "kind": meta.get("kind", self.kind),
            "model_name": meta.get("model_name", name),
            "horizon": meta.get("horizon", self.horizon),
            "train_score": meta.get("train_score"),
            "importance": meta.get("importance", {}),
        }

    def load_latest_model(self) -> dict[str, Any] | None:
        if not self.model_dir.exists():
            return None
        folders = sorted(
            [p for p in self.model_dir.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for folder in folders:
            bundle = self.load_model(folder.name)
            if bundle is not None:
                return bundle
        return None

    def list_models(self) -> list[dict[str, Any]]:
        if not self.model_dir.exists():
            return []
        out = []
        for folder in sorted(self.model_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not folder.is_dir():
                continue
            meta_file = folder / "meta.json"
            meta = {}
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            out.append({
                "name": folder.name,
                "model": meta.get("model_name", folder.name),
                "kind": meta.get("kind", ""),
                "horizon": meta.get("horizon"),
                "train_score": meta.get("train_score"),
                "created": time.strftime("%Y-%m-%d %H:%M", time.localtime(folder.stat().st_mtime)),
            })
        return out
