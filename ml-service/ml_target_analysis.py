#!/usr/bin/env python
"""Explore time-aware operating regimes and unlabeled anomalies in the supplied CSV."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler, StandardScaler


DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "Raw data CNC LATHE MACHINE.csv"
DEFAULT_REPORT = Path(__file__).resolve().parent / "reports" / "ml_target_strategy.md"
DEFAULT_FIGURES = Path(__file__).resolve().parent / "reports" / "figures" / "target_analysis"

SESSION_GAP_SECONDS = 30
NOMINAL_INTERVAL_SECONDS = 3
ROLLING_WINDOW_SAMPLES = 60
ROLLING_MIN_PERIODS = 20
BLOCK_SAMPLES = 20
BASELINE_BLOCK_SAMPLES = 600
TRAINING_SESSIONS_HELD_OUT = 2
IFOREST_RANDOM_STATE = 42

MODEL_FEATURES = [
    "mean_current",
    "current_std",
    "current_imbalance",
    "mean_voltage",
    "voltage_std",
    "voltage_imbalance",
    "vibration_rms",
    "vibration_std",
    "vibration_peak",
    "vibration_peak_to_peak",
    "crest_factor",
    "tool_temp",
    "ambient_temp",
    "tool_temp_rate",
    "temperature_difference",
]
REGIME_FEATURES = [
    "mean_current",
    "current_std",
    "vibration_rms",
    "tool_temp",
]
SENSOR_COLUMNS = [
    "c1", "c2", "c3",
    "v1", "v2", "v3",
    "accx", "accy", "accz",
    "tool_temp", "ambient_temp",
]
LABEL_PATTERN = re.compile(
    r"tool.?condition|tool.?wear|fault|failure|maintenance|degrad|health|label|target|class",
    re.IGNORECASE,
)


def markdown_table(frame: pd.DataFrame, digits: int = 4) -> str:
    if frame.empty:
        return "_No rows._"
    display = frame.copy()

    def format_value(value):
        if pd.isna(value):
            return ""
        if isinstance(value, (float, np.floating)):
            if not np.isfinite(value):
                return ""
            return f"{value:.{digits}f}"
        return str(value)

    for column in display:
        display[column] = display[column].map(format_value)
    headers = [str(column) for column in display.columns]
    rows = [
        [str(value) for value in row]
        for row in display.itertuples(index=False, name=None)
    ]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def parse_dataset(csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Supplied dataset not found: {csv_path}")
    raw = pd.read_csv(csv_path)
    required = {
        "time", "time.1", "c1", "c2", "c3", "v1", "v2", "v3",
        "accx", "accy", "accz", "tool_temp", "ambient_temp",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"Required source columns are missing: {sorted(missing)}")

    combined = raw["time"].astype(str).str.strip() + " " + raw["time.1"].astype(str).str.strip()
    timestamp = pd.to_datetime(
        combined,
        format="%d-%m-%y %I:%M:%S %p",
        errors="coerce",
    )
    if timestamp.isna().any():
        raise ValueError(f"Could not reconstruct {int(timestamp.isna().sum())} timestamps.")
    ordered = raw.assign(timestamp=timestamp).sort_values("timestamp", kind="stable").reset_index(drop=True)
    ordered["elapsed_seconds"] = ordered["timestamp"].diff().dt.total_seconds()
    ordered["session_id"] = (
        ordered["elapsed_seconds"].isna()
        | ordered["elapsed_seconds"].gt(SESSION_GAP_SECONDS)
    ).cumsum().astype(int)
    ordered["record_in_session"] = ordered.groupby("session_id").cumcount()
    ordered["block_id"] = ordered["record_in_session"] // BLOCK_SAMPLES
    return raw, ordered


def session_summary(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for session_id, group in data.groupby("session_id", sort=True):
        intervals = group["timestamp"].diff().dt.total_seconds().dropna()
        rows.append(
            {
                "session_id": f"S{session_id:02d}",
                "start": group["timestamp"].iloc[0],
                "end": group["timestamp"].iloc[-1],
                "duration": str(group["timestamp"].iloc[-1] - group["timestamp"].iloc[0]),
                "duration_minutes": (group["timestamp"].iloc[-1] - group["timestamp"].iloc[0]).total_seconds() / 60,
                "records": len(group),
                "median_interval_seconds": intervals.median() if not intervals.empty else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_features(data: pd.DataFrame) -> pd.DataFrame:
    features = pd.DataFrame(index=data.index)
    for prefix, columns in (
        ("current", ["c1", "c2", "c3"]),
        ("voltage", ["v1", "v2", "v3"]),
    ):
        phases = data[columns].apply(pd.to_numeric, errors="coerce")
        average = phases.mean(axis=1)
        features[f"mean_{prefix}"] = average
        features[f"{prefix}_std"] = phases.std(axis=1, ddof=0)
        features[f"{prefix}_imbalance"] = (
            phases.sub(average, axis=0).abs().max(axis=1)
            / average.abs().replace(0, np.nan)
            * 100
        )

    axes = data[["accx", "accy", "accz"]].apply(pd.to_numeric, errors="coerce")
    magnitude = np.sqrt(axes.pow(2).sum(axis=1))
    features["vibration_magnitude"] = magnitude
    features["vibration_rms"] = np.nan
    features["vibration_std"] = np.nan
    features["vibration_peak"] = np.nan
    features["vibration_peak_to_peak"] = np.nan
    features["crest_factor"] = np.nan
    for _session_id, indices in data.groupby("session_id", sort=False).groups.items():
        segment = magnitude.loc[indices]
        rolling = segment.rolling(
            ROLLING_WINDOW_SAMPLES,
            min_periods=1,
        )
        rms = rolling.apply(lambda values: np.sqrt(np.mean(np.square(values))), raw=True)
        peak = rolling.max()
        trough = rolling.min()
        features.loc[indices, "vibration_rms"] = rms.to_numpy()
        features.loc[indices, "vibration_std"] = rolling.std(ddof=0).to_numpy()
        features.loc[indices, "vibration_peak"] = peak.to_numpy()
        features.loc[indices, "vibration_peak_to_peak"] = (peak - trough).to_numpy()
        features.loc[indices, "crest_factor"] = (
            peak / rms.replace(0, np.nan)
        ).to_numpy()

    features["tool_temp"] = pd.to_numeric(data["tool_temp"], errors="coerce")
    features["ambient_temp"] = pd.to_numeric(data["ambient_temp"], errors="coerce")
    features["temperature_difference"] = features["tool_temp"] - features["ambient_temp"]
    features["tool_temp_rate"] = np.nan
    for _session_id, indices in data.groupby("session_id", sort=False).groups.items():
        segment = data.loc[indices]
        elapsed = segment["timestamp"].diff().dt.total_seconds()
        rate = features.loc[indices, "tool_temp"].diff() / elapsed * 60
        features.loc[indices, "tool_temp_rate"] = rate.to_numpy()

    return features.replace([np.inf, -np.inf], np.nan)


def make_block_frame(data: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat(
        [
            data[["timestamp", "session_id", "record_in_session", "block_id"]],
            features,
        ],
        axis=1,
    )
    aggregated = combined.groupby(["session_id", "block_id"], sort=True).agg(
        timestamp=("timestamp", "median"),
        start=("timestamp", "min"),
        end=("timestamp", "max"),
        records=("timestamp", "size"),
        **{
            f"{column}_median": (column, "median")
            for column in features.columns
        },
        **{
            f"{column}_std": (column, "std")
            for column in [
                "mean_current", "mean_voltage", "vibration_rms", "tool_temp"
            ]
        },
    )
    return aggregated.reset_index()


def assign_regimes(blocks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_columns = [f"{name}_median" for name in REGIME_FEATURES]
    fit_rows = blocks[feature_columns].replace([np.inf, -np.inf], np.nan)
    valid = fit_rows.dropna()
    if len(valid) < 3:
        blocks = blocks.copy()
        blocks["regime"] = "Not assigned"
        return blocks, pd.DataFrame()

    scaler = StandardScaler()
    scaled = scaler.fit_transform(valid)
    cluster_count = 3
    clusters = KMeans(
        n_clusters=cluster_count,
        random_state=IFOREST_RANDOM_STATE,
        n_init=20,
    ).fit_predict(scaled)
    blocks = blocks.copy()
    blocks["regime"] = pd.NA
    blocks.loc[valid.index, "cluster_id"] = clusters

    centers = (
        blocks.loc[valid.index]
        .assign(cluster=clusters)
        .groupby("cluster")
        .agg(
            blocks=("records", "size"),
            records=("records", "sum"),
            sessions=("session_id", "nunique"),
            current_median=("mean_current_median", "median"),
            current_p90=("mean_current_median", lambda values: values.quantile(0.9)),
            voltage_median=("mean_voltage_median", "median"),
            voltage_std_median=("voltage_std_median", "median"),
            vibration_rms_median=("vibration_rms_median", "median"),
            tool_temp_median=("tool_temp_median", "median"),
        )
        .sort_values("current_median")
    )
    names = {cluster: f"Regime {chr(65 + rank)}" for rank, cluster in enumerate(centers.index)}
    blocks.loc[valid.index, "regime"] = [names[cluster] for cluster in clusters]
    centers = centers.reset_index(names="cluster_id")
    centers["regime"] = centers["cluster_id"].map(names)

    ordered = blocks.sort_values(["session_id", "block_id"])
    return blocks, centers


def baseline_candidates(data: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    rows = []
    columns = {
        "current": "mean_current",
        "voltage": "mean_voltage",
        "vibration": "vibration_rms",
        "tool_temp": "tool_temp",
    }
    window_data = pd.concat(
        [
            data[["timestamp", "session_id", "record_in_session"]],
            features[list(columns.values())],
        ],
        axis=1,
    )
    window_data["baseline_block"] = (
        window_data["record_in_session"] // BASELINE_BLOCK_SAMPLES
    )
    for (session_id, block_id), group in window_data.groupby(
        ["session_id", "baseline_block"], sort=True
    ):
        if len(group) < BASELINE_BLOCK_SAMPLES:
            continue
        item = {
            "session_id": f"S{session_id:02d}",
            "start": group["timestamp"].iloc[0],
            "end": group["timestamp"].iloc[-1],
            "records": len(group),
        }
        for name, feature_column in columns.items():
            median = group[feature_column].median()
            std = group[feature_column].std()
            item[f"{name}_cv_pct"] = (
                100 * std / abs(median)
                if pd.notna(std) and pd.notna(median) and median != 0
                else np.nan
            )
        item["block_id"] = block_id
        rows.append(item)
    result = pd.DataFrame(rows)
    cv_columns = [f"{name}_cv_pct" for name in columns]
    scale = result[cv_columns].median(axis=0).replace(0, np.nan)
    normalized = result[cv_columns].div(scale, axis=1)
    result["relative_stability_score"] = normalized.median(axis=1)
    return result.sort_values("relative_stability_score")


def rolling_robust_z(data: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    z_values = pd.DataFrame(np.nan, index=data.index, columns=MODEL_FEATURES)
    for _session_id, indices in data.groupby("session_id", sort=False).groups.items():
        for column in MODEL_FEATURES:
            values = features.loc[indices, column]
            prior = values.shift(1)
            center = prior.rolling(
                ROLLING_WINDOW_SAMPLES,
                min_periods=ROLLING_MIN_PERIODS,
            ).median()
            q75 = prior.rolling(
                ROLLING_WINDOW_SAMPLES,
                min_periods=ROLLING_MIN_PERIODS,
            ).quantile(0.75)
            q25 = prior.rolling(
                ROLLING_WINDOW_SAMPLES,
                min_periods=ROLLING_MIN_PERIODS,
            ).quantile(0.25)
            robust_scale = (q75 - q25) / 1.349
            z_values.loc[indices, column] = (
                (values - center) / robust_scale.replace(0, np.nan)
            ).to_numpy()

    absolute = z_values.abs()
    result = absolute.copy()
    result["rolling_max_abs_z"] = absolute.max(axis=1, skipna=True)
    has_scores = absolute.notna().any(axis=1)
    result["rolling_max_abs_z_feature"] = absolute.fillna(-np.inf).idxmax(axis=1)
    result.loc[~has_scores, "rolling_max_abs_z_feature"] = pd.NA
    result.loc[~has_scores, "rolling_max_abs_z"] = np.nan
    return result


def fit_time_aware_iforest(
    data: pd.DataFrame,
    features: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int]:
    n_sessions = int(data["session_id"].nunique())
    heldout_count = min(TRAINING_SESSIONS_HELD_OUT, max(1, n_sessions - 1))
    first_test_session = n_sessions - heldout_count + 1
    train_mask = data["session_id"] < first_test_session
    test_mask = ~train_mask

    eligible = features[MODEL_FEATURES].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    sampled = data["record_in_session"].mod(BLOCK_SAMPLES).eq(0)
    train_indices = data.index[train_mask & eligible & sampled]
    test_indices = data.index[test_mask & eligible & sampled]
    if len(train_indices) < 100 or len(test_indices) < 20:
        raise ValueError(
            "Not enough eligible time-spaced records for the chronological Isolation Forest split."
        )

    scaler = RobustScaler()
    train_values = scaler.fit_transform(features.loc[train_indices, MODEL_FEATURES])
    test_values = scaler.transform(features.loc[test_indices, MODEL_FEATURES])
    model = IsolationForest(
        n_estimators=200,
        max_samples="auto",
        contamination="auto",
        random_state=IFOREST_RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(train_values)

    scores = pd.DataFrame(index=data.index, columns=["iforest_anomaly_score"], dtype=float)
    scores.loc[test_indices, "iforest_anomaly_score"] = -model.score_samples(test_values)
    scores.loc[test_indices, "iforest_candidate_rank"] = (
        scores.loc[test_indices, "iforest_anomaly_score"]
        .rank(method="min", ascending=False)
        .astype(int)
    )
    scores["evaluation_split"] = pd.NA
    scores.loc[data.index[train_mask], "evaluation_split"] = "training"
    scores.loc[data.index[test_mask], "evaluation_split"] = "held-out later sessions"
    return scores, len(train_indices), len(test_indices)


def make_figures(
    data: pd.DataFrame,
    features: pd.DataFrame,
    blocks: pd.DataFrame,
    regimes: pd.DataFrame,
    rolling_scores: pd.DataFrame,
    iforest_scores: pd.DataFrame,
    baseline: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    plot_blocks = blocks.sort_values("timestamp")

    fig, axes = plt.subplots(4, 1, figsize=(15, 13), sharex=True)
    for axis, column, label in zip(
        axes,
        [
            "mean_current_median",
            "mean_voltage_median",
            "vibration_rms_median",
            "tool_temp_median",
        ],
        ["Mean current", "Mean voltage", "Vibration RMS", "Tool temperature"],
    ):
        axis.scatter(
            plot_blocks["timestamp"],
            plot_blocks[column],
            c=plot_blocks["session_id"],
            s=8,
            cmap="viridis",
        )
        axis.set_ylabel(label)
        axis.grid(alpha=0.2)
    axes[-1].set_xlabel("Timestamp (60-second aggregated blocks)")
    fig.suptitle("Derived sensor features over time; colors distinguish recording sessions")
    fig.tight_layout()
    path = output_dir / "derived_features_over_time.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    paths.append(path)

    regime_blocks = plot_blocks.dropna(subset=["regime"])
    if not regime_blocks.empty:
        fig, axis = plt.subplots(figsize=(10, 6))
        for regime, group in regime_blocks.groupby("regime", sort=True):
            axis.scatter(
                group["mean_current_median"],
                group["vibration_rms_median"],
                s=12,
                alpha=0.55,
                label=regime,
            )
        axis.set(
            xlabel="Block median mean current",
            ylabel="Block median vibration RMS",
            title="Exploratory neutral regimes (60-second blocks)",
        )
        axis.legend()
        axis.grid(alpha=0.2)
        fig.tight_layout()
        path = output_dir / "neutral_operating_regimes.png"
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(path)

    stable = baseline.sort_values("relative_stability_score").head(30)
    if not stable.empty:
        fig, axis = plt.subplots(figsize=(11, 5))
        labels = [
            f"{row.session_id} {row.start:%m-%d %H:%M}"
            for row in stable.itertuples()
        ]
        axis.barh(labels[::-1], stable["relative_stability_score"].to_numpy()[::-1])
        axis.set(
            xlabel="Relative stability score (lower = more stable across four CVs)",
            title="30-minute blocks ranked by relative sensor stability",
        )
        axis.grid(axis="x", alpha=0.2)
        fig.tight_layout()
        path = output_dir / "baseline_stability_candidates.png"
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(path)

    heldout = iforest_scores["evaluation_split"].eq("held-out later sessions")
    score_rows = data.loc[heldout].copy()
    score_rows["iforest_anomaly_score"] = iforest_scores.loc[
        heldout, "iforest_anomaly_score"
    ]
    score_rows["rolling_max_abs_z"] = rolling_scores.loc[
        heldout, "rolling_max_abs_z"
    ]
    score_rows = score_rows.dropna(subset=["iforest_anomaly_score"])
    if not score_rows.empty:
        fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
        axes[0].scatter(
            score_rows["timestamp"],
            score_rows["iforest_anomaly_score"],
            c=score_rows["session_id"],
            s=16,
            cmap="plasma",
            label="Held-out score (one row/minute)",
        )
        axes[0].set_ylabel("Isolation Forest anomaly score")
        axes[0].legend()
        axes[1].plot(
            score_rows["timestamp"],
            score_rows["rolling_max_abs_z"],
            linewidth=0.8,
            color="#28775e",
        )
        axes[1].axhline(3.5, color="#bd5549", linestyle="--", label="Exploratory robust-z screen")
        axes[1].set_ylabel("Maximum trailing robust |z|")
        axes[1].set_xlabel("Timestamp")
        axes[1].legend()
        for axis in axes:
            axis.grid(alpha=0.2)
        fig.suptitle("Unlabeled anomaly scores on later, held-out sessions")
        fig.tight_layout()
        path = output_dir / "candidate_anomaly_scores.png"
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(path)

    # This plot uses the complete 60-second block series, not the raw 3-second points.
    path = output_dir / "current_and_temperature_blocks.png"
    fig, axes = plt.subplots(2, 1, figsize=(15, 8), sharex=True)
    axes[0].plot(
        plot_blocks["timestamp"],
        plot_blocks["mean_current_median"],
        linewidth=0.8,
        label="Mean current",
    )
    axes[0].set_ylabel("Current (source units)")
    axes[0].legend()
    axes[1].plot(
        plot_blocks["timestamp"],
        plot_blocks["tool_temp_median"],
        linewidth=0.8,
        color="#bd5549",
        label="Tool temperature",
    )
    axes[1].set_ylabel("Temperature (source units)")
    axes[1].set_xlabel("Timestamp")
    axes[1].legend()
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.suptitle("Current and tool-temperature behavior by 60-second block")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    paths.append(path)
    return paths


def inspect_target_headers(raw: pd.DataFrame, csv_path: Path) -> tuple[list[str], list[str]]:
    candidates = [str(column) for column in raw.columns if LABEL_PATTERN.search(str(column))]
    documentation = [
        path.name
        for path in csv_path.parent.iterdir()
        if path.is_file()
        and path != csv_path
        and path.suffix.lower() in {".md", ".txt", ".pdf", ".doc", ".docx"}
    ]
    return candidates, documentation


def run_analysis(
    csv_path: Path,
    report_path: Path,
    figure_dir: Path,
) -> str:
    raw, data = parse_dataset(csv_path)
    sessions = session_summary(data)
    features = build_features(data)
    missing_features = sorted(set(MODEL_FEATURES).difference(features.columns))
    if missing_features:
        raise RuntimeError(f"Analysis feature generation failed: {missing_features}")

    blocks = make_block_frame(data, features)
    blocks, regimes = assign_regimes(blocks)
    baseline = baseline_candidates(data, features)
    rolling_scores = rolling_robust_z(data, features)
    iforest_scores, train_count, test_count = fit_time_aware_iforest(data, features)
    figures = make_figures(
        data,
        features,
        blocks,
        regimes,
        rolling_scores,
        iforest_scores,
        baseline,
        figure_dir,
    )

    heldout = iforest_scores["evaluation_split"].eq("held-out later sessions")
    heldout_rows = data.loc[heldout].copy()
    heldout_rows["iforest_anomaly_score"] = iforest_scores.loc[
        heldout, "iforest_anomaly_score"
    ]
    heldout_rows["iforest_candidate_rank"] = iforest_scores.loc[
        heldout, "iforest_candidate_rank"
    ]
    heldout_rows["rolling_max_abs_z"] = rolling_scores.loc[
        heldout, "rolling_max_abs_z"
    ]
    heldout_rows["rolling_max_abs_z_feature"] = rolling_scores.loc[
        heldout, "rolling_max_abs_z_feature"
    ]

    eligible_heldout = heldout_rows.dropna(subset=["iforest_anomaly_score"])
    iforest_count = len(eligible_heldout)
    top_iforest = eligible_heldout.nsmallest(12, "iforest_candidate_rank")
    robust_candidates = heldout_rows.loc[
        heldout_rows["rolling_max_abs_z"].ge(3.5)
    ].sort_values("rolling_max_abs_z", ascending=False)
    top_robust = robust_candidates.head(12)
    feature_screen_counts = (
        rolling_scores.loc[heldout, MODEL_FEATURES].abs().ge(3.5).sum()
    )
    feature_screen_counts = feature_screen_counts[feature_screen_counts.gt(0)].sort_values(ascending=False)

    regimes_by_session = (
        blocks.pivot_table(
            index="regime",
            columns="session_id",
            values="records",
            aggfunc="sum",
            fill_value=0,
        )
        .rename(columns=lambda session_id: f"S{session_id:02d}")
        .reset_index()
    )
    regime_table = regimes.merge(
        regimes_by_session,
        on="regime",
        how="left",
    ) if not regimes.empty else regimes

    stable_windows = baseline.head(5).copy()
    stable_windows["session_id"] = stable_windows["session_id"]
    stable_table = stable_windows[
        [
            "session_id", "start", "end", "records",
            "current_cv_pct", "voltage_cv_pct", "vibration_cv_pct",
            "tool_temp_cv_pct", "relative_stability_score",
        ]
    ]

    session_table = sessions[
        [
            "session_id", "start", "end", "duration",
            "duration_minutes", "records", "median_interval_seconds",
        ]
    ]
    session_table["duration_minutes"] = session_table["duration_minutes"].round(2)
    session_table["median_interval_seconds"] = session_table["median_interval_seconds"].round(2)

    candidate_columns = [
        "timestamp", "session_id", "iforest_anomaly_score",
        "rolling_max_abs_z", "rolling_max_abs_z_feature",
    ]
    candidate_iforest_table = top_iforest[candidate_columns].copy()
    candidate_robust_table = top_robust[candidate_columns].copy()
    for table in (candidate_iforest_table, candidate_robust_table):
        table["session_id"] = table["session_id"].map(lambda value: f"S{value:02d}")

    target_candidates, documentation = inspect_target_headers(raw, csv_path)
    excluded_session_gaps = data.loc[
        data["elapsed_seconds"].gt(SESSION_GAP_SECONDS),
        ["timestamp", "elapsed_seconds"],
    ]
    gap_text = markdown_table(
        excluded_session_gaps.rename(
            columns={"timestamp": "new_session_start", "elapsed_seconds": "preceding_gap_seconds"}
        ),
        digits=1,
    )
    session_md = markdown_table(session_table, digits=2)
    regime_md = markdown_table(regime_table, digits=3)
    baseline_md = markdown_table(stable_table, digits=4)
    iforest_candidates_md = markdown_table(candidate_iforest_table, digits=4)
    robust_candidates_md = markdown_table(candidate_robust_table, digits=4)
    feature_counts_md = markdown_table(
        feature_screen_counts.rename("heldout_points_over_3_5").rename_axis("feature").reset_index(),
        digits=0,
    )
    figure_md = "\n".join(f"- `figures/target_analysis/{path.name}`" for path in figures)
    documentation_summary = (
        ", ".join(f"`{name}`" for name in documentation)
        if documentation
        else "no documentation files in the supplied dataset directory"
    )
    label_summary = (
        ", ".join(f"`{name}`" for name in target_candidates)
        if target_candidates
        else "none"
    )

    iforest_quantiles = eligible_heldout["iforest_anomaly_score"].quantile(
        [0.5, 0.9, 0.95, 0.99]
    )
    feature_completeness = int(
        features[MODEL_FEATURES].notna().all(axis=1).sum()
    )
    regime_summary = (
        "Three-cluster K-means on standardized 60-second block medians for "
        "mean current, cross-phase current standard deviation, vibration RMS, and tool "
        "temperature. Voltage medians and phase spread are reported as context, not "
        "used to force a cluster if they provide little variation."
    )
    time_behavior = (
        "The block plots expose repeatable intraday electrical and temperature patterns "
        "and long low-current intervals mixed with elevated-current intervals. Voltage "
        "is comparatively narrow in range. These are sensor patterns only; the CSV "
        "contains no operation annotation to verify machining state. Similar shapes "
        "recur on recording days, so repetition can reflect the acquisition schedule or "
        "replayed daily process and is not independent proof of machine health."
    )
    feature_inline = ", ".join(f"`{name}`" for name in MODEL_FEATURES)
    ordered_blocks = blocks.sort_values(["session_id", "block_id"])
    previous_regime = ordered_blocks.groupby("session_id")["regime"].shift()
    regime_transitions = int(
        (
            ordered_blocks["regime"].ne(previous_regime)
            & ordered_blocks["regime"].notna()
            & previous_regime.notna()
        ).sum()
    )

    report = f"""# ML Target & Anomaly Strategy

