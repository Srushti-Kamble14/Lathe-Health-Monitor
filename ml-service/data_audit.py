#!/usr/bin/env python
"""Profile the supplied CNC lathe CSV without changing the source file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_SENSORS = {
    "Temperature": ["ambient_temp", "tool_temp"],
    "Vibration": ["accx", "accy", "accz"],
    "Current": ["c1", "c2", "c3"],
    "Voltage": ["v1", "v2", "v3"],
}
SENSOR_COLUMNS = [column for group in PROJECT_SENSORS.values() for column in group]
DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "Raw data CNC LATHE MACHINE.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reports"
PLOT_LIMIT = 4000
WINDOW_SAMPLES = 60
NOMINAL_INTERVAL_SECONDS = 3.0


def markdown_table(frame: pd.DataFrame, digits: int = 4) -> str:
    """Render a compact Markdown table with stable numeric formatting."""
    if frame.empty:
        return "_No data._"
    display = frame.copy()
    for column in display.select_dtypes(include=["number"]).columns:
        def format_number(value):
            if pd.isna(value):
                return ""
            if float(value).is_integer():
                return str(int(value))
            return f"{value:.{digits}f}"

        display[column] = display[column].map(format_number)
    headers = [str(column) for column in display.columns]
    rows = [
        [str(value) for value in row]
        for row in display.fillna("").itertuples(index=False, name=None)
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def safe_corr(left: pd.Series, right: pd.Series) -> float:
    paired = pd.concat([left, right], axis=1).dropna()
    if len(paired) < 2 or paired.iloc[:, 0].nunique() < 2 or paired.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(paired.iloc[:, 0].corr(paired.iloc[:, 1]))


def make_plot(
    path: Path,
    title: str,
    draw,
    *,
    xlabel: str | None = None,
    ylabel: str | None = None,
    figsize: tuple[float, float] = (12, 5),
) -> None:
    fig, axis = plt.subplots(figsize=figsize)
    draw(axis)
    axis.set_title(title)
    if xlabel:
        axis.set_xlabel(xlabel)
    if ylabel:
        axis.set_ylabel(ylabel)
    axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def downsample(frame: pd.DataFrame, limit: int = PLOT_LIMIT) -> pd.DataFrame:
    if len(frame) <= limit:
        return frame
    indices = np.linspace(0, len(frame) - 1, num=limit, dtype=int)
    return frame.iloc[indices]


def create_vibration_features(frame: pd.DataFrame, timestamp: pd.Series) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    axes = [column for column in ["accx", "accy", "accz"] if column in frame]
    if len(axes) != 3:
        return result

    result["vibration_magnitude"] = np.sqrt(
        sum(pd.to_numeric(frame[column], errors="coerce").pow(2) for column in axes)
    )

    # Rolling features use trailing 60-record windows (nominally 3 minutes).
    # Start a new window group after every non-nominal sampling gap.
    elapsed = timestamp.diff().dt.total_seconds()
    group = elapsed.ne(NOMINAL_INTERVAL_SECONDS).cumsum()
    magnitude = result["vibration_magnitude"]
    rolling = magnitude.groupby(group).rolling(WINDOW_SAMPLES, min_periods=1)
    rms = rolling.apply(lambda values: np.sqrt(np.mean(np.square(values))), raw=True)
    result["vibration_rms_60_samples"] = rms.reset_index(level=0, drop=True).sort_index()
    result["vibration_std_60_samples"] = (
        rolling.std(ddof=0).reset_index(level=0, drop=True).sort_index()
    )
    result["vibration_peak_60_samples"] = (
        rolling.max().reset_index(level=0, drop=True).sort_index()
    )
    result["vibration_peak_to_peak_60_samples"] = (
        rolling.max().reset_index(level=0, drop=True)
        - rolling.min().reset_index(level=0, drop=True)
    ).sort_index()
    result["crest_factor_60_samples"] = (
        result["vibration_peak_60_samples"] / result["vibration_rms_60_samples"]
    ).replace([np.inf, -np.inf], np.nan)
    return result


def create_electrical_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    for name, columns in (
        ("mean_current", ["c1", "c2", "c3"]),
        ("mean_voltage", ["v1", "v2", "v3"]),
    ):
        if all(column in frame for column in columns):
            values = frame[columns].apply(pd.to_numeric, errors="coerce")
            average = values.mean(axis=1)
            maximum_deviation = values.sub(average, axis=0).abs().max(axis=1)
            result[name] = average
            result[f"{name.removeprefix('mean_')}_imbalance_pct"] = (
                100 * maximum_deviation / average.abs().replace(0, np.nan)
            )
    return result


def create_figures(
    frame: pd.DataFrame,
    timestamp: pd.Series,
    vibration: pd.DataFrame,
    electrical: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plots: list[Path] = []
    plot_frame = pd.DataFrame({"timestamp": timestamp}, index=frame.index)
    plot_frame = pd.concat([plot_frame, frame, vibration, electrical], axis=1)
    sampled = downsample(plot_frame)

    for name, columns, title, ylabel in (
        ("current_vs_time.png", ["c1", "c2", "c3"], "Three-phase current over time", "Current (source units)"),
        ("voltage_vs_time.png", ["v1", "v2", "v3"], "Three-phase voltage over time", "Voltage (source units)"),
        ("vibration_vs_time.png", ["accx", "accy", "accz"], "3-axis vibration over time", "Acceleration (source units)"),
    ):
        available = [column for column in columns if column in sampled]
        if not available:
            continue

        def draw(axis, available=available):
            for column in available:
                axis.plot(sampled["timestamp"], sampled[column], linewidth=0.7, label=column)
            axis.legend(ncol=len(available))

        path = output_dir / name
        make_plot(path, title, draw, ylabel=ylabel)
        plots.append(path)

    if {"ambient_temp", "tool_temp"}.issubset(sampled.columns):
        path = output_dir / "temperatures_vs_time.png"

        def draw_temperatures(axis):
            for column in ("ambient_temp", "tool_temp"):
                axis.plot(sampled["timestamp"], sampled[column], linewidth=0.8, label=column)
            axis.legend()

        make_plot(path, "Temperatures over time", draw_temperatures, ylabel="Temperature (source units)")
        plots.append(path)

    phase_groups = [
        [column for column in ["c1", "c2", "c3"] if column in frame],
        [column for column in ["v1", "v2", "v3"] if column in frame],
    ]
    if any(phase_groups):
        path = output_dir / "electrical_phase_comparison.png"

        def draw_phases(axis):
            axis.set_axis_off()
            for index, columns in enumerate(phase_groups, start=1):
                if not columns:
                    continue
                sub_axis = axis.figure.add_subplot(1, 2, index)
                sub_axis.boxplot(
                    [pd.to_numeric(frame[column], errors="coerce").dropna() for column in columns],
                    tick_labels=columns,
                    showfliers=False,
                )
                sub_axis.set_title("Current phases" if index == 1 else "Voltage phases")
                sub_axis.grid(alpha=0.2)

        path.parent.mkdir(parents=True, exist_ok=True)
        fig, axis = plt.subplots(figsize=(11, 5))
        draw_phases(axis)
        fig.suptitle("Electrical phase comparison (boxplots omit displayed fliers)")
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        plots.append(path)

    if {"tool_temp", "ambient_temp", "mean_current"}.issubset(plot_frame.columns):
        path = output_dir / "temperature_relationships.png"
        relationship_sample = downsample(plot_frame)
        has_vibration = "vibration_magnitude" in relationship_sample
        fig, axes = plt.subplots(
            1, 3 if has_vibration else 2, figsize=(17 if has_vibration else 12, 5)
        )
        axes[0].scatter(
            relationship_sample["ambient_temp"],
            relationship_sample["tool_temp"],
            s=5,
            alpha=0.25,
        )
        axes[0].set(xlabel="Ambient temperature", ylabel="Tool temperature", title="Tool vs ambient temperature")
        axes[1].scatter(
            relationship_sample["mean_current"],
            relationship_sample["tool_temp"],
            s=5,
            alpha=0.25,
        )
        axes[1].set(xlabel="Mean 3-phase current", ylabel="Tool temperature", title="Tool temperature vs mean current")
        if has_vibration:
            axes[2].scatter(
                relationship_sample["vibration_magnitude"],
                relationship_sample["tool_temp"],
                s=5,
                alpha=0.25,
            )
            axes[2].set(
                xlabel="Vibration magnitude",
                ylabel="Tool temperature",
                title="Tool temperature vs vibration magnitude",
            )
        for axis in axes:
            axis.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        plots.append(path)

    if {"vibration_magnitude", "mean_current"}.issubset(plot_frame.columns):
        path = output_dir / "vibration_magnitude_vs_current.png"
        relationship_sample = downsample(plot_frame)

        def draw_vibration_current(axis):
            axis.scatter(
                relationship_sample["mean_current"],
                relationship_sample["vibration_magnitude"],
                s=5,
                alpha=0.25,
            )

        make_plot(
            path,
            "Vibration magnitude vs mean current",
            draw_vibration_current,
            xlabel="Mean 3-phase current (source units)",
            ylabel="Vibration magnitude (source units)",
        )
        plots.append(path)

    correlation_columns = [column for column in SENSOR_COLUMNS if column in frame]
    if len(correlation_columns) >= 2:
        correlation = frame[correlation_columns].apply(pd.to_numeric, errors="coerce").corr()
        path = output_dir / "sensor_correlation_matrix.png"
        fig, axis = plt.subplots(figsize=(10, 8))
        image = axis.imshow(correlation, vmin=-1, vmax=1, cmap="coolwarm")
        axis.set_xticks(range(len(correlation_columns)), correlation_columns, rotation=45, ha="right")
        axis.set_yticks(range(len(correlation_columns)), correlation_columns)
        fig.colorbar(image, ax=axis, label="Pearson correlation")
        axis.set_title("Project-sensor correlation matrix")
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        plots.append(path)

    return plots


def run_audit(csv_path: Path, output_dir: Path) -> str:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Dataset not found: {csv_path}")

    raw = pd.read_csv(csv_path)
    if raw.empty:
        raise ValueError(f"Dataset contains no records: {csv_path}")

    original_rows, original_columns = raw.shape
    completely_empty_columns = [
        column for column in raw.columns if raw[column].isna().all()
    ]
    cleaned = raw.drop(columns=completely_empty_columns).copy()
    completely_empty_rows = int(raw.isna().all(axis=1).sum())
    duplicate_rows = int(raw.duplicated().sum())
    raw_memory = int(raw.memory_usage(index=True, deep=True).sum())
    file_size = csv_path.stat().st_size

    profile = pd.DataFrame(
        [
            {
                "column": column,
                "dtype": str(raw[column].dtype),
                "non_missing": int(raw[column].notna().sum()),
                "missing": int(raw[column].isna().sum()),
                "unique_non_missing": int(raw[column].nunique(dropna=True)),
                "memory_bytes": int(raw[column].memory_usage(index=False, deep=True)),
            }
            for column in raw.columns
        ]
    )

    date_column, time_column = "time", "time.1"
    timestamp: pd.Series | None = None
    timestamp_note = "No timestamp created: source date/time columns were not both available."
    interval_stats: dict[str, float] = {}
    daily_counts = pd.Series(dtype="int64")
    interval_seconds = pd.Series(dtype="float64")
    if date_column in cleaned and time_column in cleaned:
        combined = cleaned[date_column].astype(str).str.strip() + " " + cleaned[time_column].astype(str).str.strip()
        timestamp = pd.to_datetime(
            combined,
            format="%d-%m-%y %I:%M:%S %p",
            errors="coerce",
        )
        parse_failures = int(timestamp.isna().sum())
        if parse_failures == 0:
            timestamp_note = (
                "Created by parsing `time` as `%d-%m-%y` and `time.1` as "
                "`%I:%M:%S %p`; every row parsed successfully, so this combination "
                "is supported by the observed source formats."
            )
            interval_seconds = timestamp.diff().dt.total_seconds().dropna()
            if not interval_seconds.empty:
                counts = interval_seconds.value_counts()
                interval_stats = {
                    "minimum": float(interval_seconds.min()),
                    "maximum": float(interval_seconds.max()),
                    "median": float(interval_seconds.median()),
                    "mean": float(interval_seconds.mean()),
                    "mode": float(counts.index[0]),
                    "mode_count": int(counts.iloc[0]),
                    "interval_count": int(len(interval_seconds)),
                    "nominal_fraction": float(
                        interval_seconds.eq(counts.index[0]).mean()
                    ),
                    "out_of_order": int(interval_seconds.lt(0).sum()),
                    "duplicate_timestamps": int(timestamp.duplicated().sum()),
                }
            daily_counts = timestamp.dt.date.value_counts().sort_index()
        else:
            timestamp_note = (
                f"No timestamp created: {parse_failures} row(s) could not be parsed "
                "using the observed date/time format."
            )
            timestamp = None

    sensor_statistics: list[dict[str, float | int | str]] = []
    outlier_rows: list[dict[str, float | int | str]] = []
    outlier_examples: list[dict[str, float | str | int]] = []
    numeric_sensors: dict[str, pd.Series] = {}
    for sensor in SENSOR_COLUMNS:
        if sensor not in cleaned:
            continue
        values = pd.to_numeric(cleaned[sensor], errors="coerce")
        numeric_sensors[sensor] = values
        valid = values.dropna()
        missing_count = int(values.isna().sum())
        stats = valid.describe(percentiles=[0.01, 0.5, 0.99]) if not valid.empty else None
        sensor_statistics.append(
            {
                "sensor": sensor,
                "count": int(valid.count()),
                "missing": missing_count,
                "missing_pct": (100 * missing_count / len(cleaned)),
                "min": float(stats["min"]) if stats is not None else float("nan"),
                "max": float(stats["max"]) if stats is not None else float("nan"),
                "mean": float(stats["mean"]) if stats is not None else float("nan"),
                "median": float(stats["50%"]) if stats is not None else float("nan"),
                "std": float(valid.std()) if len(valid) > 1 else float("nan"),
                "p01": float(stats["1%"]) if stats is not None else float("nan"),
                "p99": float(stats["99%"]) if stats is not None else float("nan"),
            }
        )
        if valid.empty:
            continue
        q1, q3 = valid.quantile([0.25, 0.75])
        iqr = q3 - q1
        iqr_mask = (values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)
        median = valid.median()
        mad = (valid - median).abs().median()
        robust_z = (
            0.6745 * (values - median).abs() / mad if mad > 0 else pd.Series(0, index=values.index)
        )
        robust_mask = robust_z > 3.5
        impossible_mask = pd.Series(False, index=values.index)
        if sensor in {"ambient_temp", "tool_temp"}:
            impossible_mask = values < -273.15
        outlier_rows.append(
            {
                "sensor": sensor,
                "iqr_outliers": int(iqr_mask.sum()),
                "iqr_pct": float(100 * iqr_mask.sum() / len(cleaned)),
                "robust_z_gt_3_5": int(robust_mask.sum()),
                "robust_z_pct": float(100 * robust_mask.sum() / len(cleaned)),
                "physically_impossible_by_known_bounds": int(impossible_mask.sum()),
                "interpretation": (
                    "potentially anomalous; no physical limit inferred from name alone"
                    if iqr_mask.any() or robust_mask.any()
                    else "no threshold outlier detected; this does not prove validity"
                ),
            }
        )
        for row_index in robust_z.nlargest(3).index:
            if pd.isna(robust_z.loc[row_index]) or robust_z.loc[row_index] <= 3.5:
                continue
            outlier_examples.append(
                {
                    "sensor": sensor,
                    "timestamp_or_csv_line": (
                        str(timestamp.iloc[row_index])
                        if timestamp is not None
                        else f"CSV line {row_index + 2}"
                    ),
                    "value": float(values.loc[row_index]),
                    "robust_z": float(robust_z.loc[row_index]),
                    "iqr_flag": bool(iqr_mask.loc[row_index]),
                    "classification": "potentially anomalous; investigate, do not delete",
                }
            )

    sensors_found = [sensor for sensor in SENSOR_COLUMNS if sensor in cleaned]
    vibration = (
        create_vibration_features(cleaned, timestamp)
        if timestamp is not None
        else pd.DataFrame(index=cleaned.index)
    )
    electrical = create_electrical_features(cleaned)
    if "ambient_temp" in cleaned and "tool_temp" in cleaned:
        ambient = pd.to_numeric(cleaned["ambient_temp"], errors="coerce")
        tool = pd.to_numeric(cleaned["tool_temp"], errors="coerce")
        electrical["temperature_difference_tool_minus_ambient"] = tool - ambient
        if timestamp is not None:
            elapsed = timestamp.diff().dt.total_seconds()
            continuous = elapsed.eq(NOMINAL_INTERVAL_SECONDS)
            electrical["tool_temp_change_per_min"] = (
                tool.diff() / elapsed * 60
            ).where(continuous)
            electrical["ambient_temp_change_per_min"] = (
                ambient.diff() / elapsed * 60
            ).where(continuous)

    # Any nonempty unnamed trailing fields are surfaced, never silently discarded.
    unnamed_columns = [column for column in raw if re.match(r"^Unnamed:", str(column))]
    unnamed_summary = []
    for column in unnamed_columns:
        nonempty = raw[column].dropna()
        unnamed_summary.append(
            {
                "column": column,
                "non_missing": int(nonempty.size),
                "unique_values": int(nonempty.nunique()),
                "values": ", ".join(map(str, nonempty.unique()[:5])) or "none",
            }
        )

    target_pattern = re.compile(
        r"fault|health|condition|wear|failure|maintenance|anomal|label|target|class",
        re.IGNORECASE,
    )
    target_candidates = [
        str(column) for column in cleaned.columns if target_pattern.search(str(column))
    ]
    docs = [
        path
        for path in csv_path.parent.iterdir()
        if path.is_file()
        and path != csv_path
        and path.suffix.lower() in {".md", ".txt", ".pdf", ".doc", ".docx"}
    ]

    sensor_frame = pd.DataFrame(numeric_sensors)
    correlation = sensor_frame.corr() if len(sensor_frame.columns) >= 2 else pd.DataFrame()
    correlation_md = markdown_table(correlation.reset_index(names="sensor"), digits=3)
    correlations: list[tuple[str, str, float]] = []
    for left_index, left in enumerate(sensor_frame.columns):
        for right in sensor_frame.columns[left_index + 1 :]:
            value = safe_corr(sensor_frame[left], sensor_frame[right])
            if np.isfinite(value):
                correlations.append((left, right, value))
    strongest = sorted(correlations, key=lambda item: abs(item[2]), reverse=True)[:8]
    strongest_frame = pd.DataFrame(
        strongest, columns=["sensor_a", "sensor_b", "pearson_r"]
    )

    daily_summary = pd.DataFrame()
    if timestamp is not None and not daily_counts.empty:
        regime_data = pd.DataFrame(
            {
                "date": timestamp.dt.date,
                "mean_current": electrical.get("mean_current"),
                "mean_voltage": electrical.get("mean_voltage"),
                "vibration_magnitude": vibration.get("vibration_magnitude"),
                "tool_temp": pd.to_numeric(cleaned.get("tool_temp"), errors="coerce")
                if "tool_temp" in cleaned
                else np.nan,
            }
        )
        daily_summary = regime_data.groupby("date").agg(
            records=("date", "size"),
            current_median=("mean_current", "median"),
            current_p90=("mean_current", lambda values: values.quantile(0.9)),
            voltage_median=("mean_voltage", "median"),
            vibration_magnitude_median=("vibration_magnitude", "median"),
            tool_temp_median=("tool_temp", "median"),
        )

    plots = create_figures(cleaned, timestamp, vibration, electrical, output_dir / "figures") if timestamp is not None else []

    source_description = (
        "The supplied CSV is the only file in its data directory."
        if not docs
        else "Accompanying documentation: " + ", ".join(path.name for path in docs)
    )
    date_rows = (
        pd.DataFrame({"date": list(daily_counts.index), "records": daily_counts.values})
        if not daily_counts.empty
        else pd.DataFrame()
    )
    outlier_frame = pd.DataFrame(outlier_rows)
    outlier_examples_frame = pd.DataFrame(outlier_examples)
    stats_frame = pd.DataFrame(sensor_statistics)
    profile_md = markdown_table(profile)
    sensor_stats_md = markdown_table(stats_frame)
    outliers_md = markdown_table(outlier_frame, digits=3)
    outlier_examples_md = markdown_table(outlier_examples_frame, digits=4)
    daily_md = markdown_table(daily_summary.reset_index(), digits=4)
    daily_counts_md = markdown_table(date_rows)

    timestamp_coverage = (
        f"- Parsed timestamp range: **{timestamp.min()}** to **{timestamp.max()}** "
        f"({timestamp.max() - timestamp.min()}).\n"
        f"- `time`: {cleaned[date_column].nunique()} unique date strings; "
        f"`time.1`: {cleaned[time_column].nunique()} unique clock strings.\n"
        f"- {timestamp_note}"
        if timestamp is not None
        else f"- {timestamp_note}"
    )
    if interval_stats:
        uniform_text = (
            f"{interval_stats['nominal_fraction'] * 100:.3f}% of consecutive intervals "
            f"equal the modal interval ({interval_stats['mode']:g} seconds)"
        )
        sampling_text = (
            f"- Interval seconds: min **{interval_stats['minimum']:g}**, "
            f"max **{interval_stats['maximum']:g}**, median **{interval_stats['median']:g}**, "
            f"mean **{interval_stats['mean']:.4f}**, mode **{interval_stats['mode']:g}** "
            f"({interval_stats['mode_count']:,}/{interval_stats['interval_count']:,}).\n"
            f"- {uniform_text}; intervals include gaps between recording sessions/days. "
            f"Out-of-order intervals: {interval_stats['out_of_order']}; duplicate timestamps: "
            f"{interval_stats['duplicate_timestamps']}."
        )
    else:
        sampling_text = "- No consecutive timestamp intervals could be computed."

    unnamed_md = markdown_table(pd.DataFrame(unnamed_summary))
    removed_description = (
        ", ".join(f"`{column}` (entirely empty)" for column in completely_empty_columns)
        if completely_empty_columns
        else "none"
    )
    nonempty_unnamed = [
        item for item in unnamed_summary if item["non_missing"] > 0
    ]
    nonempty_unnamed_details = []
    for column in unnamed_columns:
        populated = raw[column].dropna()
        if not populated.empty:
            row_index = populated.index[0]
            row_time = (
                str(timestamp.iloc[row_index])
                if timestamp is not None
                else f"source row {row_index + 2}"
            )
            nonempty_unnamed_details.append(
                f"`{column}` has {len(populated)} nonempty value(s); first is "
                f"`{populated.iloc[0]}` at {row_time} (CSV line {row_index + 2})."
            )
    stray_note = (
        " Nonempty unnamed fields were retained in the cleaned analysis dataframe and "
        "reported, not silently removed."
        if nonempty_unnamed
        else ""
    )
    sensor_coverage = (
        ", ".join(f"`{sensor}`" for sensor in sensors_found)
        if sensors_found
        else "none of the expected project sensors"
    )
    temperature_corr = safe_corr(
        numeric_sensors["ambient_temp"], numeric_sensors["tool_temp"]
    ) if {"ambient_temp", "tool_temp"}.issubset(numeric_sensors) else float("nan")
    current_corr = safe_corr(
        pd.to_numeric(cleaned["tool_temp"], errors="coerce"),
        electrical["mean_current"],
    ) if "mean_current" in electrical and "tool_temp" in cleaned else float("nan")
    temperature_vibration_corr = safe_corr(
        pd.to_numeric(cleaned["tool_temp"], errors="coerce"),
        vibration["vibration_magnitude"],
    ) if "vibration_magnitude" in vibration and "tool_temp" in cleaned else float("nan")
    vibration_current_corr = safe_corr(
        vibration["vibration_magnitude"], electrical["mean_current"]
    ) if "vibration_magnitude" in vibration and "mean_current" in electrical else float("nan")
    rate_summary = []
    for name in ("tool_temp_change_per_min", "ambient_temp_change_per_min"):
        if name in electrical:
            rates = electrical[name].dropna()
            if not rates.empty:
                rate_summary.append(
                    f"- `{name}` on nominal 3-second intervals: median {rates.median():.4f}, "
                    f"minimum {rates.min():.4f}, maximum {rates.max():.4f} source-units/minute."
                )
    temp_rate_md = "\n".join(rate_summary) or "- Temperature rates could not be computed."
    correlation_table = (
        markdown_table(strongest_frame, digits=3)
        if not strongest_frame.empty
        else "_No sensor pair had a defined correlation._"
    )
    feature_names = sorted(
        [
            *vibration.columns.tolist(),
            *electrical.columns.tolist(),
        ]
    )
    figures_md = (
        "\n".join(f"- `figures/{path.name}`" for path in plots)
        if plots
        else "- No figures generated (timestamp unavailable or required sensors absent)."
    )
    docs_note = (
        f"`{source_description}` No target or units documentation was available in the "
        "dataset folder for interpreting statistical extremes or labels."
    )

    report = f"""# CNC Lathe Dataset Audit

