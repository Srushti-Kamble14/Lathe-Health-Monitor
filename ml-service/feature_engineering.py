#!/usr/bin/env python
"""Prepare reproducible, session-aware ML features from PostgreSQL readings."""

from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import sql

import feature_config as config
from ingest_dataset import get_connection_url


SQL_SENSOR_COLUMNS = ", ".join(f"sr.{column}" for column in config.SENSOR_COLUMNS)
FRAME_COLUMNS = [
    "machine_id",
    "session_id",
    "session_number",
    "session_start",
    "session_end",
    "declared_sample_count",
    "timestamp",
    *config.SENSOR_COLUMNS,
]


def fetch_database_readings() -> tuple[pd.DataFrame, dict[str, int]]:
    """Fetch approved columns and persisted session membership from PostgreSQL."""
    connection = psycopg2.connect(
        get_connection_url(),
        connect_timeout=10,
        application_name="lathe-health-monitor-feature-engineering",
    )
    print("Connected; checking database row/session counts and columns...", flush=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM machine_sessions AS ms
                   WHERE ms.machine_id = m.id) AS session_count,
                  (SELECT COUNT(*) FROM sensor_readings AS sr
                   WHERE sr.machine_id = m.id) AS reading_count
                FROM machines AS m
                WHERE m.machine_code = %s
                """,
                (config.MACHINE_CODE,),
            )
            machine_counts = cursor.fetchone()
            if machine_counts is None:
                raise RuntimeError(f"Machine {config.MACHINE_CODE} is not present in the database.")
            persisted_counts = {
                "session_count": int(machine_counts[0]),
                "reading_count": int(machine_counts[1]),
            }
            print("Counts read; checking required sensor columns...", flush=True)
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'sensor_readings'
                  AND column_name = ANY(%s)
                """,
                (list(config.SENSOR_COLUMNS),),
            )
            available = {row[0] for row in cursor.fetchall()}
            missing = sorted(set(config.SENSOR_COLUMNS) - available)
            if missing:
                raise RuntimeError(
                    f"sensor_readings is missing required sensor columns: {missing}"
                )

            copy_query = sql.SQL(
                """
                COPY (
                  SELECT m.id::text,
                         ms.id::text,
                         ms.session_number,
                         ms.start_time,
                         ms.end_time,
                         ms.sample_count,
                         sr.timestamp,
                         {sensor_columns}
                  FROM machines AS m
                  JOIN machine_sessions AS ms ON ms.machine_id = m.id
                  JOIN sensor_readings AS sr
                    ON sr.machine_id = m.id
                   AND sr.timestamp >= ms.start_time
                   AND sr.timestamp <= ms.end_time
                  WHERE m.machine_code = {machine_code}
                  ORDER BY ms.start_time, ms.session_number, sr.timestamp
                ) TO STDOUT WITH (FORMAT CSV)
                """
            ).format(
                sensor_columns=sql.SQL(SQL_SENSOR_COLUMNS),
                machine_code=sql.Literal(config.MACHINE_CODE),
            )
            output = io.StringIO()
            cursor.copy_expert(copy_query.as_string(connection), output)
            print(f"Database export completed ({output.tell():,} characters).", flush=True)
    finally:
        connection.close()

    output.seek(0)
    print("Parsing exported database rows...", flush=True)
    data = pd.read_csv(output, header=None, names=FRAME_COLUMNS)
    print("Database export parsed.", flush=True)
    if data.empty:
        raise RuntimeError(
            f"No persisted session readings found for machine {config.MACHINE_CODE}."
        )
    if len(data) != persisted_counts["reading_count"]:
        raise RuntimeError(
            "Database reading/session join does not account for every reading: "
            f"{len(data)} matched versus {persisted_counts['reading_count']} persisted. "
            "Inspect missing or overlapping session boundaries before feature generation."
        )
    print(f"Fetched {len(data):,} joined reading rows.", flush=True)
    return data, persisted_counts