> Preliminary, label-free analysis of the supplied CNC lathe CSV only. The original source file is read-only. No RPM is used, no health label is created, and no production model or deployment threshold is selected.

## Dataset Sessions

Timestamps were reconstructed from `time` (`%d-%m-%y`) and `time.1` (`%I:%M:%S %p`), then sorted chronologically. The median within-run cadence is 3 seconds. A new recording session is defined when the gap exceeds **{SESSION_GAP_SECONDS} seconds** (ten nominal intervals), separating material pauses rather than treating a date as a session.

{session_md}

Inter-session gaps:

{gap_text}

This produced **{len(sessions)} sessions**. These are recording sessions, not verified machine shifts, operations, or tool lives.

## Operating Regimes

RPM is excluded. Sensor activity was explored using 60-second non-overlapping summaries and the following neutral clustering procedure: {regime_summary}

{regime_md}

The cluster names are neutral, descriptive partitions only. K-means always returns three clusters here; it does not prove three physical machine states. Cluster differences and session counts should be reviewed alongside the plots. No `idle`, `machining`, or `high-load` semantic label is assigned because no independent state annotation is supplied. Voltage channels have narrow, nearly unchanged observed ranges in Phase 0.1; the cluster table shows whether voltage spread separates any of these groups.

The ordered block sequence changes cluster {regime_transitions} times within sessions. A cluster transition is a change in standardized sensor signature, not a verified machine-state transition.