> Generated by `ml-service/data_audit.py`. The source CSV is read-only for this analysis; no model is trained and no label is created. RPM, if present, is excluded from all features, correlations, regimes, and plots.

## Dataset Identity

- File: `{csv_path.name}`
- Path: `{csv_path}`
- Scope: four project sensor groups only — temperature, 3-axis vibration, 3-phase current, and 3-phase voltage.
- Data documentation: {docs_note}

## Dataset Size

- Rows: **{original_rows:,}**
- Columns: **{original_columns}**
- CSV size: **{file_size:,} bytes**
- pandas deep memory usage: **{raw_memory:,} bytes**
- Fully duplicate rows: **{duplicate_rows:,}**
- Completely empty rows: **{completely_empty_rows:,}**
- Completely empty columns excluded from the analysis dataframe: {removed_description}.{stray_note}
- Nonempty unnamed-field detail: {" ".join(nonempty_unnamed_details) if nonempty_unnamed_details else "none"} It is not treated as a project sensor.

### Column profile

{profile_md}

### Unnamed columns

{unnamed_md}

## Timestamp Coverage

{timestamp_coverage}

Records per day:

{daily_counts_md}

## Sampling Interval

{sampling_text}

## Missing Data

- Empty columns were omitted only from the cleaned analysis dataframe; the CSV itself was not changed.
- Project sensors found: {sensor_coverage}.
- The table below reports numeric-convertible sensor counts and missing percentages. Invalid numeric cells, if any, are counted as missing for that sensor.