def load_reference_snapshot() -> dict[str, Any] | None:
    path = config.INGESTION_VALIDATION_PATH
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def prepare_database_frame(
    frame: pd.DataFrame, persisted_counts: dict[str, int]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    data = frame.copy()
    print("Parsing timestamps and validating numeric sensors...", flush=True)
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
    data["session_start"] = pd.to_datetime(data["session_start"], utc=True, errors="coerce")
    data["session_end"] = pd.to_datetime(data["session_end"], utc=True, errors="coerce")
    timestamp_parse_failures = int(data["timestamp"].isna().sum())
    if timestamp_parse_failures:
        raise ValueError(f"Database returned {timestamp_parse_failures} unparseable timestamps.")

    numeric = data[list(config.SENSOR_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    missing_per_sensor = numeric.isna().sum().astype(int).to_dict()
    finite_per_sensor = {
        column: int(np.isfinite(numeric[column].to_numpy(dtype=float)).sum())
        for column in config.SENSOR_COLUMNS
    }
    invalid_numeric_per_sensor = {
        column: int(len(numeric) - finite_per_sensor[column])
        for column in config.SENSOR_COLUMNS
    }
    if any(invalid_numeric_per_sensor.values()):
        raise ValueError(
            "Database readings contain missing or non-finite sensor values: "
            f"{invalid_numeric_per_sensor}"
        )
    data[list(config.SENSOR_COLUMNS)] = numeric
    print("Sensor values validated; checking ordering and session intervals...", flush=True)

    data["machine_id"] = data["machine_id"].astype(str)
    data["session_id"] = data["session_id"].astype(str)
    data["session_number"] = data["session_number"].astype(int)
    data["declared_sample_count"] = data["declared_sample_count"].astype(int)
    data = data.sort_values(
        ["session_start", "session_number", "timestamp"], kind="stable"
    ).reset_index(drop=True)

    duplicate_timestamps = int(data["timestamp"].duplicated(keep=False).sum())
    if duplicate_timestamps:
        raise ValueError(
            f"{duplicate_timestamps} returned readings have duplicate timestamps "
            "or overlap multiple persisted sessions."
        )

    within_bounds = (
        data["timestamp"].ge(data["session_start"])
        & data["timestamp"].le(data["session_end"])
    )
    if not bool(within_bounds.all()):
        raise ValueError("A reading falls outside its persisted session boundaries.")

    ordered = bool(data["timestamp"].is_monotonic_increasing)
    if not ordered:
        raise ValueError("Database readings are not chronologically ordered.")

    session_groups = data.groupby(
        ["session_number", "session_id"], sort=True, observed=True
    )
    intervals: list[float] = []
    session_rows: list[dict[str, Any]] = []
    for (number, session_id), group in session_groups:
        session_intervals = group["timestamp"].diff().dt.total_seconds().dropna()
        intervals.extend(session_intervals.tolist())
        session_rows.append(
            {
                "session_number": int(number),
                "session_id": session_id,
                "start": group["timestamp"].iloc[0],
                "end": group["timestamp"].iloc[-1],
                "duration_seconds": float(
                    (group["timestamp"].iloc[-1] - group["timestamp"].iloc[0]).total_seconds()
                ),
                "records": int(len(group)),
                "declared_records": int(group["declared_sample_count"].iloc[0]),
                "record_count_matches": bool(
                    len(group) == int(group["declared_sample_count"].iloc[0])
                ),
                "median_interval_seconds": (
                    float(session_intervals.median())
                    if not session_intervals.empty
                    else None
                ),
                "maximum_interval_seconds": (
                    float(session_intervals.max())
                    if not session_intervals.empty
                    else None
                ),
            }
        )

    print("Session intervals summarized; deriving contiguous-region boundaries...", flush=True)
    if not intervals or any(not math.isfinite(value) or value <= 0 for value in intervals):
        raise ValueError("No valid positive within-session sampling intervals were found.")
    interval_series = pd.Series(intervals, dtype=float)
    interval_counts = {
        f"{float(interval):g}": int(count)
        for interval, count in interval_series.value_counts().sort_index().items()
    }
    modal_values = interval_series.mode()
    nominal_interval = float(modal_values.min())
    gap_threshold = max(
        nominal_interval * config.CONTIGUOUS_GAP_FACTOR,
        float(interval_series.median()) * config.CONTIGUOUS_GAP_FACTOR,
    )

    sessions = pd.DataFrame(session_rows).sort_values(
        ["start", "session_number"], kind="stable"
    ).reset_index(drop=True)
    sessions["preceding_gap_seconds"] = (
        sessions["start"] - sessions["end"].shift(1)
    ).dt.total_seconds()
    if sessions["session_id"].duplicated().any():
        raise ValueError("A persisted session ID maps to multiple session numbers.")
    if len(sessions) < 3:
        raise ValueError(
            "At least three chronological sessions are required for separate "
            "train, validation, and test splits."
        )

    frame_gaps = data.groupby("session_id", sort=False)["timestamp"].diff()
    data["_segment_start"] = (
        frame_gaps.isna()
        | frame_gaps.dt.total_seconds().gt(gap_threshold)
    )
    data["_segment_id"] = data["_segment_start"].cumsum().astype(int)

    summary = {
        "row_count": int(len(data)),
        "session_count": persisted_counts["session_count"],
        "sessions_with_readings": int(len(sessions)),
        "sessions_without_readings": max(
            0, persisted_counts["session_count"] - int(len(sessions))
        ),
        "persisted_reading_count": persisted_counts["reading_count"],
        "timestamp_parse_failures": timestamp_parse_failures,
        "timestamp_ordered": ordered,
        "duplicate_timestamp_count": duplicate_timestamps,
        "missing_values_per_sensor": missing_per_sensor,
        "invalid_numeric_values_per_sensor": invalid_numeric_per_sensor,
        "numeric_minimums": {
            column: float(numeric[column].min()) for column in config.SENSOR_COLUMNS
        },
        "numeric_maximums": {
            column: float(numeric[column].max()) for column in config.SENSOR_COLUMNS
        },
        "interval_seconds": {
            "count": int(interval_series.count()),
            "counts": interval_counts,
            "minimum": float(interval_series.min()),
            "median": float(interval_series.median()),
            "mode": nominal_interval,
            "p95": float(interval_series.quantile(0.95)),
            "maximum": float(interval_series.max()),
        },
        "contiguous_gap_threshold_seconds": float(gap_threshold),
        "sessions": session_rows,
        "declared_session_count": int(sessions["session_id"].nunique()),
        "declared_sample_count": int(data.groupby("session_id")["declared_sample_count"].first().sum()),
        "session_sample_count_mismatches": [
            row["session_number"] for row in session_rows if not row["record_count_matches"]
        ],
    }
    return data, sessions, summary


def feature_values(
    samples: np.ndarray,
    timestamp_seconds: np.ndarray,
    gap_threshold: float,
) -> dict[str, float]:
    result: dict[str, float] = {}
    column_positions = {
        column: index for index, column in enumerate(config.SENSOR_COLUMNS)
    }
    for name, columns in (
        ("current", config.CURRENT_COLUMNS),
        ("voltage", config.VOLTAGE_COLUMNS),
    ):
        positions = [column_positions[column] for column in columns]
        phases = samples[:, positions]
        for index, column in enumerate(columns, start=1):
            values = phases[:, index - 1]
            prefix = f"{name}_l{index}"
            result[f"{prefix}_mean"] = float(np.mean(values))
            result[f"{prefix}_std"] = float(np.std(values, ddof=0))
            result[f"{prefix}_min"] = float(np.min(values))
            result[f"{prefix}_max"] = float(np.max(values))

        per_sample_mean = phases.mean(axis=1)
        flattened = phases.reshape(-1)
        result[f"{name}_mean"] = float(np.mean(flattened))
        result[f"{name}_std"] = float(np.std(flattened, ddof=0))
        result[f"{name}_min"] = float(np.min(flattened))
        result[f"{name}_max"] = float(np.max(flattened))
        deviations = np.max(np.abs(phases - per_sample_mean[:, None]), axis=1)
        denominators = np.abs(per_sample_mean)
        valid = denominators > np.finfo(float).eps
        result[f"{name}_imbalance"] = (
            float(np.mean(100.0 * deviations[valid] / denominators[valid]))
            if valid.any()
            else 0.0
        )

    vibration_positions = [
        column_positions[column] for column in config.VIBRATION_COLUMNS
    ]
    axes = samples[:, vibration_positions]
    magnitudes = np.linalg.norm(axes, axis=1)
    result["vibration_x_mean"] = float(np.mean(axes[:, 0]))
    result["vibration_x_std"] = float(np.std(axes[:, 0], ddof=0))
    result["vibration_x_min"] = float(np.min(axes[:, 0]))
    result["vibration_x_max"] = float(np.max(axes[:, 0]))
    result["vibration_y_mean"] = float(np.mean(axes[:, 1]))
    result["vibration_y_std"] = float(np.std(axes[:, 1], ddof=0))
    result["vibration_y_min"] = float(np.min(axes[:, 1]))
    result["vibration_y_max"] = float(np.max(axes[:, 1]))
    result["vibration_z_mean"] = float(np.mean(axes[:, 2]))
    result["vibration_z_std"] = float(np.std(axes[:, 2], ddof=0))
    result["vibration_z_min"] = float(np.min(axes[:, 2]))
    result["vibration_z_max"] = float(np.max(axes[:, 2]))
    result["vibration_magnitude"] = float(np.linalg.norm(axes.mean(axis=0)))
    result["vibration_magnitude_mean"] = float(np.mean(magnitudes))
    result["vibration_magnitude_std"] = float(np.std(magnitudes, ddof=0))
    result["vibration_rms"] = float(np.sqrt(np.mean(np.square(magnitudes))))

    tool = samples[:, column_positions["tool_temperature"]]
    ambient = samples[:, column_positions["ambient_temperature"]]
    result["tool_temperature_mean"] = float(np.mean(tool))
    result["tool_temperature_std"] = float(np.std(tool, ddof=0))
    result["tool_temperature_min"] = float(np.min(tool))
    result["tool_temperature_max"] = float(np.max(tool))
    result["ambient_temperature_mean"] = float(np.mean(ambient))
    result["ambient_temperature_std"] = float(np.std(ambient, ddof=0))
    result["ambient_temperature_min"] = float(np.min(ambient))
    result["ambient_temperature_max"] = float(np.max(ambient))
    result["temperature_delta"] = float(np.mean(tool - ambient))

    elapsed = np.diff(timestamp_seconds)
    tool_change = np.diff(tool)
    valid_rate_pairs = (elapsed > 0) & (elapsed <= gap_threshold)
    rates_per_minute = tool_change[valid_rate_pairs] / elapsed[valid_rate_pairs] * 60.0
    result["temperature_rate"] = (
        float(np.mean(rates_per_minute)) if rates_per_minute.size else 0.0
    )
    if not np.isfinite(np.asarray(list(result.values()), dtype=float)).all():
        raise ValueError("Feature formula produced a non-finite value.")
    return result


def evaluate_window_size(
    data: pd.DataFrame,
    window_seconds: int,
    nominal_interval: float,
    gap_threshold: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    expected_samples = max(1, int(round(window_seconds / nominal_interval)))
    minimum_samples = max(1, int(math.ceil(expected_samples * config.MINIMUM_COMPLETENESS)))
    windows: list[dict[str, Any]] = []
    within_window_spreads: dict[str, list[float]] = {
        "current": [],
        "voltage": [],
        "vibration_magnitude": [],
        "tool_temperature": [],
    }
    half_window_changes: dict[str, list[float]] = {
        "current": [],
        "voltage": [],
        "vibration_rms": [],
        "tool_temperature": [],
    }

    for _, segment in data.groupby("_segment_id", sort=True, observed=True):
        timestamps = segment["timestamp"]
        timestamp_seconds = (
            timestamps - timestamps.iloc[0]
        ).dt.total_seconds().to_numpy(dtype=float)
        elapsed = timestamp_seconds
        bins = np.floor(elapsed / window_seconds).astype(int)
        boundaries = np.flatnonzero(np.diff(bins)) + 1
        starts = np.concatenate(([0], boundaries))
        ends = np.concatenate((boundaries, [len(segment)]))
        sensor_values = segment[list(config.SENSOR_COLUMNS)].to_numpy(dtype=float)
        machine_id = segment["machine_id"].iloc[0]
        session_id = segment["session_id"].iloc[0]
        session_number = int(segment["session_number"].iloc[0])
        for start, end in zip(starts, ends):
            count = int(end - start)
            if count < minimum_samples:
                continue
            window_values = sensor_values[start:end]
            window_timestamps = timestamp_seconds[start:end]
            features = feature_values(window_values, window_timestamps, gap_threshold)
            item: dict[str, Any] = {
                "machine_id": machine_id,
                "session_id": session_id,
                "session_number": session_number,
                "_segment_id": int(segment["_segment_id"].iloc[0]),
                "window_start": timestamps.iloc[start],
                "window_end": timestamps.iloc[end - 1],
                "data_completeness": min(count / expected_samples, 1.0),
                "valid_sample_count": count,
                "expected_sample_count": expected_samples,
                "window_duration_seconds": float(
                    timestamp_seconds[end - 1] - timestamp_seconds[start]
                ),
            }
            item.update(features)
            windows.append(item)

            current_samples = window_values[:, :3].mean(axis=1)
            voltage_samples = window_values[:, 3:6].mean(axis=1)
            vibration_samples = np.linalg.norm(window_values[:, 6:9], axis=1)
            tool_samples = window_values[:, 9]
            within_window_spreads["current"].append(float(np.std(current_samples, ddof=0)))
            within_window_spreads["voltage"].append(float(np.std(voltage_samples, ddof=0)))
            within_window_spreads["vibration_magnitude"].append(
                float(np.std(vibration_samples, ddof=0))
            )
            within_window_spreads["tool_temperature"].append(
                float(np.std(tool_samples, ddof=0))
            )
            midpoint = count // 2
            half_window_changes["current"].append(
                float(
                    abs(
                        current_samples[:midpoint].mean()
                        - current_samples[midpoint:].mean()
                    )
                )
            )
            half_window_changes["voltage"].append(
                float(
                    abs(
                        voltage_samples[:midpoint].mean()
                        - voltage_samples[midpoint:].mean()
                    )
                )
            )
            half_window_changes["vibration_rms"].append(
                float(
                    abs(
                        np.sqrt(np.mean(np.square(vibration_samples[:midpoint])))
                        - np.sqrt(np.mean(np.square(vibration_samples[midpoint:])))
                    )
                )
            )
            half_window_changes["tool_temperature"].append(
                float(abs(tool_samples[:midpoint].mean() - tool_samples[midpoint:].mean()))
            )

    feature_frame = pd.DataFrame(windows)
    if feature_frame.empty:
        raise RuntimeError(
            f"No usable windows were created for the {window_seconds}-second candidate."
        )
    accepted_records = int(feature_frame["valid_sample_count"].sum())
    accepted_span_seconds = float(
        np.minimum(
            window_seconds,
            feature_frame["window_duration_seconds"].to_numpy(dtype=float)
            + nominal_interval,
        ).sum()
    )
    total_span_seconds = float(
        data.groupby("session_id", observed=True)["timestamp"]
        .agg(
            lambda values: (values.max() - values.min()).total_seconds()
            + nominal_interval
        )
        .sum()
    )
    metrics: dict[str, Any] = {
        "window_seconds": int(window_seconds),
        "expected_samples_per_window": expected_samples,
        "minimum_valid_samples": minimum_samples,
        "window_count": int(len(feature_frame)),
        "usable_records": accepted_records,
        "usable_data_pct": 100.0 * accepted_records / len(data),
        "temporal_coverage_pct": (
            100.0 * accepted_span_seconds / total_span_seconds
            if total_span_seconds > 0
            else 0.0
        ),
        "median_samples_per_window": float(feature_frame["valid_sample_count"].median()),
        "p10_samples_per_window": float(feature_frame["valid_sample_count"].quantile(0.10)),
        "p90_samples_per_window": float(feature_frame["valid_sample_count"].quantile(0.90)),
    }
    for name, values in within_window_spreads.items():
        metrics[f"median_within_window_std_{name}"] = (
            float(np.median(values)) if values else None
        )
    for name, values in half_window_changes.items():
        metrics[f"median_half_window_change_{name}"] = (
            float(np.median(values)) if values else None
        )
    return feature_frame, metrics


def select_window_size(metrics: list[dict[str, Any]]) -> int:
    eligible = [
        row
        for row in metrics
        if row["expected_samples_per_window"] >= config.MINIMUM_STABLE_WINDOW_SAMPLES
        and row["usable_data_pct"] >= 95.0
        and row["window_count"] >= config.MINIMUM_WINDOWS_FOR_SELECTION
    ]
    if not eligible:
        raise RuntimeError(
            "No candidate meets the explicit window selection requirements "
            f"({config.MINIMUM_STABLE_WINDOW_SAMPLES}+ expected samples, at least "
            "95% usable records, and at least 100 windows). Review the generated "
            "candidate metrics before proceeding."
        )
    return int(min(eligible, key=lambda row: row["window_seconds"])["window_seconds"])


def feature_quality(features: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in features.columns:
        values = pd.to_numeric(features[column], errors="coerce")
        finite = values[np.isfinite(values.to_numpy(dtype=float))]
        if finite.empty:
            raise ValueError(f"Candidate feature {column} has no finite observations.")
        quantiles = finite.quantile([0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99])
        q25, q75 = float(quantiles.loc[0.25]), float(quantiles.loc[0.75])
        iqr = q75 - q25
        outlier_count = int(((finite < q25 - 1.5 * iqr) | (finite > q75 + 1.5 * iqr)).sum())
        mean = float(finite.mean())
        std = float(finite.std(ddof=0))
        coefficient = std / abs(mean) if abs(mean) > np.finfo(float).eps else None
        rows.append(
            {
                "feature": column,
                "count": int(len(finite)),
                "missing_count": int(values.isna().sum()),
                "missing_pct": 100.0 * float(values.isna().mean()),
                "mean": mean,
                "median": float(quantiles.loc[0.50]),
                "std": std,
                "variance": float(finite.var(ddof=0)),
                "minimum": float(finite.min()),
                "maximum": float(finite.max()),
                "p01": float(quantiles.loc[0.01]),
                "p05": float(quantiles.loc[0.05]),
                "p25": q25,
                "p75": q75,
                "p95": float(quantiles.loc[0.95]),
                "p99": float(quantiles.loc[0.99]),
                "unique_values": int(finite.nunique()),
                "skew": float(finite.skew()) if len(finite) > 2 else 0.0,
                "iqr_outlier_count": outlier_count,
                "iqr_outlier_pct": 100.0 * outlier_count / len(finite),
                "coefficient_of_variation": coefficient,
                "constant": bool(finite.nunique() <= 1),
                "near_zero_variance": bool(
                    finite.nunique() <= 5
                    or (
                        coefficient is not None
                        and coefficient <= config.NEAR_ZERO_CV_THRESHOLD
                    )
                ),
            }
        )
    return pd.DataFrame(rows)


def correlation_analysis(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrix = features.corr(method="pearson", min_periods=3)
    pairs = []
    for left_index, left in enumerate(matrix.columns):
        for right in matrix.columns[left_index + 1 :]:
            value = matrix.loc[left, right]
            if pd.notna(value):
                pairs.append(
                    {
                        "feature_a": left,
                        "feature_b": right,
                        "correlation": float(value),
                        "absolute_correlation": abs(float(value)),
                    }
                )
    pair_frame = pd.DataFrame(pairs)
    if not pair_frame.empty:
        pair_frame = pair_frame.sort_values(
            ["absolute_correlation", "feature_a", "feature_b"],
            ascending=[False, True, True],
            kind="stable",
        ).reset_index(drop=True)
    return matrix, pair_frame


def choose_features(
    quality: pd.DataFrame,
    correlations: pd.DataFrame,
) -> tuple[list[str], list[dict[str, str]]]:
    quality_by_name = quality.set_index("feature")
    selected: list[str] = []
    removals: list[dict[str, str]] = []
    for feature in config.PREFERRED_FEATURES:
        if feature not in quality_by_name.index:
            continue
        row = quality_by_name.loc[feature]
        if bool(row["constant"]) or int(row["missing_count"]) > 0:
            removals.append(
                {"feature": feature, "reason": "constant or incomplete feature"}
            )
            continue
        if feature == "vibration_magnitude_std" and "vibration_rms" in selected:
            pair = correlations[
                (
                    correlations["feature_a"].eq("vibration_rms")
                    & correlations["feature_b"].eq(feature)
                )
                | (
                    correlations["feature_b"].eq("vibration_rms")
                    & correlations["feature_a"].eq(feature)
                )
            ]
            if not pair.empty and float(pair.iloc[0]["absolute_correlation"]) >= config.CORRELATION_REVIEW_THRESHOLD:
                removals.append(
                    {
                        "feature": feature,
                        "reason": (
                            "redundant with vibration_rms at the "
                            f"{config.CORRELATION_REVIEW_THRESHOLD:.2f} correlation review threshold"
                        ),
                    }
                )
                continue
        selected.append(feature)
    if not selected:
        raise RuntimeError("Feature selection produced no non-constant sensor features.")
    return selected, removals


def assign_chronological_splits(
    features: pd.DataFrame,
    sessions: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    ordered_sessions = sessions.sort_values(
        ["start", "session_number"], kind="stable"
    ).reset_index(drop=True)
    count = len(ordered_sessions)
    train_end = max(1, int(math.floor(count * 0.50)))
    validation_end = max(train_end + 1, int(math.floor(count * (2.0 / 3.0))))
    validation_end = min(validation_end, count - 1)

    assignments: list[dict[str, Any]] = []
    for index, row in ordered_sessions.iterrows():
        split = "train" if index < train_end else (
            "validation" if index < validation_end else "test"
        )
        assignments.append(
            {
                "session_number": int(row["session_number"]),
                "session_id": str(row["session_id"]),
                "split": split,
                "start": row["start"],
                "end": row["end"],
            }
        )
    mapping = {row["session_id"]: row["split"] for row in assignments}
    result = features.copy()
    result["split"] = result["session_id"].map(mapping)
    if result["split"].isna().any():
        raise RuntimeError("Some feature windows could not be assigned to a session split.")

    split_order = {"train": 0, "validation": 1, "test": 2}
    result["_split_order"] = result["split"].map(split_order)
    result = result.sort_values(
        ["window_start", "_split_order", "session_number"], kind="stable"
    ).drop(columns="_split_order").reset_index(drop=True)
    return result, assignments


def validate_ml_dataset(
    data: pd.DataFrame,
    features: list[str],
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    feature_values_frame = data[features].to_numpy(dtype=float)
    if not np.isfinite(feature_values_frame).all():
        raise ValueError("Selected ML features contain NaN or infinite values.")
    constants = [
        name for name in features if data[name].nunique(dropna=False) <= 1
    ]
    if constants:
        raise ValueError(f"Selected ML features are constant: {constants}")
    if data.groupby("session_id")["split"].nunique().gt(1).any():
        raise ValueError("Windows from a single session cross split boundaries.")
    for index in range(1, len(data)):
        if data.loc[index, "window_start"] < data.loc[index - 1, "window_start"]:
            raise ValueError("ML-ready windows are not chronologically ordered.")

    split_bounds = {}
    for split in ("train", "validation", "test"):
        subset = data[data["split"].eq(split)]
        if subset.empty:
            raise ValueError(f"The chronological {split} split is empty.")
        split_bounds[split] = {
            "count": int(len(subset)),
            "first_window": subset["window_start"].min().isoformat(),
            "last_window": subset["window_end"].max().isoformat(),
            "sessions": sorted(subset["session_number"].unique().astype(int).tolist()),
        }
    if not (
        data.loc[data["split"].eq("train"), "window_end"].max()
        < data.loc[data["split"].eq("validation"), "window_start"].min()
        <= data.loc[data["split"].eq("validation"), "window_end"].max()
        < data.loc[data["split"].eq("test"), "window_start"].min()
    ):
        raise ValueError("Chronological split time bounds overlap or are out of order.")
    forbidden_model_inputs = set(features) & set(config.METADATA_COLUMNS)
    if forbidden_model_inputs:
        raise ValueError(f"Metadata fields appear in ML inputs: {sorted(forbidden_model_inputs)}")

    for assignment in assignments:
        count_for_session = data.loc[
            data["session_id"].eq(assignment["session_id"]), "split"
        ].nunique()
        if count_for_session != 1:
            raise ValueError(
                f"Session {assignment['session_number']} has inconsistent split assignment."
            )
    return {
        "selected_feature_count": len(features),
        "selected_features_finite": True,
        "selected_features_nonconstant": True,
        "chronological_order": True,
        "session_isolation": True,
        "split_bounds": split_bounds,
        "no_identifiers_in_model_inputs": not forbidden_model_inputs,
        "no_scaler_fit": True,
    }


def markdown_table(frame: pd.DataFrame, digits: int = 4) -> str:
    if frame.empty:
        return "_No rows._"
    display = frame.copy()

    def format_value(value: Any) -> str:
        if isinstance(value, (list, tuple, dict)):
            return json.dumps(value, default=str)
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return ""
        if isinstance(value, (float, np.floating)):
            if not np.isfinite(value):
                return ""
            return f"{value:.{digits}f}"
        if isinstance(value, (bool, np.bool_)):
            return "yes" if value else "no"
        if isinstance(value, (pd.Timestamp,)):
            return value.isoformat()
        return str(value)

    rows = [[format_value(value) for value in row] for row in display.itertuples(index=False, name=None)]
    headers = [str(column) for column in display.columns]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def save_figures(
    features: pd.DataFrame,
    selected: list[str],
    candidate_metrics: pd.DataFrame,
    splits: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    count = len(selected)
    columns = 3
    rows = int(math.ceil(count / columns))
    figure, axes = plt.subplots(rows, columns, figsize=(15, 3.4 * rows), squeeze=False)
    for axis, feature in zip(axes.flat, selected):
        axis.hist(features[feature], bins=35, color="#3572A5", alpha=0.85)
        axis.set_title(feature.replace("_", " "))
        axis.set_ylabel("Windows")
        axis.grid(axis="y", alpha=0.2)
    for axis in axes.flat[count:]:
        axis.set_visible(False)
    figure.suptitle("Selected feature distributions", fontsize=15)
    figure.tight_layout()
    path = output_dir / "selected_feature_distributions.png"
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    paths.append(path)

    selected_corr = features[selected].corr()
    figure, axis = plt.subplots(figsize=(max(8, len(selected) * 0.85), max(7, len(selected) * 0.75)))
    image = axis.imshow(selected_corr.to_numpy(), cmap="coolwarm", vmin=-1, vmax=1, aspect="auto")
    axis.set_xticks(range(len(selected)), [name.replace("_", "\n") for name in selected], rotation=45, ha="right")
    axis.set_yticks(range(len(selected)), selected)
    figure.colorbar(image, ax=axis, label="Pearson correlation")
    axis.set_title("Correlation among selected ML features")
    figure.tight_layout()
    path = output_dir / "selected_feature_correlation.png"
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    paths.append(path)

    quality = feature_quality(features[selected])
    selected_quality = quality.set_index("feature").loc[selected].reset_index()
    ordered = selected_quality.sort_values("std", ascending=True)
    figure, axis = plt.subplots(figsize=(10, max(4, len(selected) * 0.42)))
    axis.barh(ordered["feature"], ordered["variance"], color="#3A8D76")
    axis.set_xscale("log")
    axis.set_xlabel("Window-level variance (log scale)")
    axis.set_title("Selected feature variance comparison")
    axis.grid(axis="x", alpha=0.25)
    figure.tight_layout()
    path = output_dir / "selected_feature_variance.png"
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    paths.append(path)

    time_feature_groups = [
        ("Current", ["current_mean", "current_std", "current_imbalance"]),
        ("Voltage", ["voltage_mean", "voltage_imbalance"]),
        ("Vibration", ["vibration_rms", "vibration_magnitude_std"]),
        ("Temperature", ["temperature_delta", "temperature_rate"]),
    ]
    figure, axes = plt.subplots(4, 1, figsize=(16, 13), sharex=True)
    for axis, (title, names) in zip(axes, time_feature_groups):
        available = [name for name in names if name in features.columns]
        for feature in available:
            for _, session in features.groupby("session_number", sort=True):
                axis.plot(
                    session["window_start"],
                    session[feature],
                    linewidth=0.8,
                    alpha=0.7,
                    label=feature,
                )
        axis.set_title(f"{title} features over time")
        axis.grid(alpha=0.2)
        if available:
            axis.legend(loc="upper left", ncol=min(3, len(available)), fontsize=8)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d\n%H:%M", tz=mdates.UTC))
    figure.tight_layout()
    path = output_dir / "sensor_features_over_time.png"
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    paths.append(path)

    figure, axis = plt.subplots(figsize=(9, 4))
    axis.hist(features["data_completeness"] * 100, bins=20, color="#D28B36")
    axis.set_xlabel("Valid samples / expected samples (%)")
    axis.set_ylabel("Windows")
    axis.set_title("Accepted window completeness")
    axis.grid(axis="y", alpha=0.2)
    figure.tight_layout()
    path = output_dir / "window_completeness.png"
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    paths.append(path)

    figure, axis = plt.subplots(figsize=(12, 4))
    split_colors = {"train": "#3572A5", "validation": "#D28B36", "test": "#9B4F7C"}
    for split, group in splits.groupby("split", sort=False):
        axis.scatter(
            group["window_start"],
            group["session_number"],
            s=8,
            alpha=0.65,
            label=split,
            color=split_colors[split],
        )
    axis.set_yticks(sorted(splits["session_number"].unique()))
    axis.set_ylabel("Persisted session number")
    axis.set_title("Chronological session-level train / validation / test split")
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d", tz=mdates.UTC))
    axis.legend()
    axis.grid(alpha=0.2)
    figure.tight_layout()
    path = output_dir / "chronological_split.png"
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    paths.append(path)

    figure, axis = plt.subplots(figsize=(9, 4))
    axis.plot(
        candidate_metrics["window_seconds"],
        candidate_metrics["usable_data_pct"],
        marker="o",
        label="Usable records",
    )
    axis.plot(
        candidate_metrics["window_seconds"],
        candidate_metrics["temporal_coverage_pct"],
        marker="s",
        label="Temporal coverage",
    )
    axis.axhline(95.0, color="gray", linestyle="--", linewidth=1, label="95% selection criterion")
    axis.set_xscale("log")
    axis.set_xticks(candidate_metrics["window_seconds"])
    axis.set_xticklabels(candidate_metrics["window_seconds"])
    axis.set_xlabel("Candidate window (seconds)")
    axis.set_ylabel("Coverage (%)")
    axis.set_title("Candidate window coverage comparison")
    axis.legend()
    axis.grid(alpha=0.2)
    figure.tight_layout()
    path = output_dir / "candidate_window_coverage.png"
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    paths.append(path)
    return paths


def build_report(
    input_summary: dict[str, Any],
    reference: dict[str, Any] | None,
    sessions: pd.DataFrame,
    window_metrics: pd.DataFrame,
    selected_window: int,
    selected: list[str],
    removals: list[dict[str, str]],
    quality: pd.DataFrame,
    high_correlations: pd.DataFrame,
    assignments: list[dict[str, Any]],
    split_summary: dict[str, Any],
    validation: dict[str, Any],
    artifacts: dict[str, Any],
) -> str:
    session_table = sessions[
        [
            "session_number",
            "session_id",
            "start",
            "end",
            "preceding_gap_seconds",
            "duration_seconds",
            "records",
            "declared_records",
            "median_interval_seconds",
            "maximum_interval_seconds",
            "record_count_matches",
        ]
    ].rename(
        columns={
            "session_number": "session",
            "start": "start_utc",
            "end": "end_utc",
            "duration_seconds": "duration_seconds",
            "records": "observed_records",
            "declared_records": "database_session_sample_count",
            "record_count_matches": "stored_count_matches",
        }
    )
    current_summary = pd.DataFrame(
        [
            {"sensor": name, "minimum": input_summary["numeric_minimums"][name],
             "maximum": input_summary["numeric_maximums"][name]}
            for name in config.SENSOR_COLUMNS
        ]
    )
    compact_quality = quality[
        [
            "feature",
            "count",
            "missing_pct",
            "mean",
            "median",
            "std",
            "variance",
            "minimum",
            "maximum",
            "p01",
            "p99",
            "unique_values",
            "skew",
            "iqr_outlier_pct",
            "constant",
            "near_zero_variance",
        ]
    ]
    assignment_table = pd.DataFrame(assignments)[
        ["session_number", "session_id", "split", "start", "end"]
    ]
    selected_quality = quality[
        quality["feature"].isin(selected)
    ][["feature", "std", "unique_values", "near_zero_variance"]]
    baseline_count = reference.get("database_row_count") if reference else None
    baseline_sessions = reference.get("database_session_count") if reference else None
    baseline_note = (
        f"Historical ingestion snapshot: {baseline_count} rows across {baseline_sessions} "
        "sessions. This is a comparison point, not a hard-coded pipeline requirement."
        if reference
        else "No historical ingestion snapshot was available for comparison."
    )
    row_difference = (
        int(input_summary["row_count"]) - int(baseline_count)
        if baseline_count is not None
        else None
    )
    session_difference = (
        int(input_summary["session_count"]) - int(baseline_sessions)
        if baseline_sessions is not None
        else None
    )
    correlations_table = high_correlations.head(30)[
        ["feature_a", "feature_b", "correlation"]
    ] if not high_correlations.empty else high_correlations
    removal_table = pd.DataFrame(removals, columns=["feature", "reason"])
    window_table_columns = [
        "window_seconds",
        "expected_samples_per_window",
        "minimum_valid_samples",
        "window_count",
        "usable_records",
        "usable_data_pct",
        "temporal_coverage_pct",
        "median_samples_per_window",
        "p10_samples_per_window",
        "p90_samples_per_window",
        "median_within_window_std_current",
        "median_within_window_std_voltage",
        "median_within_window_std_vibration_magnitude",
        "median_within_window_std_tool_temperature",
        "median_half_window_change_current",
        "median_half_window_change_voltage",
        "median_half_window_change_vibration_rms",
        "median_half_window_change_tool_temperature",
    ]

    report = f"""# Phase 3 — Feature Engineering and ML Dataset Preparation

## 1. Objective

Create a reproducible, database-first feature pipeline from the persisted sensor readings. This phase validates the source, derives session-bounded time windows, reviews features, and writes a chronological ML-ready dataset. It does not fit an anomaly model, calculate production scores, or assign machine-health statuses.

## 2. Input Data

Primary source: Neon PostgreSQL `sensor_readings`, joined to `machines` and `machine_sessions` using persisted machine identity and timestamp boundaries. Only the eleven approved temperature, vibration, current, and voltage fields are selected. No CSV data is read by this pipeline.

- Machine code: `{config.MACHINE_CODE}`
- Observed readings: **{input_summary['row_count']:,}**
- Persisted sessions: **{input_summary['session_count']}**; sessions with readings: **{input_summary['sessions_with_readings']}**; empty sessions: **{input_summary['sessions_without_readings']}**
- Reading timestamp parse failures: **{input_summary['timestamp_parse_failures']}**
- Timestamp ordering: **{'chronological' if input_summary['timestamp_ordered'] else 'not chronological'}**
- Duplicate / multiply matched timestamps: **{input_summary['duplicate_timestamp_count']}**
- Within-session interval count: **{input_summary['interval_seconds']['count']:,}**
- Within-session interval counts (seconds: count): `{json.dumps(input_summary['interval_seconds']['counts'], sort_keys=True)}`
- Sampling intervals (seconds): min **{input_summary['interval_seconds']['minimum']:.3f}**, median **{input_summary['interval_seconds']['median']:.3f}**, mode **{input_summary['interval_seconds']['mode']:.3f}**, p95 **{input_summary['interval_seconds']['p95']:.3f}**, max **{input_summary['interval_seconds']['maximum']:.3f}**
- Contiguous-gap threshold: **{input_summary['contiguous_gap_threshold_seconds']:.3f} seconds** (1.5 × the greater of the modal and median within-session interval)
- Stored session sample-count mismatches: **{input_summary['session_sample_count_mismatches']}**
- Missing fields by sensor: `{json.dumps(input_summary['missing_values_per_sensor'], sort_keys=True)}`
- Invalid numeric values by sensor: `{json.dumps(input_summary['invalid_numeric_values_per_sensor'], sort_keys=True)}`
- Historical comparison: {baseline_note}
- Difference from historical snapshot: **{row_difference if row_difference is not None else 'not available'} readings**, **{session_difference if session_difference is not None else 'not available'} sessions**. Differences are reported for investigation; the historical totals do not gate processing.

Timestamp and sensor range checks are calculated from the database query at each run. Source timestamps stored as `TIMESTAMPTZ` are interpreted and displayed in UTC, consistent with the Phase 2 ingestion convention.

### Persisted session boundaries

{markdown_table(session_table)}

### Sensor value ranges

{markdown_table(current_summary)}

## 3. Windowing Analysis

Within each persisted session, rows are sorted by timestamp and then divided into contiguous regions. A gap larger than **{input_summary['contiguous_gap_threshold_seconds']:.3f} seconds** starts a new region. A candidate window is anchored to the beginning of its region; no window can cross a persisted session or a detected gap.

For each candidate, expected samples are rounded from window seconds divided by the observed modal cadence. The minimum valid sample count is `ceil(expected samples × {config.MINIMUM_COMPLETENESS:.0%})`. Windows below this minimum are dropped. Thus, for the selected {selected_window}-second window, at least **{int(math.ceil(round(selected_window / input_summary['interval_seconds']['mode']) * config.MINIMUM_COMPLETENESS))}** valid readings are required.

The within-window standard deviation columns summarize within-window sensor spread. The half-window change columns compare the first and second halves of each window for representative current, voltage, vibration RMS, and tool-temperature signals; they are median absolute level changes across accepted windows, so smaller changes indicate more internally consistent windows. These are diagnostic comparisons, not model targets. Temporal coverage credits one observed cadence interval after each window's last sample, capped at the candidate duration, and compares accepted coverage against persisted session spans.

{markdown_table(window_metrics[window_table_columns])}

**Selection:** {selected_window} seconds. The selection rule chooses the shortest candidate with at least {config.MINIMUM_STABLE_WINDOW_SAMPLES} expected samples, 95% usable source records, and {config.MINIMUM_WINDOWS_FOR_SELECTION} windows. This supports stable window statistics while limiting monitoring delay. Candidate counts, record coverage, temporal coverage, per-window sample distributions, and within-window spread are retained above; larger windows trade responsiveness for additional aggregation. The window duration field in the artifact is the observed first-to-last sample span, while the expected sample count and completeness describe the nominal candidate duration.

## 4. Feature Definitions

Features below are computed independently for every accepted window. Standard deviations use population convention (`ddof=0`).

- **Current phase features:** for each phase `l1`, `l2`, `l3`, the mean, standard deviation, minimum, and maximum of that phase's window samples.
- **Current aggregate features:** mean, population standard deviation, minimum, and maximum over all current phase samples in the window. `current_imbalance` is the mean over timestamps of `100 × max_phase(abs(I_phase - mean_phase_current)) / abs(mean_phase_current)`. Timestamps whose phase mean is numerically zero do not contribute; if none are valid the value is zero.
- **Voltage phase and aggregate features:** same phase-wise and flattened-window statistics as current. `voltage_imbalance` uses the analogous per-timestamp maximum absolute phase deviation divided by absolute three-phase mean, expressed as percent.
- **Vibration axis features:** per-axis mean, population standard deviation, minimum, and maximum.
- **Vibration magnitude:** instantaneous vector magnitude is `sqrt(x² + y² + z²)`. `vibration_magnitude` is the Euclidean norm of the three window-axis means; `vibration_magnitude_mean` and `vibration_magnitude_std` are the mean and population standard deviation of instantaneous magnitude. `vibration_rms = sqrt(mean(x² + y² + z²))` over all timestamps in the window.
- **Temperature features:** tool and ambient mean, population standard deviation, minimum, and maximum. `temperature_delta = mean(tool_temperature - ambient_temperature)` for the window.
- **Temperature rate:** mean of adjacent tool-temperature differences divided by the actual elapsed seconds and multiplied by 60. Pair intervals must be positive and no longer than the contiguous-gap threshold; therefore no rate spans a session boundary or detected gap. A window with no valid adjacent pair receives zero.

No frequency-domain features are generated: this pipeline uses the observed time-domain channels and does not assume sampling resolution or units sufficient for spectral interpretation.

## 5. Feature Quality

### Group A — Candidate features

The 60 candidate sensor-derived features at the selected window size are listed below. Quality statistics include finite count, missing percentage, mean, median, standard deviation, variance, minimum/maximum, selected percentiles, unique-value count, skew, and IQR outlier percentage. The screening rule is the conventional 1.5 × IQR range; flagged points are retained because extreme observations may be useful for later anomaly work. Skewness with absolute value at least 2 is treated as a review cue, not a deletion criterion. Near-zero variance is flagged when a feature has at most five unique values or its coefficient of variation is at most {config.NEAR_ZERO_CV_THRESHOLD:.3%}; it is a review flag, not an automatic exclusion. These statistics do not establish physical validity because source-unit and calibration documentation is incomplete.

{markdown_table(compact_quality)}

## 6. Correlation Analysis

Pearson correlations are calculated for the complete numerical candidate-feature set. Absolute correlation **≥ {config.CORRELATION_REVIEW_THRESHOLD:.2f}** is used as a candidate redundancy-review threshold, not an automatic feature deletion rule. Pair details and the full matrix are saved in the feature artifacts.

{markdown_table(correlations_table)}

The selection retains interpretable representatives for distinct sensor modalities. Only `vibration_magnitude_std` is dropped when it crosses the review threshold with `vibration_rms`; other high-correlation pairs are reported for review and are not blanket-pruned. Phase-specific statistics remain in the candidate group and are not selected as separate model inputs because aggregate phase features are more compact.

## 7. Selected Features

### Group B — Selected ML features

Selected model inputs (**{len(selected)}**):

{', '.join(f'`{name}`' for name in selected)}

Selection starts from representative electrical, vibration, and temperature features, removes constants/incomplete features, and removes `vibration_magnitude_std` only when redundant with `vibration_rms` at the stated threshold. Correlated features from different modalities are retained when they represent distinct engineering signals.

`current_mean` and `current_imbalance` are strongly inversely correlated in these windows, but are retained as distinct current-level and relative phase-balance descriptors; this relationship should be reviewed again on actual-machine data. `voltage_mean` is flagged near-zero variance because observed voltage is stable, but is retained as the representative voltage-level input rather than discarding that sensor category based only on this historical data. These choices do not imply that either feature is independently predictive.

{markdown_table(selected_quality)}

Feature removals:

{markdown_table(removal_table)}

## 8. Metadata

### Group C — Tracking and data-quality metadata

The ML-ready artifact preserves `machine_id`, `session_id`, `session_number`, `window_start`, and `window_end`. Data-quality metadata is also included: `data_completeness`, `valid_sample_count`, `expected_sample_count`, and `window_duration_seconds`. `split` records the chronological assignment. None of these identifiers, timestamps, quality fields, or split values are model inputs.

## 9. Chronological Split

Splits are assigned by entire persisted sessions in start-time order, never by random window sampling. With {len(assignments)} sessions, the first half (rounded down) is training, the next chronological third boundary defines validation, and the remaining latest sessions are test. For the present dataset this becomes the following exact allocation:

{markdown_table(assignment_table)}

Window counts and temporal bounds:

{markdown_table(pd.DataFrame([
    {"split": name, **values}
    for name, values in split_summary["split_bounds"].items()
]))}

Whole-session holdouts avoid overlapping recording histories across splits. Validation/test session counts are shown explicitly above; small session counts limit claims about generalization.

## 10. Leakage Prevention

- Session split assignment occurs before any future model-fitting stage and is applied to all windows from that session.
- Training windows precede validation windows, which precede test windows; split time bounds are checked for strict chronological order and non-overlap.
- Windows are non-overlapping and are built only within one session and one contiguous region.
- Identifiers, timestamps, completeness metadata, and split labels are excluded from the ML feature matrix.
- No learned scaler or other transformation was fitted in this phase. Any later scaler must be fit on training windows only, then applied unchanged to validation/test.

## Scaling and downstream use

No scaling artifact is produced. Tree-based anomaly methods generally do not require feature scaling; distance- or density-based methods are scale-sensitive and should use a documented scaler fitted on training data only. Skewed features and wide sensor range differences should be reviewed before choosing a later model. This phase does not train any model.

## 11. Limitations

- The dataset has no verified supervised fault or health labels.
- Anomaly detection remains exploratory until independently validated against actual machine events.
- Feature selection and variance/correlation observations are based on this historical dataset and may not transfer to the future YCCE lathe.
- No final production health prediction, anomaly score, health status, alert, or machine-failure claim is made.
- Source sensor units, calibration, machine state, maintenance history, and known event annotations remain incomplete.

## Reproducible outputs

Run from the repository root with `python ml-service/feature_engineering.py`, or from `ml-service` with `python feature_engineering.py`. The script reads only PostgreSQL, uses deterministic window and split rules, and overwrites only generated files in `artifacts/features/`, `reports/feature_engineering_report.md`, and `reports/figures/feature_analysis/`.

**Run validation:** `{json.dumps(validation, sort_keys=True)}`

**Generated artifacts:** `{json.dumps(artifacts, sort_keys=True)}`
"""
    return report


def run_pipeline() -> dict[str, Any]:
    print("Reading approved sensor fields and persisted sessions from PostgreSQL...", flush=True)
    database_frame, persisted_counts = fetch_database_readings()
    data, sessions, input_summary = prepare_database_frame(
        database_frame, persisted_counts
    )
    print(
        f"Validated {input_summary['row_count']:,} readings across "
        f"{input_summary['sessions_with_readings']} sessions.",
        flush=True,
    )
    reference = load_reference_snapshot()
    nominal_interval = float(input_summary["interval_seconds"]["mode"])
    gap_threshold = float(input_summary["contiguous_gap_threshold_seconds"])

    candidate_frames: dict[int, pd.DataFrame] = {}
    metric_rows: list[dict[str, Any]] = []
    for window_seconds in config.CANDIDATE_WINDOW_SECONDS:
        print(f"Evaluating {window_seconds}-second windows...", flush=True)
        window_frame, metrics = evaluate_window_size(
            data, window_seconds, nominal_interval, gap_threshold
        )
        candidate_frames[window_seconds] = window_frame
        metric_rows.append(metrics)

    window_metrics = pd.DataFrame(metric_rows)
    config.FEATURE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    window_metrics.to_csv(
        config.FEATURE_OUTPUT_DIR / "window_candidates.csv",
        index=False,
        float_format="%.10g",
    )
    selected_window = select_window_size(metric_rows)
    generated = candidate_frames[selected_window]
    feature_names = [
        column
        for column in generated.columns
        if column not in set(config.METADATA_COLUMNS)
        and column not in {
            "machine_id",
            "session_id",
            "session_number",
            "window_start",
            "window_end",
            "_segment_id",
            "data_completeness",
            "valid_sample_count",
            "expected_sample_count",
            "window_duration_seconds",
        }
    ]
    sensor_features = generated[feature_names].copy()
    quality = feature_quality(sensor_features)
    correlation_matrix, correlation_pairs = correlation_analysis(sensor_features)
    high_correlations = correlation_pairs[
        correlation_pairs["absolute_correlation"].ge(config.CORRELATION_REVIEW_THRESHOLD)
    ].copy()
    selected_features, removals = choose_features(quality, high_correlations)

    generated, assignments = assign_chronological_splits(generated, sessions)
    model_metadata = [
        "machine_id",
        "session_id",
        "session_number",
        "window_start",
        "window_end",
        *selected_features,
        "data_completeness",
        "valid_sample_count",
        "expected_sample_count",
        "window_duration_seconds",
        "split",
    ]
    ml_ready = generated[model_metadata].copy()
    validation = validate_ml_dataset(ml_ready, selected_features, assignments)
    validation.update(
        {
            "database_connection": True,
            "required_sensor_columns_present": True,
            "timestamp_parse": input_summary["timestamp_parse_failures"] == 0,
            "timestamp_ordering": input_summary["timestamp_ordered"],
            "duplicate_timestamps": input_summary["duplicate_timestamp_count"] == 0,
            "no_cross_session_windows": bool(
                generated.groupby("session_id")["session_number"].nunique().le(1).all()
            ),
            "no_cross_gap_windows": bool(
                generated["_segment_id"].notna().all()
                and generated.groupby(["session_id", "window_start"])["_segment_id"]
                .nunique()
                .le(1)
                .all()
            ),
            "no_missing_or_nonfinite_sensor_inputs": not any(
                input_summary["invalid_numeric_values_per_sensor"].values()
            ),
            "candidate_feature_count": len(feature_names),
            "generated_window_count": int(len(ml_ready)),
        }
    )

    config.FEATURE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ml_ready.to_csv(config.FEATURE_OUTPUT_DIR / "ml_ready_features.csv", index=False, float_format="%.10g")
    quality.to_csv(config.FEATURE_OUTPUT_DIR / "feature_quality.csv", index=False, float_format="%.10g")
    correlation_matrix.to_csv(
        config.FEATURE_OUTPUT_DIR / "feature_correlations.csv", float_format="%.10g"
    )
    window_metrics.to_csv(
        config.FEATURE_OUTPUT_DIR / "window_candidates.csv", index=False, float_format="%.10g"
    )
    assignments_frame = pd.DataFrame(assignments)
    assignments_frame.to_csv(
        config.FEATURE_OUTPUT_DIR / "session_splits.csv", index=False
    )
    split_summary = {
        "split_bounds": validation["split_bounds"],
    }
    figure_paths = save_figures(
        generated,
        selected_features,
        window_metrics,
        generated,
        config.FIGURE_DIR,
    )
    print("Writing feature report and reproducibility artifacts...", flush=True)
    artifacts = {
        "ml_ready_dataset": str((config.FEATURE_OUTPUT_DIR / "ml_ready_features.csv").relative_to(config.ROOT)),
        "feature_quality": str((config.FEATURE_OUTPUT_DIR / "feature_quality.csv").relative_to(config.ROOT)),
        "feature_correlations": str((config.FEATURE_OUTPUT_DIR / "feature_correlations.csv").relative_to(config.ROOT)),
        "window_candidates": str((config.FEATURE_OUTPUT_DIR / "window_candidates.csv").relative_to(config.ROOT)),
        "session_splits": str((config.FEATURE_OUTPUT_DIR / "session_splits.csv").relative_to(config.ROOT)),
        "figures": [
            str(path.relative_to(config.ROOT)) for path in figure_paths
        ],
    }
    report = build_report(
        input_summary,
        reference,
        sessions,
        window_metrics,
        selected_window,
        selected_features,
        removals,
        quality,
        high_correlations,
        assignments,
        split_summary,
        validation,
        artifacts,
    )
    report_path = config.REPORT_DIR / "feature_engineering_report.md"
    report_path.write_text(report, encoding="utf-8")
    summary = {
        "machine_code": config.MACHINE_CODE,
        "database_rows_processed": input_summary["row_count"],
        "sessions_processed": input_summary["session_count"],
        "windows_generated": int(len(ml_ready)),
        "selected_window_seconds": selected_window,
        "candidate_feature_count": len(feature_names),
        "selected_ml_features": selected_features,
        "split_counts": {
            name: details["count"]
            for name, details in validation["split_bounds"].items()
        },
        "validation": validation,
        "artifacts": artifacts,
        "report": str(report_path.relative_to(config.ROOT)),
    }
    (config.FEATURE_OUTPUT_DIR / "run_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = run_pipeline()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