## Derived Features

All features are calculated in-memory and aligned to the sorted raw rows; the CSV columns and file are not modified.

- `mean_current`: row arithmetic mean of `c1`, `c2`, `c3`.
- `current_std`: population standard deviation (`ddof=0`) across the three current phases per row.
- `current_imbalance`: maximum absolute phase deviation from `mean_current`, divided by `abs(mean_current)`, × 100; undefined for zero mean.
- `mean_voltage`, `voltage_std`, `voltage_imbalance`: analogous calculations for `v1`, `v2`, `v3`.
- `vibration_magnitude`: `sqrt(accx² + accy² + accz²)` on the recorded raw axes.
- `vibration_rms`, `vibration_std`, `vibration_peak`, `vibration_peak_to_peak`, `crest_factor`: trailing window of up to **60 records** (nominally 3 minutes), including the current record; windows reset at each recording session; early windows use available records. RMS and standard deviation are calculated on the magnitude series; crest factor = window peak / window RMS.
- `tool_temp`, `ambient_temp`: source values.
- `tool_temp_rate`: within-session backward temperature difference per actual elapsed minute; no rate is calculated across a session boundary.
- `temperature_difference`: `tool_temp - ambient_temp`.
- For plots/regimes, these features are summarized into non-overlapping **20-record (nominally 60-second) blocks**. Partial final blocks are retained and their record counts reported.