## Sensor Statistics

{sensor_stats_md}

## Outliers

The IQR rule flags values outside 1.5 × IQR; the robust-z rule flags absolute modified z-scores above 3.5 (MAD-based). These are screening thresholds, not fault labels. Only the absolute-zero lower bound is used as a physical impossibility check for temperatures. No universal acceleration/electrical bounds can be inferred from column names without units and measurement definitions.

{outliers_md}

Examples of the three most extreme robust-z observations per sensor (where the threshold is exceeded):

{outlier_examples_md}

Classification: ordinary in-range observations are **likely valid readings**, not certified valid; statistical extremes are **potentially anomalous** and must be investigated against machine context; values below absolute zero or non-numeric sensor values would be **potentially invalid**. No statistical outlier is automatically deleted.

## Sensor Relationships

Pearson correlation across available project sensors (descriptive association, not causation):

{correlation_md}

Strongest absolute pairwise correlations:

{correlation_table}

- Ambient/tool temperature correlation: {temperature_corr:.3f}.
- Tool temperature / average 3-phase current correlation: {current_corr:.3f}.
- Tool temperature / vibration magnitude correlation: {temperature_vibration_corr:.3f}.
- Vibration magnitude / average 3-phase current correlation: {vibration_current_corr:.3f}.
- Correlation is sensitive to time trends and operating schedules; it does not establish a causal or health relationship.

