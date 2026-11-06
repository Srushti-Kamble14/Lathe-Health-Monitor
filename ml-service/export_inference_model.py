#!/usr/bin/env python
"""Export the Phase 4 Isolation Forest for serving after verifying score parity."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

import anomaly_config as config


MODEL_PATH = config.ARTIFACT_DIR / "isolation_forest.joblib"
METADATA_PATH = config.ARTIFACT_DIR / "model_metadata.json"
THRESHOLD_PATH = config.ARTIFACT_DIR / "threshold_config.json"
SCORES_PATH = config.ARTIFACT_DIR / "anomaly_scores.csv"


def export_model() -> Path:
    """Recreate the exact Phase 4 estimator and verify it against saved scores."""
    features = pd.read_csv(config.FEATURE_PATH)
    if "split" not in features or not set(config.FEATURE_NAMES).issubset(features.columns):
        raise ValueError("The approved Phase 3 feature artifact is missing required columns.")

    feature_columns = list(config.FEATURE_NAMES)
    train = features.loc[features["split"].eq("train"), feature_columns]
    if train.empty:
        raise ValueError("The Phase 3 TRAIN split is empty.")

    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    thresholds = json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
    if metadata.get("feature_names") != feature_columns:
        raise ValueError("Phase 4 model metadata does not match the approved feature order.")
    if metadata.get("model_name") != "IsolationForest":
        raise ValueError("Phase 4 metadata does not select IsolationForest.")
    if thresholds.get("model_name") != "IsolationForest":
        raise ValueError("Phase 4 threshold configuration is not for IsolationForest.")
    if thresholds.get("model_version") != metadata.get("model_version"):
        raise ValueError("Phase 4 model and threshold versions do not match.")
    if (
        float(thresholds["warning_threshold"]) != float(metadata["warning_threshold"])
        or float(thresholds["anomaly_threshold"]) != float(metadata["anomaly_threshold"])
    ):
        raise ValueError("Phase 4 metadata and threshold configuration do not match.")

    estimator = IsolationForest(
        n_estimators=300,
        contamination="auto",
        random_state=config.DEFAULT_RANDOM_STATE,
        n_jobs=-1,
    )
    estimator.fit(train)

    saved_scores = pd.read_csv(SCORES_PATH)
    if saved_scores["model_name"].ne("IsolationForest").any():
        raise ValueError("The Phase 4 score artifact contains an unexpected model.")
    expected = saved_scores["anomaly_score"].to_numpy(dtype=float)
    ordered_features = features[feature_columns]
    observed = -estimator.score_samples(ordered_features)
    if len(expected) != len(observed) or not np.allclose(
        expected, observed, rtol=0, atol=1e-12
    ):
        raise RuntimeError(
            "The exported estimator does not reproduce the persisted Phase 4 scores."
        )

    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(estimator, MODEL_PATH)
    return MODEL_PATH


if __name__ == "__main__":
    print(f"Verified Phase 4 inference model exported: {export_model().name}")