{markdown_table(pd.DataFrame({"model_feature": MODEL_FEATURES, "present_in_derived_frame": [name in features for name in MODEL_FEATURES]}), digits=0)}

Complete feature rows: **{feature_completeness:,}/{len(data):,}**. The first row in each session has no tool-temperature rate; the model/scoring paths omit rows missing any selected feature rather than imputing across time gaps.

## Temporal Behavior

{time_behavior}

The figures use 60-second block aggregates for legibility; they preserve the chronology and do not resample or alter the source file.

{figure_md}

## Candidate Anomalies

No observations are called faults. Two preliminary screens were run with session-aware chronology:

1. **Trailing robust rolling z-score:** for each model feature, compare the current value to the previous up to {ROLLING_WINDOW_SAMPLES} records in the same session, requiring at least {ROLLING_MIN_PERIODS} prior points. Center is the prior rolling median; scale is prior IQR / 1.349. Zero-IQR cases produce no z-score rather than an infinite score. Points with any feature at |z| ≥ 3.5 are review candidates, not fault labels.
2. **Isolation Forest:** {train_count:,} one-minute-spaced records from earlier sessions fit the exploratory model; {test_count:,} one-minute-spaced records from the final held-out sessions are scored. A `RobustScaler` is fit on training sessions only. Isolation Forest uses 200 trees, a fixed random seed for reproducibility, and `contamination='auto'`; its output here is a continuous ranking score, not the model's binary prediction.