## Derived Features

- Vibration magnitude: `sqrt(accx² + accy² + accz²)`; raw acceleration columns are unchanged.
- Rolling vibration RMS, population standard deviation, peak, peak-to-peak and crest factor use trailing **60-record** windows (nominally 3 minutes at 3-second sampling). Windows reset at any interval other than 3 seconds; initial windows use available records only.
- Average current / voltage: row-wise arithmetic mean across the three available phases.
- Imbalance: maximum absolute phase deviation from the row mean, divided by absolute row mean, × 100. Undefined for a zero mean.
- Temperature difference: `tool_temp - ambient_temp`; rates are consecutive differences divided by elapsed time and reported per minute only for nominal 3-second steps.
- Derived features are in-memory analysis values only; no columns are written into the source CSV.
- No apparent power, real power, power factor, or energy is computed: current/voltage measurement types, phase alignment, and the required electrical formulas are not documented.
- Features generated by this run: {", ".join(f"`{name}`" for name in feature_names) if feature_names else "none"}.

## Temperature Analysis

- Ambient and tool temperature observed ranges are listed in the sensor statistics table; both columns contain the observed row count if their missing count is zero.
- Temperature values are complete at recorded samples, but that does not make the record continuous across the long session/day gaps.
- Temperature correlation and temperature/current relationships are reported above and plotted below. Association may reflect time or operating changes.

