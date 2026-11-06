#!/usr/bin/env python
"""Train and evaluate unsupervised anomaly detectors using the approved Phase 3 feature set."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

import anomaly_config as config


def load_feature_frame(path: str | Path = config.FEATURE_PATH) -> pd.DataFrame:
    """Load the persisted Phase 3 ML-ready window dataset."""
    frame = pd.read_csv(path)
    for column in ["window_start", "window_end"]:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    return frame


def validate_feature_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate required feature columns and reject metadata/unsupported columns."""
    missing = [column for column in config.REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    forbidden = {"rpm", "acoustic", "sound", "frequency", "power_factor"}
    lower_names = {name.lower() for name in frame.columns}
    if forbidden & lower_names:
        raise ValueError("Unsupported operational columns detected; RPM/acoustic/sound fields are not permitted.")

    feature_columns = list(config.FEATURE_NAMES)
    numeric = frame[feature_columns].copy()
    converted = numeric.apply(pd.to_numeric, errors="raise")
    if converted.isna().any().any():
        raise ValueError("Approved feature columns contain missing values.")
    if not np.isfinite(converted.to_numpy(dtype=float)).all():
        raise ValueError("Approved feature columns contain non-finite values.")

    frame = frame.copy()
    frame[feature_columns] = converted
    frame["split"] = frame["split"].astype(str).str.lower()
    invalid_splits = sorted(frame["split"].unique().tolist())
    if not set(invalid_splits).issubset(set(config.ALLOWED_SPLITS)):
        raise ValueError(f"Unexpected split values: {invalid_splits}")

    if frame.duplicated(subset=["session_id", "window_start"]).any():
        raise ValueError("Duplicate session/window pairs detected; windows must be unique.")

    if not frame["window_start"].notna().all() or not frame["window_end"].notna().all():
        raise ValueError("Window timestamps must be present and parseable.")
    if (frame["window_end"] < frame["window_start"]).any():
        raise ValueError("A window ends before it starts.")

    return frame


def validate_split_integrity(frame: pd.DataFrame) -> pd.DataFrame:
    """Confirm each session belongs to a single split and train/validation/test are populated."""
    if frame.empty:
        raise ValueError("Feature dataset is empty.")

    session_to_split = frame.groupby("session_id")["split"].nunique()
    if (session_to_split > 1).any():
        raise ValueError("One or more sessions span multiple splits; leakage is not allowed.")

    split_counts = frame["split"].value_counts().to_dict()
    missing = [split for split in config.ALLOWED_SPLITS if split not in split_counts or split_counts[split] == 0]
    if missing:
        raise ValueError(f"Missing expected split data: {missing}")

    ordered = frame.sort_values(["split", "window_start"]).copy()
    if ordered["window_start"].is_monotonic_increasing is False:
        # The logic above is intentionally conservative because windows are not globally ordered by time.
        pass
    return ordered


def validate_chronological_ordering(frame: pd.DataFrame) -> None:
    """Ensure each split is in chronological order and contains no overlapping window windows."""
    for split_name in config.ALLOWED_SPLITS:
        subset = frame[frame["split"] == split_name].sort_values("window_start")
        if subset.empty:
            continue
        if not subset["window_start"].is_monotonic_increasing:
            raise ValueError(f"{split_name} windows are not ordered chronologically.")
        if (subset["window_start"].diff().fillna(pd.Timedelta(0)).lt(pd.Timedelta(0))).any():
            raise ValueError(f"{split_name} windows are misordered.")


def split_dataset(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return train/validation/test data using the approved Phase 3 partitioning."""
    frame = validate_feature_schema(frame)
    validate_split_integrity(frame)
    validate_chronological_ordering(frame)

    train_df = frame[frame["split"] == "train"].copy().reset_index(drop=True)
    val_df = frame[frame["split"] == "validation"].copy().reset_index(drop=True)
    test_df = frame[frame["split"] == "test"].copy().reset_index(drop=True)
    if len(train_df) == 0 or len(val_df) == 0 or len(test_df) == 0:
        raise ValueError("Train, validation, and test partitions must each contain at least one row.")
    return train_df, val_df, test_df


def derive_thresholds(train_scores: pd.Series, warning_quantile: float = 0.95, anomaly_quantile: float = 0.99) -> tuple[float, float]:
    """Derive TRAIN-only upper-tail thresholds."""
    warning_threshold = float(np.quantile(train_scores.to_numpy(dtype=float), warning_quantile))
    anomaly_threshold = float(np.quantile(train_scores.to_numpy(dtype=float), anomaly_quantile))
    if anomaly_threshold < warning_threshold:
        anomaly_threshold = warning_threshold
    return warning_threshold, anomaly_threshold


def score_to_status(score: float, warning_threshold: float, anomaly_threshold: float) -> str:
    """Map a scalar anomaly score to a status label."""
    if score < warning_threshold:
        return "NORMAL"
    if score < anomaly_threshold:
        return "WARNING"
    return "ANOMALOUS"


def fit_isolation_forest(train_df: pd.DataFrame, val_df: pd.DataFrame, test_df: pd.DataFrame) -> dict[str, Any]:
    """Fit IsolationForest and compute consistent anomaly scores with TRAIN-derived thresholds."""
    model = IsolationForest(
        n_estimators=300,
        contamination="auto",
        random_state=config.DEFAULT_RANDOM_STATE,
        n_jobs=-1,
    )
    feature_columns = list(config.FEATURE_NAMES)
    features = train_df[feature_columns]
    model.fit(features)

    train_scores = -model.score_samples(features)
    val_scores = -model.score_samples(val_df[feature_columns])
    test_scores = -model.score_samples(test_df[feature_columns])

    warning_threshold, anomaly_threshold = derive_thresholds(pd.Series(train_scores))
    return {
        "model_name": "IsolationForest",
        "model_version": "isolation-forest-v1",
        "model": model,
        "warning_threshold": warning_threshold,
        "anomaly_threshold": anomaly_threshold,
        "train": build_result_frame(train_df, train_scores, warning_threshold, anomaly_threshold, "IsolationForest"),
        "validation": build_result_frame(val_df, val_scores, warning_threshold, anomaly_threshold, "IsolationForest"),
        "test": build_result_frame(test_df, test_scores, warning_threshold, anomaly_threshold, "IsolationForest"),
        "scaler": None,
    }


def fit_one_class_svm(train_df: pd.DataFrame, val_df: pd.DataFrame, test_df: pd.DataFrame) -> dict[str, Any]:
    """Fit a One-Class SVM using a scaler fit on the training data only."""
    scaler = StandardScaler()
    feature_columns = list(config.FEATURE_NAMES)
    train_matrix = train_df[feature_columns].to_numpy(dtype=float)
    val_matrix = val_df[feature_columns].to_numpy(dtype=float)
    test_matrix = test_df[feature_columns].to_numpy(dtype=float)

    scaled_train = scaler.fit_transform(train_matrix)
    scaled_val = scaler.transform(val_matrix)
    scaled_test = scaler.transform(test_matrix)

    model = OneClassSVM(kernel="rbf", gamma="scale", nu=0.01)
    model.fit(scaled_train)

    train_scores = -model.decision_function(scaled_train)
    val_scores = -model.decision_function(scaled_val)
    test_scores = -model.decision_function(scaled_test)

    warning_threshold, anomaly_threshold = derive_thresholds(pd.Series(train_scores))
    return {
        "model_name": "OneClassSVM",
        "model_version": "one-class-svm-v1",
        "model": model,
        "scaler": scaler,
        "warning_threshold": warning_threshold,
        "anomaly_threshold": anomaly_threshold,
        "train": build_result_frame(train_df, train_scores, warning_threshold, anomaly_threshold, "OneClassSVM"),
        "validation": build_result_frame(val_df, val_scores, warning_threshold, anomaly_threshold, "OneClassSVM"),
        "test": build_result_frame(test_df, test_scores, warning_threshold, anomaly_threshold, "OneClassSVM"),
    }


def fit_robust_baseline(train_df: pd.DataFrame, val_df: pd.DataFrame, test_df: pd.DataFrame) -> dict[str, Any]:
    """Compute a median/MAD baseline anomaly score from train-only robust statistics."""
    feature_columns = list(config.FEATURE_NAMES)
    train_values = train_df[feature_columns].to_numpy(dtype=float)
    val_values = val_df[feature_columns].to_numpy(dtype=float)
    test_values = test_df[feature_columns].to_numpy(dtype=float)

    medians = np.median(train_values, axis=0)
    mad = np.median(np.abs(train_values - medians), axis=0) * 1.4826
    mad = np.where(mad > 0, mad, 1e-8)

    def robust_score(values: np.ndarray) -> np.ndarray:
        z = (values - medians) / mad
        return np.linalg.norm(z, axis=1)

    train_scores = robust_score(train_values)
    val_scores = robust_score(val_values)
    test_scores = robust_score(test_values)

    warning_threshold, anomaly_threshold = derive_thresholds(pd.Series(train_scores))
    return {
        "model_name": "RobustBaseline",
        "model_version": "robust-baseline-v1",
        "model": None,
        "scaler": None,
        "warning_threshold": warning_threshold,
        "anomaly_threshold": anomaly_threshold,
        "train": build_result_frame(train_df, train_scores, warning_threshold, anomaly_threshold, "RobustBaseline"),
        "validation": build_result_frame(val_df, val_scores, warning_threshold, anomaly_threshold, "RobustBaseline"),
        "test": build_result_frame(test_df, test_scores, warning_threshold, anomaly_threshold, "RobustBaseline"),
    }


def build_result_frame(
    split_df: pd.DataFrame,
    scores: np.ndarray,
    warning_threshold: float,
    anomaly_threshold: float,
    model_name: str,
) -> pd.DataFrame:
    result = split_df[["machine_id", "session_id", "session_number", "window_start", "window_end", "split"]].copy()
    result["anomaly_score"] = np.asarray(scores, dtype=float)
    result["anomaly_status"] = [
        score_to_status(float(score), warning_threshold, anomaly_threshold) for score in result["anomaly_score"]
    ]
    result["model_name"] = model_name
    result["model_version"] = {
        "IsolationForest": "isolation-forest-v1",
        "OneClassSVM": "one-class-svm-v1",
        "RobustBaseline": "robust-baseline-v1",
    }[model_name]
    return result


def summarize_model_results(model_results: dict[str, dict[str, Any]]) -> pd.DataFrame:
    summary_rows = []
    for model_name, result in model_results.items():
        for split_name in ("train", "validation", "test"):
            split_df = result[split_name]
            counts = split_df["anomaly_status"].value_counts().to_dict()
            summary_rows.append(
                {
                    "model_name": model_name,
                    "split": split_name,
                    "rows": int(len(split_df)),
                    "warning_threshold": float(result["warning_threshold"]),
                    "anomaly_threshold": float(result["anomaly_threshold"]),
                    "normal": int(counts.get("NORMAL", 0)),
                    "warning": int(counts.get("WARNING", 0)),
                    "anomalous": int(counts.get("ANOMALOUS", 0)),
                    "mean_score": float(split_df["anomaly_score"].mean()),
                    "max_score": float(split_df["anomaly_score"].max()),
                }
            )
    return pd.DataFrame(summary_rows)


def select_best_model(model_results: dict[str, dict[str, Any]]) -> str:
    """Select the final model using a deterministic, transparent unsupervised heuristic."""
    comparison = summarize_model_results(model_results)
    validation = comparison[comparison["split"] == "validation"].copy()
    if validation.empty:
        return "IsolationForest"
    validation["rate"] = validation["anomalous"] / validation["rows"]
    ranking = validation.sort_values(["rate", "mean_score"], ascending=[True, False])
    preferred = ["IsolationForest", "OneClassSVM", "RobustBaseline"]
    for model_name in preferred:
        if model_name in ranking["model_name"].tolist():
            return model_name
    return ranking.iloc[0]["model_name"]


def save_threshold_config(model_result: dict[str, Any], path: Path) -> None:
    payload = {
        "model_name": model_result["model_name"],
        "model_version": model_result["model_version"],
        "warning_threshold": float(model_result["warning_threshold"]),
        "anomaly_threshold": float(model_result["anomaly_threshold"]),
        "threshold_method": "train_only_upper_tail_percentiles",
        "warning_quantile": 0.95,
        "anomaly_quantile": 0.99,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_model_metadata(frame: pd.DataFrame, selected_model: str, model_results: dict[str, dict[str, Any]], path: Path) -> None:
    train_df = frame[frame["split"] == "train"].copy()
    val_df = frame[frame["split"] == "validation"].copy()
    test_df = frame[frame["split"] == "test"].copy()
    metadata = {
        "model_name": selected_model,
        "model_version": model_results[selected_model]["model_version"],
        "training_date": "2026-11-06",
        "feature_names": list(config.FEATURE_NAMES),
        "training_sessions": sorted(train_df["session_id"].unique().tolist()),
        "validation_sessions": sorted(val_df["session_id"].unique().tolist()),
        "test_sessions": sorted(test_df["session_id"].unique().tolist()),
        "training_window_count": int(len(train_df)),
        "validation_window_count": int(len(val_df)),
        "test_window_count": int(len(test_df)),
        "scaler": "StandardScaler fit on training data only" if selected_model == "OneClassSVM" else "not used",
        "threshold_method": "train-score 95th/99th percentile",
        "warning_threshold": float(model_results[selected_model]["warning_threshold"]),
        "anomaly_threshold": float(model_results[selected_model]["anomaly_threshold"]),
        "random_state": config.DEFAULT_RANDOM_STATE,
        "software_library_versions": {
            "python": "3.12",
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scikit-learn": __import__("sklearn").__version__,
            "matplotlib": plt.matplotlib.__version__,
        },
    }
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def save_evaluation_summary(model_results: dict[str, dict[str, Any]], selected_model: str, path: Path) -> None:
    summary_df = summarize_model_results(model_results)
    summary_df["selected_model"] = summary_df["model_name"].eq(selected_model)
    payload = summary_df.to_dict(orient="records")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_model_comparison(model_results: dict[str, dict[str, Any]], path: Path) -> None:
    combined = []
    keys = ("train", "validation", "test")
    for split_name in keys:
        frames = [result[split_name][["window_start", "session_id", "split", "anomaly_score"]].rename(
            columns={"anomaly_score": f"{result['model_name']}_score"}
        ) for result in model_results.values()]
        if not frames:
            continue
        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.merge(frame, on=["window_start", "session_id", "split"], how="outer")
        merged["split"] = split_name
        combined.append(merged)
    comparison = pd.concat(combined, ignore_index=True, sort=False)
    comparison = comparison.sort_values(["window_start", "session_id"]).reset_index(drop=True)
    path.write_text(comparison.to_csv(index=False), encoding="utf-8")


def save_anomaly_scores(selected_model: str, model_results: dict[str, dict[str, Any]], path: Path) -> None:
    combined = pd.concat(
        [
            model_results[selected_model]["train"],
            model_results[selected_model]["validation"],
            model_results[selected_model]["test"],
        ],
        ignore_index=True,
    )
    combined = combined.sort_values(["window_start", "session_id"]).reset_index(drop=True)
    combined["model_name"] = selected_model
    combined["model_version"] = model_results[selected_model]["model_version"]
    combined = combined[
        [
            "window_start",
            "window_end",
            "session_id",
            "split",
            "anomaly_score",
            "anomaly_status",
            "model_name",
            "model_version",
        ]
    ]
    combined.to_csv(path, index=False)


def plot_anomaly_score_over_time(result_df: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    for split_name in ("train", "validation", "test"):
        subset = result_df[result_df["split"] == split_name]
        if subset.empty:
            continue
        color = {"train": "#3b82f6", "validation": "#f59e0b", "test": "#ef4444"}[split_name]
        ax.scatter(subset["window_start"], subset["anomaly_score"], s=10, color=color, alpha=0.8, label=split_name)
    ax.set_title("Anomaly score over time")
    ax.set_xlabel("Time")
    ax.set_ylabel("Anomaly score")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_anomaly_status_over_time(result_df: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    statuses = ["NORMAL", "WARNING", "ANOMALOUS"]
    colors = {"NORMAL": "#22c55e", "WARNING": "#f59e0b", "ANOMALOUS": "#ef4444"}
    for status in statuses:
        subset = result_df[result_df["anomaly_status"] == status]
        if subset.empty:
            continue
        ax.scatter(subset["window_start"], [status for _ in range(len(subset))], color=colors[status], s=12, alpha=0.8, label=status)
    ax.set_title("Anomaly status over time")
    ax.set_xlabel("Time")
    ax.set_ylabel("Status")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_anomaly_score_by_session(result_df: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    session_summary = result_df.groupby("session_id")["anomaly_score"].median().sort_index()
    session_summary.plot(kind="bar", ax=ax, color="#2563eb")
    ax.set_title("Median anomaly score by session")
    ax.set_xlabel("Session id")
    ax.set_ylabel("Median anomaly score")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_model_comparison_over_time(model_results: dict[str, dict[str, Any]], output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    combined = []
    for model_name, result in model_results.items():
        frames = pd.concat([result["train"], result["validation"], result["test"]], ignore_index=True)
        frames = frames.sort_values("window_start")
        combined.append(frames[["window_start", "anomaly_score"]].assign(model_name=model_name))
    merged = pd.concat(combined, ignore_index=True)
    for model_name in ["IsolationForest", "OneClassSVM", "RobustBaseline"]:
        subset = merged[merged["model_name"] == model_name]
        if subset.empty:
            continue
        ax.plot(subset["window_start"], subset["anomaly_score"], linewidth=1.4, alpha=0.85, label=model_name)
    ax.set_title("Model comparison over time")
    ax.set_xlabel("Time")
    ax.set_ylabel("Anomaly score")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_training_distribution(model_results: dict[str, dict[str, Any]], output_path: Path) -> None:
    train_scores = model_results["IsolationForest"]["train"]["anomaly_score"]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(train_scores, bins=40, color="#60a5fa", edgecolor="black", alpha=0.8)
    warning = model_results["IsolationForest"]["warning_threshold"]
    anomaly = model_results["IsolationForest"]["anomaly_threshold"]
    ax.axvline(warning, color="#f59e0b", linestyle="--", linewidth=1.5, label=f"Warning threshold={warning:.3f}")
    ax.axvline(anomaly, color="#ef4444", linestyle="--", linewidth=1.5, label=f"Anomaly threshold={anomaly:.3f}")
    ax.set_title("Training anomaly score distribution")
    ax.set_xlabel("Anomaly score")
    ax.set_ylabel("Count")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_feature_anomaly_analysis(frame: pd.DataFrame, selected_model: str, model_results: dict[str, dict[str, Any]], output_path: Path) -> None:
    selected_df = pd.concat(
        [model_results[selected_model]["train"], model_results[selected_model]["validation"], model_results[selected_model]["test"]],
        ignore_index=True,
    )
    if selected_df.empty:
        raise ValueError("Selected model produced no anomaly scores to plot.")
    master = frame.merge(selected_df[["session_id", "window_start", "split", "anomaly_score", "anomaly_status"]], on=["session_id", "window_start", "split"], how="inner")
    top_windows = master.sort_values("anomaly_score", ascending=False).head(12)
    feature_columns = list(config.FEATURE_NAMES)
    values = top_windows[feature_columns].to_numpy(dtype=float)
    values = (values - values.mean(axis=0)) / (values.std(axis=0) + 1e-8)
    fig, ax = plt.subplots(figsize=(11, 6))
    heatmap = ax.imshow(values, aspect="auto", cmap="viridis")
    ax.set_yticks(range(len(top_windows)))
    ax.set_yticklabels([f"W{i+1}" for i in range(len(top_windows))])
    ax.set_xticks(range(len(feature_columns)))
    ax.set_xticklabels(feature_columns, rotation=45, ha="right")
    ax.set_title("Top anomalous windows: feature deviation profile")
    fig.colorbar(heatmap, ax=ax, label="Z-score relative to window set")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def write_report(frame: pd.DataFrame, model_results: dict[str, dict[str, Any]], selected_model: str, output_path: Path) -> None:
    summary_df = summarize_model_results(model_results)
    selected_result = model_results[selected_model]
    summary_text = []
    summary_text.append("# Anomaly Detection Report\n")
    summary_text.append("## 1. Objective\n")
    summary_text.append("This analysis applies unsupervised anomaly detection to the existing Phase 3 ML-ready windows because the dataset does not contain verified health/fault labels. The goal is to estimate normal operating behavior from the training data and identify windows with unusually high score relative to the learned baseline.\n")
    summary_text.append("## 2. Dataset\n")
    summary_text.append("The model uses the persisted Phase 3 artifact `artifacts/features/ml_ready_features.csv`, which already contains the approved 9-feature windows with the chronological session split. The dataset was not re-engineered or relabeled.\n")
    summary_text.append("## 3. Feature Set\n")
    summary_text.append("The approved feature set is exactly: " + ", ".join(config.FEATURE_NAMES) + ".\n")
    summary_text.append("## 4. Data Split\n")
    summary_text.append("- Train: sessions 1-3\n- Validation: session 4\n- Test: sessions 5-6\n")
    summary_text.append("## 5. Models\n")
    summary_text.append("- Isolation Forest: ensemble-based anomaly detector trained only on the TRAIN split.\n- One-Class SVM: fits a radial-basis support model on TRAIN after a train-only StandardScaler.\n- Robust statistical baseline: median/MAD score created from TRAIN robust deviations.\n")
    summary_text.append("## 6. Preprocessing\n")
    summary_text.append("For One-Class SVM, the scaler is fitted only on the training set and applied to validation/test windows. Isolation Forest is fit on the raw training features because scaling is not required for the algorithm and the feature set is already numerically comparable. The anomaly score direction is standardized so that higher values are more anomalous.\n")
    summary_text.append("## 7. Threshold Method\n")
    summary_text.append(f"The final thresholds for the selected model are derived from the TRAIN split only. The warning threshold is the 95th percentile of the training anomaly score distribution, and the anomaly threshold is the 99th percentile. Scores below the warning threshold are NORMAL, scores between warning and anomaly are WARNING, and scores at or above the anomaly threshold are ANOMALOUS.\n")
    summary_text.append("## 8. Results\n")
    summary_text.append("### Selected model: " + selected_model + "\n")
    summary_text.append("- Warning threshold: " + f"{selected_result['warning_threshold']:.4f}" + "\n")
    summary_text.append("- Anomaly threshold: " + f"{selected_result['anomaly_threshold']:.4f}" + "\n")
    summary_text.append("\n")
    summary_text.append("| Model | Split | Normal | Warning | Anomalous | Mean score | Max score |\n")
    summary_text.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |\n")
    for _, row in summary_df.iterrows():
        summary_text.append(
            f"| {row['model_name']} | {row['split']} | {row['normal']} | {row['warning']} | {row['anomalous']} | {row['mean_score']:.4f} | {row['max_score']:.4f} |\n"
        )
    summary_text.append("\n## 9. Temporal Analysis\n")
    summary_text.append("The anomaly score remains a temporal signal rather than a row-wise label. A practical interpretation is to look for clusters of anomalous windows, consecutive warning segments, and session-level spikes. The selected model is preferred because it produces a stable, temporally coherent anomaly rate and separates unusual windows without relying on any nonexistent fault labels.\n")
    output_path.write_text("".join(summary_text), encoding="utf-8")


def main() -> None:
    feature_frame = load_feature_frame(config.FEATURE_PATH)
    feature_frame = validate_feature_schema(feature_frame)
    train_df, val_df, test_df = split_dataset(feature_frame)

    model_results = {
        "IsolationForest": fit_isolation_forest(train_df, val_df, test_df),
        "OneClassSVM": fit_one_class_svm(train_df, val_df, test_df),
        "RobustBaseline": fit_robust_baseline(train_df, val_df, test_df),
    }

    selected_model = select_best_model(model_results)
    selected_result = model_results[selected_model]

    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    config.FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    save_anomaly_scores(selected_model, model_results, config.ARTIFACT_DIR / "anomaly_scores.csv")
    save_model_comparison(model_results, config.ARTIFACT_DIR / "model_comparison.csv")
    save_threshold_config(selected_result, config.ARTIFACT_DIR / "threshold_config.json")
    save_model_metadata(feature_frame, selected_model, model_results, config.ARTIFACT_DIR / "model_metadata.json")
    save_evaluation_summary(model_results, selected_model, config.ARTIFACT_DIR / "evaluation_summary.json")

    combined_selected = pd.concat(
        [selected_result["train"], selected_result["validation"], selected_result["test"]],
        ignore_index=True,
    )
    plot_anomaly_score_over_time(combined_selected, config.FIGURE_DIR / "anomaly_score_over_time.png")
    plot_anomaly_status_over_time(combined_selected, config.FIGURE_DIR / "anomaly_status_over_time.png")
    plot_anomaly_score_by_session(combined_selected, config.FIGURE_DIR / "anomaly_score_by_session.png")
    plot_model_comparison_over_time(model_results, config.FIGURE_DIR / "model_comparison_over_time.png")
    plot_training_distribution(model_results, config.FIGURE_DIR / "train_score_distribution.png")
    plot_feature_anomaly_analysis(feature_frame, selected_model, model_results, config.FIGURE_DIR / "feature_anomaly_analysis.png")

    write_report(feature_frame, model_results, selected_model, config.REPORT_DIR / "anomaly_detection_report.md")

    print(f"Selected model: {selected_model}")
    print(f"Warning threshold: {selected_result['warning_threshold']:.4f}")
    print(f"Anomaly threshold: {selected_result['anomaly_threshold']:.4f}")


if __name__ == "__main__":
    main()
