#!/usr/bin/env python
"""Idempotently ingest the approved sensor fields from the supplied lathe CSV."""

from __future__ import annotations

import argparse
import json
import os
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "Raw data CNC LATHE MACHINE.csv"
DEFAULT_SUMMARY = Path(__file__).resolve().parent / "reports" / "ingestion_validation.json"
BACKEND_ENV = ROOT / "backend" / ".env"
MACHINE_CODE = "LATHE-001"
SESSION_GAP_SECONDS = 30
BATCH_SIZE = 2000

SOURCE_TO_DATABASE = {
    "c1": "current_l1",
    "c2": "current_l2",
    "c3": "current_l3",
    "v1": "voltage_l1",
    "v2": "voltage_l2",
    "v3": "voltage_l3",
    "accx": "vibration_x",
    "accy": "vibration_y",
    "accz": "vibration_z",
    "ambient_temp": "ambient_temperature",
    "tool_temp": "tool_temperature",
}
SENSOR_COLUMNS = list(SOURCE_TO_DATABASE.values())
INSERT_COLUMNS = ["machine_id", "timestamp", *SENSOR_COLUMNS]


def load_source(csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Supplied dataset not found: {csv_path}")

    required = ["time", "time.1", *SOURCE_TO_DATABASE]
    source = pd.read_csv(csv_path, usecols=required)
    combined_time = (
        source["time"].astype(str).str.strip()
        + " "
        + source["time.1"].astype(str).str.strip()
    )
    timestamp = pd.to_datetime(
        combined_time,
        format="%d-%m-%y %I:%M:%S %p",
        errors="coerce",
    )
    if timestamp.isna().any():
        raise ValueError(f"Timestamp parse failed for {int(timestamp.isna().sum())} CSV row(s).")

    readings = pd.DataFrame(
        {
            "timestamp": timestamp,
            **{
                database_column: pd.to_numeric(source[source_column], errors="coerce")
                for source_column, database_column in SOURCE_TO_DATABASE.items()
            },
        }
    ).sort_values("timestamp", kind="stable").reset_index(drop=True)

    missing = readings[SENSOR_COLUMNS].isna().sum()
    missing = missing[missing.gt(0)]
    if not missing.empty:
        detail = ", ".join(f"{name}={count}" for name, count in missing.items())
        raise ValueError(f"Missing/non-numeric values in required sensor fields: {detail}")

    duplicate_timestamps = int(readings["timestamp"].duplicated(keep=False).sum())
    if duplicate_timestamps:
        examples = (
            readings.loc[readings["timestamp"].duplicated(keep=False), "timestamp"]
            .drop_duplicates()
            .head(5)
            .astype(str)
            .tolist()
        )
        raise ValueError(
            f"Found {duplicate_timestamps} source rows with duplicate timestamps; "
            f"no rows were ingested. Examples: {examples}"
        )

    readings["session_number"] = (
        readings["timestamp"].diff().dt.total_seconds().gt(SESSION_GAP_SECONDS).cumsum() + 1
    )
    sessions = (
        readings.groupby("session_number", sort=True)
        .agg(
            start_time=("timestamp", "min"),
            end_time=("timestamp", "max"),
            sample_count=("timestamp", "size"),
            median_interval_seconds=("timestamp", lambda values: values.diff().dt.total_seconds().median()),
        )
        .reset_index()
    )
    if sessions["session_number"].iloc[0] != 1:
        raise RuntimeError("The first dataset recording session number is not 1.")
    return readings, sessions


def get_connection_url() -> str:
    load_dotenv(BACKEND_ENV, override=False)
    connection_url = os.environ.get("DATABASE_URL", "").strip()
    if not connection_url:
        raise RuntimeError(
            "DATABASE_URL is required. Set it in backend/.env or the process environment."
        )
    parsed = urlparse(connection_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URL.")
    return connection_url


def make_summary(
    cursor: Any,
    machine_id: str,
    readings: pd.DataFrame,
    sessions: pd.DataFrame,
) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT COUNT(*)::bigint AS row_count,
               MIN(timestamp) AS earliest_timestamp,
               MAX(timestamp) AS latest_timestamp,
               COUNT(*)::bigint - COUNT(DISTINCT timestamp)::bigint AS duplicate_timestamp_count
        FROM sensor_readings
        WHERE machine_id = %s
        """,
        (machine_id,),
    )
    (
        database_count,
        earliest_timestamp,
        latest_timestamp,
        database_duplicate_count,
    ) = cursor.fetchone()
    cursor.execute(
        "SELECT COUNT(*)::bigint FROM machine_sessions WHERE machine_id = %s",
        (machine_id,),
    )
    database_session_count = int(cursor.fetchone()[0])

    cursor.execute(
        """
        SELECT
          COUNT(*) - COUNT(current_l1) AS current_l1,
          COUNT(*) - COUNT(current_l2) AS current_l2,
          COUNT(*) - COUNT(current_l3) AS current_l3,
          COUNT(*) - COUNT(voltage_l1) AS voltage_l1,
          COUNT(*) - COUNT(voltage_l2) AS voltage_l2,
          COUNT(*) - COUNT(voltage_l3) AS voltage_l3,
          COUNT(*) - COUNT(vibration_x) AS vibration_x,
          COUNT(*) - COUNT(vibration_y) AS vibration_y,
          COUNT(*) - COUNT(vibration_z) AS vibration_z,
          COUNT(*) - COUNT(ambient_temperature) AS ambient_temperature,
          COUNT(*) - COUNT(tool_temperature) AS tool_temperature
        FROM sensor_readings
        WHERE machine_id = %s
        """,
        (machine_id,),
    )
    missing_values = {
        column: int(count)
        for column, count in zip(SENSOR_COLUMNS, cursor.fetchone())
    }

    sensor_statistics: dict[str, dict[str, float | None]] = {}
    for column in SENSOR_COLUMNS:
        cursor.execute(
            f"""
            SELECT MIN({column}), MAX({column}), AVG({column})
            FROM sensor_readings
            WHERE machine_id = %s
            """,
            (machine_id,),
        )
        minimum, maximum, average = cursor.fetchone()
        sensor_statistics[column] = {
            "minimum": float(minimum) if minimum is not None else None,
            "maximum": float(maximum) if maximum is not None else None,
            "mean": float(average) if average is not None else None,
        }

    source_count = len(readings)
    database_count = int(database_count)
    database_session_count = int(database_session_count)
    if database_count != source_count:
        raise RuntimeError(
            f"Database row count {database_count} does not match CSV row count {source_count}."
        )
    if database_session_count != len(sessions):
        raise RuntimeError(
            f"Database session count {database_session_count} does not match "
            f"CSV-derived session count {len(sessions)}."
        )
    if any(missing_values.values()):
        raise RuntimeError(f"Database contains missing sensor values: {missing_values}")
    if int(database_duplicate_count):
        raise RuntimeError("Database contains duplicate timestamps for this machine.")

    return {
        "machine_code": MACHINE_CODE,
        "timestamp_convention": (
            "Source date/time has no timezone. Parsed wall-clock values are interpreted "
            "as UTC when inserted into TIMESTAMPTZ; this is a consistent storage "
            "convention, not a claim about the source's actual timezone."
        ),
        "csv_row_count": source_count,
        "database_row_count": database_count,
        "earliest_timestamp": earliest_timestamp.isoformat(),
        "latest_timestamp": latest_timestamp.isoformat(),
        "source_session_count": int(len(sessions)),
        "database_session_count": database_session_count,
        "source_duplicate_timestamp_rows": int(readings["timestamp"].duplicated().sum()),
        "database_duplicate_timestamp_count": int(
            database_duplicate_count
        ),
        "missing_values_per_sensor": missing_values,
        "sensor_statistics": sensor_statistics,
        "sessions": [
            {
                "session_number": int(row.session_number),
                "start_time": row.start_time.isoformat(),
                "end_time": row.end_time.isoformat(),
                "sample_count": int(row.sample_count),
                "median_interval_seconds": (
                    float(row.median_interval_seconds)
                    if pd.notna(row.median_interval_seconds)
                    else None
                ),
            }
            for row in sessions.itertuples(index=False)
        ],
        "row_count_matches": database_count == source_count,
    }


def ingest(csv_path: Path, summary_path: Path) -> dict[str, Any]:
    readings, sessions = load_source(csv_path)
    connection_url = get_connection_url()
    connection = psycopg2.connect(connection_url, connect_timeout=10, application_name="lathe-health-monitor-ingest")

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM machines WHERE machine_code = %s",
                    (MACHINE_CODE,),
                )
                machine = cursor.fetchone()
                if machine is None:
                    raise RuntimeError(
                        f"Machine {MACHINE_CODE} is missing; run backend migrations first."
                    )
                machine_id = str(machine[0])

                session_rows = [
                    (
                        machine_id,
                        int(row.session_number),
                        row.start_time.to_pydatetime().replace(tzinfo=timezone.utc),
                        row.end_time.to_pydatetime().replace(tzinfo=timezone.utc),
                        int(row.sample_count),
                    )
                    for row in sessions.itertuples(index=False)
                ]
                execute_values(
                    cursor,
                    """
                    INSERT INTO machine_sessions
                      (machine_id, session_number, start_time, end_time, sample_count)
                    VALUES %s
                    ON CONFLICT (machine_id, session_number) DO UPDATE SET
                      start_time = EXCLUDED.start_time,
                      end_time = EXCLUDED.end_time,
                      sample_count = EXCLUDED.sample_count
                    """,
                    session_rows,
                    page_size=BATCH_SIZE,
                )

                reading_rows = []
                for row in readings.itertuples(index=False):
                    timestamp = row.timestamp.to_pydatetime().replace(tzinfo=timezone.utc)
                    sensor_values = tuple(
                        float(getattr(row, column)) for column in SENSOR_COLUMNS
                    )
                    reading_rows.append((machine_id, timestamp, *sensor_values))

                insert_columns = ", ".join(INSERT_COLUMNS)
                update_columns = ", ".join(
                    f"{column} = EXCLUDED.{column}" for column in SENSOR_COLUMNS
                )
                execute_values(
                    cursor,
                    f"""
                    INSERT INTO sensor_readings ({insert_columns})
                    VALUES %s
                    ON CONFLICT (machine_id, timestamp) DO UPDATE SET
                      {update_columns}
                    """,
                    reading_rows,
                    page_size=BATCH_SIZE,
                )

                summary = make_summary(cursor, machine_id, readings, sessions)
    finally:
        connection.close()

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()
    summary = ingest(args.csv.resolve(), args.summary.resolve())
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Validation summary written to: {args.summary.resolve()}")


if __name__ == "__main__":
    main()