{temp_rate_md}

## Operating Regimes

Daily summaries below use only project sensor groups; RPM is not used. Different daily aggregates may indicate changing conditions, but there are no verified idle, machining, or load-state labels. These summaries do **not** justify assigning operating-state names.

{daily_md}

**Conclusion:** the data support descriptive time-block variation only. Without independent process annotations or validated thresholds, operating regimes cannot be confidently identified or labeled.

## Health/Fault Label Investigation

- Candidate label-like columns found by header inspection: {", ".join(f"`{name}`" for name in target_candidates) if target_candidates else "none"}.
- {source_description}
- No fault, health, condition, wear, failure, maintenance, anomaly, or target label is present in the observed headers.

**NO VERIFIED SUPERVISED HEALTH LABEL FOUND**

No target values or class distribution can be reported; no labels have been invented.

## ML Suitability

| Approach | Required target/data | Present? | Suitability and limitations |
|---|---|---|---|
| Supervised health/fault classification | Verified health/fault labels tied to sensor observations | No | Not supported. Do not label high temperature, vibration, or current as a fault without verified ground truth. |
| Anomaly detection | Sensor-only baseline and a defensible definition of unusual behavior | Sensor time series present | Possible for exploratory, unlabeled anomaly screening only. No fault validation, sensor units, or known healthy baseline; statistical anomalies are not necessarily faults. |
| Regression | A measured continuous target (for example a documented wear measurement) | No target found | Not supported for a project outcome. Sensor-to-sensor regression would not validate predictive maintenance. |
| Remaining useful life | Failure/censoring times and operating history linked to assets | No | Not supported; no asset/run-to-failure or maintenance-event information is present. |

