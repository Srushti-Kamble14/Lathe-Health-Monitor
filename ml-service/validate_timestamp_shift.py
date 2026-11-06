#!/usr/bin/env python
"""Translate dataset timestamps once, or verify a completed November 2026 shift."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import psycopg2

import feature_config as config
from ingest_dataset import DEFAULT_CSV, MACHINE_CODE, get_connection_url


ROOT = Path(__file__).resolve().parents[1]
FEATURE_FILE = config.FEATURE_OUTPUT_DIR / "ml_ready_features.csv"
SESSION_SPLITS_FILE = config.FEATURE_OUTPUT_DIR / "session_splits.csv"
RUN_SUMMARY_FILE = config.FEATURE_OUTPUT_DIR / "run_summary.json"
FEATURE_REPORT_FILE = config.REPORT_DIR / "feature_engineering_report.md"
SHIFT_REPORT_FILE = ROOT / "docs" / "timestamp_shift.md"
BASELINE_FILE = config.FEATURE_OUTPUT_DIR / "timestamp_shift_baseline.json"

SENSOR_COLUMNS = config.SENSOR_COLUMNS
TIMESTAMP_COLUMNS = {
    FEATURE_FILE: ("window_start", "window_end"),
    SESSION_SPLITS_FILE: ("start", "end"),
}
ISO_TIMESTAMP_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)\b"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_csv_columns(
    path: Path, excluded: set[str] | frozenset[str] = frozenset()
) -> str:
    digest = hashlib.sha256()
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise RuntimeError(f"CSV has no header: {path}")
        columns = [column for column in reader.fieldnames if column not in excluded]
        digest.update(json.dumps(columns, separators=(",", ":")).encode())
        for row in reader:
            digest.update(b"\n")
            digest.update(
                json.dumps(
                    [row[column] for column in columns],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
    return digest.hexdigest()


def hash_session_splits(path: Path) -> str:
    return hash_csv_columns(path, {"start", "end"})


def hash_shifted_timestamps(path: Path, columns: tuple[str, ...], offset: timedelta) -> str:
    digest = hashlib.sha256()
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None or any(column not in reader.fieldnames for column in columns):
            raise RuntimeError(f"Expected timestamp columns {columns} are missing from {path}.")
        for row in reader:
            timestamps = [
                (parse_timestamp(row[column]) - offset).isoformat()
                for column in columns
            ]
            digest.update(json.dumps(timestamps, separators=(",", ":")).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def load_baseline() -> dict[str, Any]:
    if not BASELINE_FILE.is_file():
        raise RuntimeError(
            f"Timestamp shift baseline is missing: {BASELINE_FILE}. "
            "Run this script with --apply before validation."
        )
    return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))


def database_snapshot(
    connection: psycopg2.extensions.connection,
    normalize_timestamps_by: timedelta = timedelta(0),
) -> dict[str, Any]:
    sensors_sql = ", ".join(f"sr.{column}::text" for column in SENSOR_COLUMNS)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT m.id::text, COUNT(sr.id)::bigint, MIN(sr.timestamp), MAX(sr.timestamp)
            FROM machines AS m
            LEFT JOIN sensor_readings AS sr ON sr.machine_id = m.id
            WHERE m.machine_code = %s
            GROUP BY m.id
            """,
            (MACHINE_CODE,),
        )
        machine = cursor.fetchone()
        if machine is None:
            raise RuntimeError(f"Machine {MACHINE_CODE} was not found in PostgreSQL.")
        machine_id, row_count, minimum, maximum = machine
        if minimum is None or maximum is None:
            raise RuntimeError("The machine has no measurement timestamps.")

        cursor.execute(
            """
            SELECT ms.id::text,
                   ms.session_number,
                   ms.start_time,
                   ms.end_time,
                   ms.sample_count,
                   lag(ms.end_time) OVER (ORDER BY ms.start_time, ms.session_number)
            FROM machine_sessions AS ms
            WHERE ms.machine_id = %s
            ORDER BY ms.start_time, ms.session_number
            """,
            (machine_id,),
        )
        session_rows = cursor.fetchall()
        sessions = [
            {
                "session_id": row[0],
                "session_number": int(row[1]),
                "start": row[2].isoformat(),
                "end": row[3].isoformat(),
                "sample_count": int(row[4]),
                "duration_seconds": (row[3] - row[2]).total_seconds(),
                "preceding_gap_seconds": (
                    (row[2] - row[5]).total_seconds() if row[5] is not None else None
                ),
            }
            for row in session_rows
        ]

        cursor.execute(
            """
            WITH reading_intervals AS (
              SELECT EXTRACT(EPOCH FROM (
                       sr.timestamp - lag(sr.timestamp) OVER (
                         PARTITION BY ms.id ORDER BY sr.timestamp
                       )
                     ))::double precision AS seconds
              FROM sensor_readings AS sr
              JOIN machine_sessions AS ms
                ON ms.machine_id = sr.machine_id
               AND sr.timestamp BETWEEN ms.start_time AND ms.end_time
              WHERE sr.machine_id = %s
            )
            SELECT seconds, COUNT(*)::bigint
            FROM reading_intervals
            WHERE seconds IS NOT NULL
            GROUP BY seconds
            ORDER BY seconds
            """,
            (machine_id,),
        )
        interval_distribution = {
            format(float(seconds), ".15g"): int(count)
            for seconds, count in cursor.fetchall()
        }

        cursor.execute(
            f"""
            SELECT COUNT(*)::bigint,
                   md5(COALESCE(string_agg(
                     md5(concat_ws('|', {sensors_sql})), ''
                     ORDER BY sr.timestamp
                   ), ''))
            FROM sensor_readings AS sr
            WHERE sr.machine_id = %s
            """,
            (machine_id,),
        )
        sensor_count, sensor_digest = cursor.fetchone()

        cursor.execute(
            """
            SELECT md5(COALESCE(string_agg(
                     to_char(
                       sr.timestamp - %s,
                       'YYYY-MM-DD"T"HH24:MI:SS.US'
                     ),
                     '' ORDER BY sr.timestamp
                   ), ''))
            FROM sensor_readings AS sr
            WHERE sr.machine_id = %s
            """,
            (normalize_timestamps_by, machine_id),
        )
        timestamp_digest = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*)::bigint FROM anomaly_results WHERE machine_id = %s",
            (machine_id,),
        )
        anomaly_count = int(cursor.fetchone()[0])

    return {
        "machine_id": machine_id,
        "row_count": int(row_count),
        "session_count": len(sessions),
        "minimum_timestamp": minimum.isoformat(),
        "maximum_timestamp": maximum.isoformat(),
        "sessions": sessions,
        "sampling_interval_distribution_seconds": interval_distribution,
        "sensor_row_count": int(sensor_count),
        "sensor_values_sha256": sensor_digest,
        "timestamp_sequence_md5": timestamp_digest,
        "anomaly_result_count": anomaly_count,
    }


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime, original: str) -> str:
    separator = " " if " " in original and "T" not in original else "T"
    return value.astimezone(timezone.utc).isoformat(sep=separator)


