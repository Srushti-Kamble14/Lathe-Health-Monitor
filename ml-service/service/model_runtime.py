"""Load and run the persisted Phase 4 anomaly detector."""

from __future__ import annotations

import json
import math
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

from anomaly_config import FEATURE_NAMES


SERVICE_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = SERVICE_ROOT / "artifacts" / "anomaly_detection"


def score_to_status(score: float, warning_threshold: float, anomaly_threshold: float) -> str:
    if score < warning_threshold:
        return "NORMAL"
    if score < anomaly_threshold:
        return "WARNING"
    return "ANOMALOUS"


@dataclass(frozen=True)
class ModelRuntime:
    estimator: IsolationForest
    model_name: str
    model_version: str
    warning_threshold: float
    anomaly_threshold: float

    def score(self, features: dict[str, float]) -> dict[str, Any]:
        ordered = pd.DataFrame(
            [[features[name] for name in FEATURE_NAMES]],
            columns=list(FEATURE_NAMES),
        )
        score = float(-self.estimator.score_samples(ordered)[0])
        if not math.isfinite(score):
            raise RuntimeError("The anomaly model returned a non-finite score.")

        return {
            "success": True,
            "data": {
                "anomaly_score": score,
                "anomaly_status": score_to_status(
                    score, self.warning_threshold, self.anomaly_threshold
                ),
                "model_name": self.model_name,
                "model_version": self.model_version,
                "features_used": list(FEATURE_NAMES),
            },
        }


def load_runtime() -> ModelRuntime:
    """Load compatible artifacts once; fail startup rather than fitting a fallback."""
    model_path = ARTIFACT_ROOT / "isolation_forest.joblib"
    metadata_path = ARTIFACT_ROOT / "model_metadata.json"
    threshold_path = ARTIFACT_ROOT / "threshold_config.json"

    try:
        estimator = joblib.load(model_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        thresholds = json.loads(threshold_path.read_text(encoding="utf-8"))
        warning = float(thresholds["warning_threshold"])
        anomaly = float(thresholds["anomaly_threshold"])
        metadata_warning = float(metadata["warning_threshold"])
        metadata_anomaly = float(metadata["anomaly_threshold"])
        model_name = metadata["model_name"]
        model_version = metadata["model_version"]
        metadata_features = metadata["feature_names"]
        threshold_model = thresholds["model_name"]
        threshold_version = thresholds["model_version"]
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        EOFError,
        ImportError,
        pickle.UnpicklingError,
    ):
        raise RuntimeError(
            "Required anomaly inference artifacts are missing or invalid."
        ) from None

    if (
        not isinstance(estimator, IsolationForest)
        or getattr(estimator, "n_features_in_", None) != len(FEATURE_NAMES)
        or tuple(metadata_features) != FEATURE_NAMES
        or model_name != "IsolationForest"
        or threshold_model != model_name
        or threshold_version != model_version
        or not math.isfinite(warning)
        or not math.isfinite(anomaly)
        or warning != metadata_warning
        or anomaly != metadata_anomaly
        or warning >= anomaly
    ):
        raise RuntimeError("Anomaly inference artifacts are incompatible.")

    estimator_features = getattr(estimator, "feature_names_in_", None)
    if estimator_features is not None and tuple(estimator_features) != FEATURE_NAMES:
        raise RuntimeError("Anomaly inference feature order is incompatible.")

    return ModelRuntime(
        estimator=estimator,
        model_name=model_name,
        model_version=model_version,
        warning_threshold=warning,
        anomaly_threshold=anomaly,
    )