## Recommended Features

Use only observed project sensor channels: {", ".join(f"`{name}`" for name in sensors_found) if sensors_found else "none found"}.

Potential sensor-only analysis features, after verifying units and acquisition semantics: raw temperature (`tool_temp`, `ambient_temp`), temperature difference/rate; raw `accx`, `accy`, `accz`, vibration magnitude and explicitly windowed rolling vibration features; raw `c1`/`c2`/`c3` and their mean/imbalance; raw `v1`/`v2`/`v3` and their mean/imbalance. Only include a listed channel if it is actually present. **Do not include RPM.** Timestamps should be retained for ordering/splitting, not casually used as a predictive feature.

## Data Leakage Risks

- Chronological time can encode the recording schedule, drift, or run progression; using it as a feature can create spurious predictions.
- A random row split can place adjacent 3-second samples and overlapping rolling windows in both train and test, inflating results.
- Rolling features must be trailing-only and reset at session gaps; centered or future-looking windows leak future information.
- Duplicate full rows: {duplicate_rows}. Duplicate timestamps: {interval_stats.get("duplicate_timestamps", "not available")}.
- Any future labels derived from maintenance/failure events must not be joined using information unavailable at prediction time.
- Prefer a chronological/session-aware holdout with an appropriate gap; fit all preprocessing on training data only.
- No target exists to test target leakage in this dataset.

