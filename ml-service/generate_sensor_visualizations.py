#!/usr/bin/env python
"""Generate sensor and selected-feature plots without changing analysis artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as nps
import pandas as pd

import feature_config as config
from feature_engineering import fetch_database_readings


EXPECTED_FEATURES = [
    "current_mean",
    "current_std",
    "current_imbalance",
    "voltage_mean",
    "voltage_imbalance",
    "vibration_rms",
    "vibration_magnitude_std",
    "temperature_delta",
    "temperature_rate",
]
FEATURE_FILE = config.FEATURE_OUTPUT_DIR / "ml_ready_features.csv"
RUN_SUMMARY_FILE = config.FEATURE_OUTPUT_DIR / "run_summary.json"
NOVEMBER_START = pd.Timestamp("2026-11-01T00:00:00Z")
DECEMBER_START = pd.Timestamp("2026-12-01T00:00:00Z")
SESSION_COLORS = plt.get_cmap("tab10").colors[:6]


def validate_timestamp_range(timestamps: pd.Series, label: str) -> None:
    if timestamps.empty or timestamps.isna().any():
        raise ValueError(f"{label} timestamps are empty or invalid.")
    minimum = timestamps.min()
    maximum = timestamps.max()
    if minimum < NOVEMBER_START or maximum >= DECEMBER_START:
        raise ValueError(
            f"{label} timestamps are outside November 2026: "
            f"{minimum.isoformat()} through {maximum.isoformat()}."
        )


def save_figure(
    figure: plt.Figure,
    filename: str,
    timestamps: pd.Series,
    series: tuple[str, ...],
) -> Path:
    validate_timestamp_range(timestamps, filename)
    path = config.FIGURE_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        metadata={
            "Title": filename,
            "Description": (
                f"UTC timestamps: {timestamps.min().isoformat()} through "
                f"{timestamps.max().isoformat()}; series: {', '.join(series)}"
            ),
        },
    )
    plt.close(figure)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Figure was not written successfully: {path}")
    return path


def load_sensor_readings() -> pd.DataFrame:
    readings, counts = fetch_database_readings()
    if len(readings) != 67_258 or counts["reading_count"] != 67_258:
        raise ValueError(
            "Expected 67,258 persisted sensor readings; "
            f"received {len(readings)} rows."
        )
    if counts["session_count"] != 6:
        raise ValueError(f"Expected six persisted sessions, found {counts['session_count']}.")

    readings["timestamp"] = pd.to_datetime(
        readings["timestamp"], utc=True, errors="coerce"
    )
    readings["session_start"] = pd.to_datetime(
        readings["session_start"], utc=True, errors="coerce"
    )
    readings["session_end"] = pd.to_datetime(
        readings["session_end"], utc=True, errors="coerce"
    )
    if readings[["timestamp", "session_start", "session_end"]].isna().any().any():
        raise ValueError("Database returned invalid measurement or session timestamps.")
    if not readings["timestamp"].is_monotonic_increasing:
        raise ValueError("Database readings are not in chronological order.")
    if readings["timestamp"].duplicated().any():
        raise ValueError("Database readings contain duplicate timestamps.")

    session_numbers = sorted(readings["session_number"].astype(int).unique().tolist())
    if session_numbers != [1, 2, 3, 4, 5, 6]:
        raise ValueError(f"Expected sessions 1-6, found {session_numbers}.")

    for column in config.SENSOR_COLUMNS:
        values = pd.to_numeric(readings[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"Sensor channel {column} contains invalid values.")
        readings[column] = values

    validate_timestamp_range(readings["timestamp"], "Database sensor")
    if readings["timestamp"].min() != pd.Timestamp("2026-11-01T09:03:01Z"):
        raise ValueError("Database sensor timestamp minimum does not match the shifted data.")
    if readings["timestamp"].max() != pd.Timestamp("2026-11-07T18:15:21Z"):
        raise ValueError("Database sensor timestamp maximum does not match the shifted data.")

    if not (
        readings["timestamp"].ge(readings["session_start"])
        & readings["timestamp"].le(readings["session_end"])
    ).all():
        raise ValueError("Some readings fall outside their persisted session boundaries.")
    for _, session in readings.groupby("session_number", sort=True):
        declared_counts = session["declared_sample_count"].astype(int).unique()
        if len(declared_counts) != 1 or len(session) != declared_counts[0]:
            raise ValueError(
                f"Session {int(session['session_number'].iloc[0])} does not match "
                "its persisted sample count."
            )
    return readings


def load_selected_features() -> pd.DataFrame:
    if not FEATURE_FILE.is_file() or not RUN_SUMMARY_FILE.is_file():
        raise FileNotFoundError("The existing Phase 3 feature artifacts are required.")
    summary: dict[str, Any] = json.loads(RUN_SUMMARY_FILE.read_text(encoding="utf-8"))
    if summary.get("selected_ml_features") != EXPECTED_FEATURES:
        raise ValueError("The recorded selected-feature list differs from the required list.")
    if summary.get("selected_window_seconds") != 60:
        raise ValueError("Expected the existing 60-second Phase 3 feature windows.")

    features = pd.read_csv(
        FEATURE_FILE, parse_dates=["window_start", "window_end"]
    )
    if len(features) != 3_362:
        raise ValueError(f"Expected 3,362 feature windows; found {len(features)}.")
    required = {"session_number", "split", "window_start", "window_end", *EXPECTED_FEATURES}
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"ML-ready feature dataset is missing columns: {sorted(missing)}")
    features["window_start"] = pd.to_datetime(
        features["window_start"], utc=True, errors="coerce"
    )
    features["window_end"] = pd.to_datetime(
        features["window_end"], utc=True, errors="coerce"
    )
    if features[["window_start", "window_end"]].isna().any().any():
        raise ValueError("ML-ready feature timestamps contain invalid values.")
    validate_timestamp_range(features["window_start"], "Feature window start")
    validate_timestamp_range(features["window_end"], "Feature window end")
    if not features["window_start"].is_monotonic_increasing:
        raise ValueError("Feature windows are not in chronological order.")
    for feature in EXPECTED_FEATURES:
        values = pd.to_numeric(features[feature], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"Selected feature {feature} contains invalid values.")
        features[feature] = values
    return features


def format_time_axis(axis: plt.Axes, include_date: bool = True) -> None:
    date_format = "%Y-%m-%d\n%H:%M" if include_date else "%H:%M"
    axis.xaxis.set_major_formatter(
        mdates.DateFormatter(date_format, tz=mdates.UTC)
    )
    axis.set_xlabel("Time")


def plot_sensor_series(
    readings: pd.DataFrame,
    filename: str,
    channels: tuple[str, ...],
    ylabel: str,
    title: str,
) -> Path:
    figure, axis = plt.subplots(figsize=(16, 5))
    for channel in channels:
        axis.plot(
            readings["timestamp"],
            readings[channel],
            linewidth=0.65,
            label=channel,
        )
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    format_time_axis(axis)
    axis.set_xlim(readings["timestamp"].min(), readings["timestamp"].max())
    figure.tight_layout()
    return save_figure(figure, filename, readings["timestamp"], channels)


def plot_current_temperature_blocks(readings: pd.DataFrame) -> Path:
    sessions = list(readings.groupby("session_number", sort=True))
    if len(sessions) != 6:
        raise ValueError(f"Expected six actual session blocks, found {len(sessions)}.")

    figure, axes = plt.subplots(
        6, 2, figsize=(17, 18), sharex=False, constrained_layout=True
    )
    for row, (session_number, session) in enumerate(sessions):
        color = SESSION_COLORS[row]
        date = session["timestamp"].min().strftime("%Y-%m-%d")
        current_axis, temperature_axis = axes[row]
        for channel in ("current_l1", "current_l2", "current_l3"):
            current_axis.plot(
                session["timestamp"],
                session[channel],
                linewidth=0.65,
                label=channel,
            )
        current_axis.set_ylabel("Current")
        current_axis.set_title(f"Session {int(session_number)} — {date}", loc="left")
        current_axis.grid(alpha=0.2)
        if row == 0:
            current_axis.legend(loc="upper left", ncol=3, fontsize=8)

        for channel in ("tool_temperature", "ambient_temperature"):
            temperature_axis.plot(
                session["timestamp"],
                session[channel],
                linewidth=0.8,
                label=channel,
            )
        temperature_axis.set_ylabel("Temperature")
        temperature_axis.set_title(f"Session {int(session_number)} — {date}", loc="left")
        temperature_axis.grid(alpha=0.2)
        temperature_axis.set_facecolor((*color, 0.035))
        if row == 0:
            temperature_axis.legend(loc="upper left", ncol=2, fontsize=8)
        current_axis.set_xlim(session["timestamp"].min(), session["timestamp"].max())
        temperature_axis.set_xlim(
            session["timestamp"].min(), session["timestamp"].max()
        )
        format_time_axis(current_axis, include_date=False)
        format_time_axis(temperature_axis, include_date=False)

    figure.suptitle("Current and temperature by persisted recording session", fontsize=15)
    figure.supxlabel("Time within each recorded session")
    return save_figure(
        figure,
        "current_temperature_blocks.png",
        readings["timestamp"],
        (
            "current_l1",
            "current_l2",
            "current_l3",
            "tool_temperature",
            "ambient_temperature",
            "persisted sessions 1-6",
        ),
    )


def plot_derived_features(features: pd.DataFrame) -> Path:
    figure, axes = plt.subplots(3, 3, figsize=(17, 12), sharex=True)
    sessions = list(features.groupby("session_number", sort=True))
    if [int(number) for number, _ in sessions] != [1, 2, 3, 4, 5, 6]:
        raise ValueError("Selected feature rows do not represent sessions 1-6.")

    legend_handles = [
        Patch(color=SESSION_COLORS[index], label=f"Session {int(number)}")
        for index, (number, _) in enumerate(sessions)
    ]
    for axis, feature in zip(axes.flat, EXPECTED_FEATURES):
        for index, (session_number, session) in enumerate(sessions):
            axis.plot(
                session["window_start"],
                session[feature],
                color=SESSION_COLORS[index],
                linewidth=0.75,
                label=f"Session {int(session_number)}",
            )
        axis.set_title(feature)
        axis.set_ylabel(feature)
        axis.grid(alpha=0.2)
    date_axis = axes[-1, 1]
    date_axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=5))
    date_axis.xaxis.set_major_formatter(
        mdates.DateFormatter("%m-%d", tz=mdates.UTC)
    )
    date_axis.set_xlim(
        features["window_start"].min(),
        features["window_start"].max(),
    )
    axes[-1, 0].tick_params(labelbottom=False)
    axes[-1, 2].tick_params(labelbottom=False)
    date_axis.set_xlabel("Time (UTC, November 2026)")
    figure.legend(
        handles=legend_handles,
        loc="upper center",
        ncol=6,
        bbox_to_anchor=(0.5, 0.95),
    )
    figure.suptitle(
        "Selected Phase 3 features over time (independent y-scales)",
        fontsize=15,
        y=0.99,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.91))
    return save_figure(
        figure,
        "derived_features_over_time.png",
        features["window_start"],
        tuple(EXPECTED_FEATURES),
    )


def main() -> None:
    readings = load_sensor_readings()
    features = load_selected_features()
    generated = [
        plot_sensor_series(
            readings,
            "current_vs_time.png",
            ("current_l1", "current_l2", "current_l3"),
            "Current",
            "Three-phase current vs time",
        ),
        plot_sensor_series(
            readings,
            "temperature_vs_time.png",
            ("tool_temperature", "ambient_temperature"),
            "Temperature",
            "Tool and ambient temperature vs time",
        ),
        plot_sensor_series(
            readings,
            "vibration_vs_time.png",
            ("vibration_x", "vibration_y", "vibration_z"),
            "Vibration",
            "Three-axis vibration vs time",
        ),
        plot_sensor_series(
            readings,
            "voltage_vs_time.png",
            ("voltage_l1", "voltage_l2", "voltage_l3"),
            "Voltage",
            "Three-phase voltage vs time",
        ),
        plot_current_temperature_blocks(readings),
        plot_derived_features(features),
    ]
    print(
        json.dumps(
            {
                "figures": [str(path.relative_to(config.ROOT)) for path in generated],
                "figure_count": len(generated),
                "sensor_row_count": len(readings),
                "session_count": readings["session_number"].nunique(),
                "sensor_time_range_utc": [
                    readings["timestamp"].min().isoformat(),
                    readings["timestamp"].max().isoformat(),
                ],
                "feature_window_count": len(features),
                "feature_time_range_utc": [
                    features["window_start"].min().isoformat(),
                    features["window_start"].max().isoformat(),
                ],
                "selected_features": EXPECTED_FEATURES,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