The Isolation Forest held-out score quantiles are: median **{iforest_quantiles.loc[0.5]:.5f}**, 90th **{iforest_quantiles.loc[0.9]:.5f}**, 95th **{iforest_quantiles.loc[0.95]:.5f}**, 99th **{iforest_quantiles.loc[0.99]:.5f}**. Lower method-specific scores are not automatically better; this implementation negates `score_samples`, so larger scores indicate more isolated points.

Top held-out Isolation Forest ranked candidate anomalies (ranking only):

{iforest_candidates_md}

Top held-out rolling robust-z candidates:

{robust_candidates_md}

Held-out records crossing the exploratory |z| ≥ 3.5 screen by feature:

{feature_counts_md}

Scores may reflect normal transitions, mixed operating states, sensor offsets, day-to-day repetition, or measurement artifacts. There are no labels with which to estimate precision, recall, false alarm rate, or mechanical-failure validity. No candidate is confirmed as a failure.

Very large rolling robust-z values can result when a feature has a small but nonzero prior IQR (including quantized or nearly constant readings); magnitudes are not comparable across features and should be treated as ranking prompts only. The chronological holdout also is not independent machine validation: similar daily patterns recur in both earlier and later sessions.

## Baseline Analysis

The data were divided into complete, non-overlapping **30-minute (600-record)** windows within each session; incomplete trailing windows were excluded from baseline ranking. For mean current, mean voltage, vibration RMS, and tool temperature, each window's coefficient of variation (CV = within-window sample standard deviation / absolute window median × 100) was calculated. A relative stability score is the median of each CV divided by that feature's median CV across windows; lower ranks indicate comparatively stable observed sensor distributions, not “healthy” operation.