def prepare_shifted_csv(path: Path, columns: tuple[str, ...], offset: timedelta) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None or any(column not in reader.fieldnames for column in columns):
            raise RuntimeError(f"Expected timestamp columns {columns} are missing from {path}.")
        rows = list(reader)
        fieldnames = reader.fieldnames
    for row in rows:
        for column in columns:
            old_value = row[column]
            row[column] = format_timestamp(parse_timestamp(old_value) + offset, old_value)
    output = tempfile.SpooledTemporaryFile(mode="w+", encoding="utf-8", newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    result = output.read()
    output.close()
    return result


def prepare_shifted_run_summary(offset: timedelta) -> str:
    summary = json.loads(RUN_SUMMARY_FILE.read_text(encoding="utf-8"))

    def translate(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {name: translate(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [translate(item, key) for item in value]
        if isinstance(value, str) and key in {"first_window", "last_window"}:
            return (parse_timestamp(value) + offset).isoformat()
        return value

    return json.dumps(translate(summary), indent=2, sort_keys=True) + "\n"


def prepare_shifted_feature_report(offset: timedelta) -> str:
    source = FEATURE_REPORT_FILE.read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        original = match.group(0)
        return (parse_timestamp(original) + offset).isoformat()

    return ISO_TIMESTAMP_PATTERN.sub(replace, source)


def write_staged_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
        file.write(content)
    return temporary_path


def replace_staged_files(staged: dict[Path, Path]) -> None:
    replaced: list[Path] = []
    try:
        for destination, temporary in staged.items():
            temporary.replace(destination)
            replaced.append(destination)
    except OSError:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        raise


def build_temporal_figures() -> None:
    features = pd.read_csv(FEATURE_FILE, parse_dates=["window_start", "window_end"])
    features["window_start"] = pd.to_datetime(features["window_start"], utc=True)
    figure_dir = config.FIGURE_DIR

    figure, axes = plt.subplots(4, 1, figsize=(16, 13), sharex=True)
    groups = [
        ("Current", ["current_mean", "current_std", "current_imbalance"]),
        ("Voltage", ["voltage_mean", "voltage_imbalance"]),
        ("Vibration", ["vibration_rms", "vibration_magnitude_std"]),
        ("Temperature", ["temperature_delta", "temperature_rate"]),
    ]
    for axis, (title, names) in zip(axes, groups):
        for feature in names:
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
        axis.legend(loc="upper left", ncol=min(3, len(names)), fontsize=8)
    axes[-1].xaxis.set_major_formatter(
        mdates.DateFormatter("%Y-%m-%d\n%H:%M", tz=mdates.UTC)
    )
    figure.tight_layout()
    figure.savefig(
        figure_dir / "sensor_features_over_time.png", dpi=150, bbox_inches="tight"
    )
    plt.close(figure)

    splits = features[["window_start", "session_number", "split"]].drop_duplicates()
    figure, axis = plt.subplots(figsize=(12, 4))
    colors = {"train": "#3572A5", "validation": "#D28B36", "test": "#9B4F7C"}
    for split, group in splits.groupby("split", sort=False):
        axis.scatter(
            group["window_start"],
            group["session_number"],
            s=8,
            alpha=0.65,
            label=split,
            color=colors[split],
        )
    axis.set_yticks(sorted(splits["session_number"].unique()))
    axis.set_ylabel("Persisted session number")
    axis.set_title("Chronological session-level train / validation / test split")
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d", tz=mdates.UTC))
    axis.legend()
    axis.grid(alpha=0.2)
    figure.tight_layout()
    figure.savefig(
        figure_dir / "chronological_split.png", dpi=150, bbox_inches="tight"
    )
    plt.close(figure)


def ensure_no_non_timestamp_artifact_changes(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    if before["row_count"] != after["row_count"]:
        raise RuntimeError("Database row count changed during timestamp translation.")
    if before["session_count"] != after["session_count"]:
        raise RuntimeError("Database session count changed during timestamp translation.")
    if before["sensor_values_sha256"] != after["sensor_values_sha256"]:
        raise RuntimeError("Database sensor values changed during timestamp translation.")
    if before["sampling_interval_distribution_seconds"] != after["sampling_interval_distribution_seconds"]:
        raise RuntimeError("Database sampling intervals changed during timestamp translation.")
    if before["anomaly_result_count"] != after["anomaly_result_count"]:
        raise RuntimeError("Anomaly-result row count changed during timestamp translation.")


def validate_shift() -> dict[str, Any]:
    baseline = load_baseline()
    offset = timedelta(seconds=int(baseline["offset_seconds"]))
    connection = psycopg2.connect(
        get_connection_url(),
        connect_timeout=10,
        application_name="lathe-health-monitor-timestamp-validation",
    )
    try:
        current = database_snapshot(connection, normalize_timestamps_by=offset)
    finally:
        connection.close()

    expected_database = baseline["database_before"]
    expected_minimum = parse_timestamp(expected_database["minimum_timestamp"]) + offset
    expected_maximum = parse_timestamp(expected_database["maximum_timestamp"]) + offset
    if parse_timestamp(current["minimum_timestamp"]) != expected_minimum:
        raise RuntimeError("Database minimum timestamp does not match the recorded offset.")
    if parse_timestamp(current["maximum_timestamp"]) != expected_maximum:
        raise RuntimeError("Database maximum timestamp does not match the recorded offset.")
    ensure_no_non_timestamp_artifact_changes(expected_database, current)
    if current["timestamp_sequence_md5"] != expected_database["timestamp_sequence_md5"]:
        raise RuntimeError("Database measurement timestamps were not translated uniformly.")

    for before_session, after_session in zip(
        expected_database["sessions"], current["sessions"], strict=True
    ):
        for key in ("session_id", "session_number", "sample_count", "duration_seconds", "preceding_gap_seconds"):
            if before_session[key] != after_session[key]:
                raise RuntimeError(
                    f"Session {before_session['session_number']} changed {key}."
                )
        if parse_timestamp(after_session["start"]) != parse_timestamp(before_session["start"]) + offset:
            raise RuntimeError(f"Session {before_session['session_number']} start is not shifted correctly.")
        if parse_timestamp(after_session["end"]) != parse_timestamp(before_session["end"]) + offset:
            raise RuntimeError(f"Session {before_session['session_number']} end is not shifted correctly.")
    if len(current["sessions"]) != len(expected_database["sessions"]):
        raise RuntimeError("The session count changed during timestamp translation.")

    if sha256_file(DEFAULT_CSV) != baseline["raw_csv_sha256"]:
        raise RuntimeError("The original raw CSV checksum changed.")
    if hash_csv_columns(FEATURE_FILE, {"window_start", "window_end"}) != baseline["feature_values_sha256"]:
        raise RuntimeError("Feature values, identifiers, or splits changed in the ML-ready dataset.")
    if hash_session_splits(SESSION_SPLITS_FILE) != baseline["session_assignment_sha256"]:
        raise RuntimeError("Session split assignments or identifiers changed.")
    if hash_shifted_timestamps(FEATURE_FILE, ("window_start", "window_end"), offset) != baseline["feature_timestamps_sha256"]:
        raise RuntimeError("ML-ready window timestamps did not all receive the same offset.")
    if hash_shifted_timestamps(SESSION_SPLITS_FILE, ("start", "end"), offset) != baseline["split_timestamps_sha256"]:
        raise RuntimeError("Session split boundary timestamps did not all receive the same offset.")

    summary = json.loads(RUN_SUMMARY_FILE.read_text(encoding="utf-8"))
    for split, bounds in baseline["feature_split_bounds"].items():
        actual = summary["validation"]["split_bounds"][split]
        for key in ("first_window", "last_window"):
            if parse_timestamp(actual[key]) != parse_timestamp(bounds[key]) + offset:
                raise RuntimeError(f"Run summary {split} {key} timestamp was not translated.")

    current_report_timestamps = ISO_TIMESTAMP_PATTERN.findall(
        FEATURE_REPORT_FILE.read_text(encoding="utf-8")
    )
    expected_report_timestamps = [
        (parse_timestamp(value) + offset).isoformat()
        for value in baseline["feature_report_timestamps"]
    ]
    if current_report_timestamps != expected_report_timestamps:
        raise RuntimeError("Feature engineering report timestamps were not uniformly translated.")

    feature_rows = pd.read_csv(FEATURE_FILE, parse_dates=["window_start", "window_end"])
    feature_rows["window_start"] = pd.to_datetime(feature_rows["window_start"], utc=True)
    feature_rows["window_end"] = pd.to_datetime(feature_rows["window_end"], utc=True)
    if len(feature_rows) != baseline["feature_row_count"]:
        raise RuntimeError("The ML-ready feature row count changed.")
    if not feature_rows["window_start"].is_monotonic_increasing:
        raise RuntimeError("ML-ready window timestamps are not chronological.")
    if not (
        feature_rows["window_start"].min() >= datetime(2026, 11, 1, tzinfo=timezone.utc)
        and feature_rows["window_end"].max() < datetime(2026, 12, 1, tzinfo=timezone.utc)
    ):
        raise RuntimeError("ML-ready feature timestamps are outside November 2026.")
    if not (
        expected_minimum >= datetime(2026, 11, 1, tzinfo=timezone.utc)
        and expected_maximum < datetime(2026, 12, 1, tzinfo=timezone.utc)
    ):
        raise RuntimeError("Database measurement timestamps are outside November 2026.")

    expected_split_map = {
        int(session["session_number"]): session["split"]
        for session in baseline["session_splits"]
    }
    actual_splits = (
        feature_rows.groupby("session_number")["split"].agg(lambda values: set(values))
    )
    if any(actual_splits[number] != {split} for number, split in expected_split_map.items()):
        raise RuntimeError("Train/validation/test assignment changed.")

    return {
        "database": current,
        "new_minimum_timestamp": current["minimum_timestamp"],
        "new_maximum_timestamp": current["maximum_timestamp"],
        "offset_seconds": int(baseline["offset_seconds"]),
        "feature_row_count": int(len(feature_rows)),
        "feature_values_unchanged": True,
        "session_assignments_unchanged": True,
        "raw_csv_unchanged": True,
        "november_2026": True,
    }


def apply_shift() -> dict[str, Any]:
    if BASELINE_FILE.exists():
        raise RuntimeError(
            f"Timestamp shift baseline already exists at {BASELINE_FILE}; "
            "refusing to apply a second offset."
        )
    required_files = [
        DEFAULT_CSV,
        FEATURE_FILE,
        SESSION_SPLITS_FILE,
        RUN_SUMMARY_FILE,
        FEATURE_REPORT_FILE,
    ]
    missing = [str(path) for path in required_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Required timestamp-shift files are missing: {missing}")

    connection = psycopg2.connect(
        get_connection_url(),
        connect_timeout=10,
        application_name="lathe-health-monitor-timestamp-shift",
    )
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "LOCK TABLE sensor_readings, machine_sessions, anomaly_results IN SHARE ROW EXCLUSIVE MODE"
                )
            before = database_snapshot(connection)
            original_minimum = parse_timestamp(before["minimum_timestamp"])
            original_maximum = parse_timestamp(before["maximum_timestamp"])
            if original_minimum.year == 2026 and original_minimum.month == 11:
                raise RuntimeError("Database already starts in November 2026; no shift was applied.")
            if original_maximum - original_minimum > timedelta(days=30):
                raise RuntimeError(
                    "Dataset span exceeds 30 days; it cannot safely fit in November 2026."
                )
            target_minimum = original_minimum.replace(
                year=2026, month=11, day=1
            )
            offset = target_minimum - original_minimum
            target_maximum = original_maximum + offset
            if target_maximum >= datetime(2026, 12, 1, tzinfo=timezone.utc):
                raise RuntimeError(
                    "A November 1 anchor would place the dataset beyond November 2026."
                )

            old_session_splits = list(
                csv.DictReader(SESSION_SPLITS_FILE.open(encoding="utf-8", newline=""))
            )
            before_manifest = {
                "database_before": before,
                "offset_seconds": int(offset.total_seconds()),
                "offset_string": str(offset),
                "raw_csv_sha256": sha256_file(DEFAULT_CSV),
                "feature_values_sha256": hash_csv_columns(
                    FEATURE_FILE, {"window_start", "window_end"}
                ),
                "feature_timestamps_sha256": hash_shifted_timestamps(
                    FEATURE_FILE, ("window_start", "window_end"), timedelta(0)
                ),
                "feature_row_count": sum(1 for _ in FEATURE_FILE.open(encoding="utf-8")) - 1,
                "session_assignment_sha256": hash_session_splits(SESSION_SPLITS_FILE),
                "split_timestamps_sha256": hash_shifted_timestamps(
                    SESSION_SPLITS_FILE, ("start", "end"), timedelta(0)
                ),
                "feature_report_timestamps": ISO_TIMESTAMP_PATTERN.findall(
                    FEATURE_REPORT_FILE.read_text(encoding="utf-8")
                ),
                "feature_split_bounds": {
                    split: {
                        "first_window": group["window_start"].min().isoformat(),
                        "last_window": group["window_end"].max().isoformat(),
                    }
                    for split, group in pd.read_csv(
                        FEATURE_FILE,
                        parse_dates=["window_start", "window_end"],
                    ).groupby("split", sort=False)
                },
                "session_splits": [
                    {
                        "session_number": int(row["session_number"]),
                        "session_id": row["session_id"],
                        "split": row["split"],
                    }
                    for row in old_session_splits
                ],
            }

            staged: dict[Path, Path] = {}
            for path, columns in TIMESTAMP_COLUMNS.items():
                staged[path] = write_staged_text(
                    path, prepare_shifted_csv(path, columns, offset)
                )
            staged[RUN_SUMMARY_FILE] = write_staged_text(
                RUN_SUMMARY_FILE, prepare_shifted_run_summary(offset)
            )
            staged[FEATURE_REPORT_FILE] = write_staged_text(
                FEATURE_REPORT_FILE, prepare_shifted_feature_report(offset)
            )

            interval = timedelta(seconds=int(offset.total_seconds()))
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE sensor_readings AS sr
                    SET timestamp = sr.timestamp + %s
                    FROM machines AS m
                    WHERE sr.machine_id = m.id AND m.machine_code = %s
                    """,
                    (interval, MACHINE_CODE),
                )
                if cursor.rowcount != before["row_count"]:
                    raise RuntimeError(
                        f"Expected to shift {before['row_count']} readings, "
                        f"shifted {cursor.rowcount}."
                    )
                cursor.execute(
                    """
                    UPDATE machine_sessions AS ms
                    SET start_time = ms.start_time + %s,
                        end_time = ms.end_time + %s
                    FROM machines AS m
                    WHERE ms.machine_id = m.id AND m.machine_code = %s
                    """,
                    (interval, interval, MACHINE_CODE),
                )
                if cursor.rowcount != before["session_count"]:
                    raise RuntimeError(
                        f"Expected to shift {before['session_count']} sessions, "
                        f"shifted {cursor.rowcount}."
                    )
                cursor.execute(
                    """
                    UPDATE anomaly_results AS ar
                    SET timestamp = ar.timestamp + %s
                    FROM machines AS m
                    WHERE ar.machine_id = m.id
                      AND ar.reading_id IS NOT NULL
                      AND m.machine_code = %s
                    """,
                    (interval, MACHINE_CODE),
                )
            after = database_snapshot(connection, normalize_timestamps_by=interval)
            ensure_no_non_timestamp_artifact_changes(before, after)
            before_manifest["database_after"] = after
            before_manifest["new_minimum_timestamp"] = after["minimum_timestamp"]
            before_manifest["new_maximum_timestamp"] = after["maximum_timestamp"]
            for old_session, new_session in zip(
                before["sessions"], after["sessions"], strict=True
            ):
                if (
                    parse_timestamp(new_session["start"])
                    != parse_timestamp(old_session["start"]) + offset
                    or parse_timestamp(new_session["end"])
                    != parse_timestamp(old_session["end"]) + offset
                    or new_session["duration_seconds"] != old_session["duration_seconds"]
                    or new_session["preceding_gap_seconds"]
                    != old_session["preceding_gap_seconds"]
                ):
                    raise RuntimeError(
                        f"Session {old_session['session_number']} temporal structure changed."
                    )
            if after["sampling_interval_distribution_seconds"] != before["sampling_interval_distribution_seconds"]:
                raise RuntimeError("Sampling interval distribution changed.")

        replace_staged_files(staged)
    finally:
        connection.close()

    manifest_path = write_staged_text(
        BASELINE_FILE, json.dumps(before_manifest, indent=2, sort_keys=True) + "\n"
    )
    manifest_path.replace(BASELINE_FILE)
    build_temporal_figures()

    result = validate_shift()
    result["original_minimum_timestamp"] = before["minimum_timestamp"]
    result["original_maximum_timestamp"] = before["maximum_timestamp"]
    result["rows_affected"] = before["row_count"]
    result["sessions_affected"] = before["session_count"]
    result["session_duration_and_gap_checks"] = True
    result["sampling_intervals_preserved"] = True
    create_shift_report(before_manifest, result)
    return result


def create_shift_report(manifest: dict[str, Any], result: dict[str, Any]) -> None:
    before = manifest["database_before"]
    after = result["database"]
    duration_rows = [
        {
            "session": session["session_number"],
            "original_duration_seconds": session["duration_seconds"],
            "new_duration_seconds": after["sessions"][index]["duration_seconds"],
            "original_inter_session_gap_seconds": session["preceding_gap_seconds"],
            "new_inter_session_gap_seconds": after["sessions"][index]["preceding_gap_seconds"],
        }
        for index, session in enumerate(before["sessions"])
    ]
    original_intervals = before["sampling_interval_distribution_seconds"]
    new_intervals = after["sampling_interval_distribution_seconds"]
    report = f"""# Dataset Timestamp Translation Report

This operation was a deterministic constant timestamp translation. Every affected measurement/session timestamp received the same offset; no readings were synthesized, dropped, reordered, or independently retimed. Sensor and feature calculations were not rerun.

Original minimum timestamp: `{before['minimum_timestamp']}`

Original maximum timestamp: `{before['maximum_timestamp']}`

New minimum timestamp: `{after['minimum_timestamp']}`

New maximum timestamp: `{after['maximum_timestamp']}`

Timestamp offset applied: `{manifest['offset_string']}` (`{manifest['offset_seconds']}` seconds)

Rows affected: `{before['row_count']}`

Sessions affected: `{before['session_count']}`

Original sampling interval distribution (seconds: count): `{json.dumps(original_intervals, sort_keys=True)}`

New sampling interval distribution (seconds: count): `{json.dumps(new_intervals, sort_keys=True)}`

Original and new session durations / inter-session gaps (seconds):

| Session | Original duration | New duration | Original preceding gap | New preceding gap |
|---:|---:|---:|---:|---:|
{chr(10).join(f"| {row['session']} | {row['original_duration_seconds']} | {row['new_duration_seconds']} | {row['original_inter_session_gap_seconds']} | {row['new_inter_session_gap_seconds']} |" for row in duration_rows)}

Sensor values changed: `No` (database sensor-value digest unchanged)

Feature values changed: `No` (all non-time ML-ready artifact columns unchanged)

Split assignments changed: `No` (session split digest unchanged; sessions 1–3 TRAIN, 4 VALIDATION, 5–6 TEST)

Raw CSV checksum before: `{manifest['raw_csv_sha256']}`

Raw CSV checksum after: `{sha256_file(DEFAULT_CSV)}`

Validation result: `PASS` — database rows and sessions, temporal interval distribution, session durations and gaps, feature values, split assignments, timestamp range, and raw CSV checksum all verified.

The database update was transactional and affected only `sensor_readings.timestamp`, `machine_sessions.start_time/end_time`, and any anomaly-result timestamp linked to one of this machine's readings. Creation/update metadata and schema were not changed. Phase 3 temporal plots were redrawn from the existing feature rows solely to display their translated timestamps.
"""
    SHIFT_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SHIFT_REPORT_FILE.write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply the one-time November 2026 timestamp translation.",
    )
    mode.add_argument(
        "--validate",
        action="store_true",
        help="Validate a previously applied translation (the default).",
    )
    args = parser.parse_args()
    result = apply_shift() if args.apply else validate_shift()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