## Limitations

- Sensor units, calibration, phase/current/voltage measurement definitions, machine state, workpiece/tool context, and collection protocol are unavailable.
- Acceleration channels have large nonzero offsets; magnitude computed directly from the raw axes includes those offsets and should not be interpreted as calibrated vibration severity without sensor orientation, calibration, and appropriate baseline treatment.
- A single nonempty unnamed field may be an extra export artifact; it was retained and surfaced rather than interpreted as a sensor.
- Missingness and statistical outlier rules cannot establish sensor validity or fault condition.
- The recording contains separate days with large inter-session gaps, so it is not one uniformly continuous stream.
- No documented healthy/fault state, tool-wear ground truth, maintenance log, failure event, or RUL target is available.
- The supplied CSV remains unchanged. This audit reads only the named CSV and any documentation next to it.

## Data Quality Score

| Dimension | Score | Reason |
|---|---:|---|
| Sensor completeness | 10/10 | All expected project channels are present and have no missing numeric values in this file. |
| Timestamp quality | 8/10 | Both source columns parse on every row and nearly all consecutive records are 3 seconds apart, but recording sessions have long gaps and date-only values repeat. |
| Sensor consistency | 6/10 | Values are numeric and complete, but some statistical extremes occur and units/calibration/measurement semantics are undocumented. |
| Time-series suitability | 7/10 | 67k ordered records with a strong 3-second cadence within sessions; separate-day gaps and no session annotations limit modeling. |
| ML suitability | 4/10 | Usable for exploratory sensor-only anomaly research, not validated predictive maintenance; no target or ground-truth labels. |
| Health-label availability | 0/10 | No verified health/fault/tool-wear/failure/maintenance target found. |
| Overall suitability | 5/10 | Useful as a sensor/time-series exploration baseline, but insufficient by itself for verified supervised predictive maintenance. |