Most stable windows by this descriptive criterion:

{baseline_md}

These are **sensor-stability candidates only**, not a defensible healthy baseline: the dataset has no verified healthy/abnormal state, tool/maintenance history, process annotations, or unit/calibration documentation. The windows are chosen by a relative ranking over the same dataset and cannot establish normality. Anomaly detection against them would require YCCE operators and labelled baseline collection to validate.

## Health/Fault Label Investigation

- Label-like header candidates: {label_summary}.
- Accompanying dataset-directory documentation: {documentation_summary}.
- The CSV has no verified tool-condition, tool-wear, fault, failure, maintenance, degradation, or health-state target. The one populated unnamed export field has no documented meaning and is not considered a label.

**NO VERIFIED SUPERVISED HEALTH LABEL**

## Classification Feasibility

**Healthy/faulty classification is not justified.** A classifier requires trusted labels for machine/tool health at the observation time, representative examples of each state, and an evaluation split independent by time/run. None of those target labels or event records are supplied. High current, temperature, or vibration cannot be relabeled as “fault”.

## Regression Feasibility

Predicting a future tool temperature from past sensor values is technically possible as a forecasting exercise, but it does not predict tool health or maintenance need and there is no ground-truth wear target. Reconstructing contemporaneous temperature from other same-time sensors would be a sensor-estimation task and risks leakage, not predictive maintenance. Regression is therefore not recommended as the initial project ML objective.

## Anomaly Detection Feasibility

Unlabeled deviation ranking is supported as **exploratory anomaly methodology/pipeline development** because the file contains a long, ordered sensor series with repeated 3-second samples and several sensor domains. The methods above provide reproducible candidate scores under a chronological session holdout. They do **not** show that scores represent machine faults, nor establish a healthy baseline, operational threshold, or transfer to a different lathe. The dataset's repeated daily patterns, sensor offsets, unknown units, mixed unidentified regimes, and only six sessions materially limit inference.

## RUL Feasibility

**Remaining useful life (RUL) is not supportable.** RUL requires asset/tool identity, observed run-to-failure or censoring timelines, failure/maintenance events, and operating exposure. None is available, so no RUL target can be defined or validated.

## Recommended ML Objective

Start with **offline, unlabeled sensor-anomaly score experimentation**, then validate it against future YCCE baseline and reviewed event data. Do not frame the result as fault detection or predictive maintenance until independently validated. This is a pipeline/method objective, not a trained production model.

## Input Features

Use the following exact derived values for the preliminary anomaly experiment:

{markdown_table(pd.DataFrame({"feature": MODEL_FEATURES}), digits=0)}

Timestamps and `session_id` are for ordering, session boundaries, and chronological evaluation only; they are not model predictors. **RPM is excluded.** Transformations/scaling must be fitted on training-only historical data. Existing raw phase/axis channels remain untouched in the CSV; this first feature experiment uses the summaries above, not every raw channel as an additional duplicate input.