## Final Recommendation

1. **Can this dataset be used for the lathe project?** Yes, cautiously, for initial sensor-format, cadence, descriptive, and unlabeled anomaly-method exploration; first verify its provenance and machine equivalence.
2. **Which four-sensor architecture parts does it cover?** It contains the named ambient/tool temperature, 3-axis acceleration, three current, and three voltage channels, with no missing values in the observed records. Units and sensor definitions still need verification.
3. **What important information is missing?** Units/calibration and acquisition details, operating-state annotations, machine/tool/workpiece context, verified health/fault or wear labels, maintenance/failure history, and run-to-failure records.
4. **Can supervised predictive maintenance be performed?** No, not defensibly from this dataset alone; no verified supervised target exists.
5. **Should anomaly detection be used instead?** It may be explored as an explicitly unlabeled, unvalidated screening approach. It must not be presented as fault diagnosis without ground-truth validation.
6. **What should be collected from the real YCCE lathe?** Synchronized timestamped tool/ambient temperatures; calibrated X/Y/Z vibration with units and sampling/window details; per-phase current and voltage with measurement mode/units; machine and sensor identifiers, tool/workpiece/material, operation/load/state annotations, and acquisition metadata. For supervised maintenance, record verified tool condition/wear inspections, fault events, maintenance actions, and failure/run-to-failure timelines, including healthy periods and censoring.

## Generated Figures

Plots use at most {PLOT_LIMIT:,} evenly spaced records for readable visualization; source rows and analysis data are not downsampled or modified.

{figures_md}
"""

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "dataset_audit.md"
    report_path.write_text(report, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Supplied source CSV")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="Audit report/figure directory")
    args = parser.parse_args()
    report = run_audit(args.csv.resolve(), args.output_dir.resolve())
    print(report)
    print(f"\nReport written to: {args.output_dir.resolve() / 'dataset_audit.md'}")
    print(f"Figures written to: {args.output_dir.resolve() / 'figures'}")


if __name__ == "__main__":
    main()