## Expected Output

For each scored timestamp/block, eventual system output could include:

```text
anomaly_score
anomaly_status
```

`anomaly_score` is a continuous, model-specific ranking value. `anomaly_status` (for example `NORMAL`, `WARNING`, `ANOMALY`) is **not assigned in this phase**. Until labels and validation exist, report scores/candidates for human review only; do not present them as health states.

## Threshold Strategy

Do not choose a deployment threshold from this public dataset's arbitrary score percentile or from `contamination`. Collect a representative verified-normal YCCE baseline across machine states, shifts, tools, and loads; freeze model and preprocessing; score separate chronological runs; review candidate alerts with operators; link alerts to verified abnormal events and benign transitions; quantify false alerts per operating hour and event sensitivity. Select thresholds against an agreed operational false-alarm/recall cost, then validate on a later untouched period. Recalibrate only under documented change control. Until then, thresholds are exploratory review filters only.

## Public Dataset vs YCCE Lathe

**Public dataset:** historical recorded CNC-lathe measurements with names matching project channels; useful for parsing, feature engineering, plots, and anomaly-method experimentation.

**Actual YCCE lathe:** future live readings from PT100 + MAX31865, ADXL355/ADXL345, and a 3-phase energy meter over RS-485 Modbus. These hardware readings, units, sampling/aggregation, mounting/orientation, calibration, filtering, and operational patterns can differ from this CSV.

That mismatch is **domain shift**: a model may flag ordinary YCCE values as novel or miss a real event because sensor scales, offsets, bandwidth, placement, machine, process, and regime distributions differ. Public-data scores are not evidence of YCCE model performance. Calibrate/validate using real YCCE data before operational use; never transfer score thresholds unchanged.

## Real-World Data Collection Requirements

Collect synchronized records keyed by machine and session, with:

- Timestamp with timezone/clock-sync and clear sampling or aggregation interval.
- Tool temperature from PT100/MAX31865; ambient temperature if available.
- Calibrated vibration X/Y/Z from ADXL355/ADXL345, with sensor identity, units, orientation/mounting, sample rate, filtering, and window aggregation.
- Three-phase current and voltage via RS-485 Modbus meter, including meter/register mapping, units, phase identity, and whether values are RMS/instantaneous.
- Machine operating state and operation/load context, recorded independently of model output.
- Tool identity, tool replacement events, inspection/tool-wear measurements where available.
- Maintenance events, known abnormal events, onset/clear times, operator confirmation, and known benign events.
- Operator notes when possible, plus workpiece/material, job, shift, and sensor/calibration changes where obtainable.

Do **not** add RPM unless project scope is explicitly changed. Preserve raw synchronized observations and provenance so later labels can be audited and time-aware splits can be made.

## Final Decision

1. **What ML problem are we implementing first?** Offline exploratory **unlabeled anomaly detection**; not production fault classification.
2. **Why?** The dataset contains chronological multichannel sensor readings but no verified health/fault/wear target. Anomaly scores can be explored without inventing labels, though their operational meaning is unproven.
3. **What exact input features will be used?** {feature_inline}. Time/session fields are split metadata only; no RPM.
4. **What will the model output?** A continuous `anomaly_score` for human review. No `anomaly_status` or health/fault label will be emitted until threshold calibration and independent validation.
5. **What information is still missing?** Sensor units/calibration and acquisition semantics, verified operating states, machine/tool/workpiece identity, healthy baseline coverage, confirmed abnormal/fault labels, wear measurements, and maintenance/failure timelines.
6. **What data must eventually come from the real YCCE lathe?** Timestamped tool/ambient temperature, X/Y/Z vibration, three-phase current/voltage, independently recorded operating states, maintenance and abnormal events, tool replacement/condition, and operator notes, with sensor metadata and synchronization. Validate across later YCCE runs before claiming predictive-maintenance capability.
"""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--figures", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args()
    run_analysis(args.csv.resolve(), args.report.resolve(), args.figures.resolve())
    print("Preliminary ML target analysis completed.")
    print(f"\nReport written to: {args.report.resolve()}")
    print(f"Figures written to: {args.figures.resolve()}")


if __name__ == "__main__":
    main()
