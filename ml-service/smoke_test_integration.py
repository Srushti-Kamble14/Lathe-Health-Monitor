#!/usr/bin/env python
"""Exercise Node -> FastAPI -> PostgreSQL with a real Phase 3 feature row."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import psycopg2
from dotenv import load_dotenv

import anomaly_config


ROOT = Path(__file__).resolve().parent
BACKEND_ENV = ROOT.parent / "backend" / ".env"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend-url",
        default=os.getenv("BACKEND_API_URL", "http://localhost:3000"),
        help="Node backend base URL (or set BACKEND_API_URL).",
    )
    args = parser.parse_args()

    load_dotenv(BACKEND_ENV)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    features_frame = pd.read_csv(anomaly_config.FEATURE_PATH)
    sample = features_frame.iloc[0]
    feature_values = {
        name: float(sample[name]) for name in anomaly_config.FEATURE_NAMES
    }
    request_body = {
        "machine_id": str(sample["machine_id"]),
        "session_id": str(sample["session_id"]),
        "timestamp": pd.to_datetime(sample["window_start"], utc=True).isoformat(),
        "features": feature_values,
    }

    inserted_id: str | None = None
    try:
        with psycopg2.connect(database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM anomaly_results
                    WHERE machine_id = %s AND timestamp = %s::timestamptz
                    """,
                    (request_body["machine_id"], request_body["timestamp"]),
                )
                if cursor.fetchone() is not None:
                    raise RuntimeError(
                        "The selected smoke-test timestamp already has a result; "
                        "refusing to overwrite it."
                    )
        request = Request(
            f"{args.backend_url.rstrip('/')}/api/v1/anomalies/score",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(
                f"Backend smoke request failed with HTTP {error.code}."
            ) from None
        except URLError:
            raise RuntimeError("Backend smoke request could not connect.") from None

        data = body.get("data", {})
        inserted_id = data.get("id")
        if (
            body.get("success") is not True
            or not inserted_id
            or data.get("model_name") != "IsolationForest"
            or data.get("anomaly_status") not in {"NORMAL", "WARNING", "ANOMALOUS"}
        ):
            raise RuntimeError("Backend smoke response did not match the inference contract.")

        with psycopg2.connect(database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id::text, anomaly_score, anomaly_status, model_name, model_version
                    FROM anomaly_results
                    WHERE id = %s
                    """,
                    (inserted_id,),
                )
                stored = cursor.fetchone()
                if stored is None or stored[2] != data["anomaly_status"]:
                    raise RuntimeError("The smoke-test anomaly result was not persisted.")
        print(
            json.dumps(
                {
                    "success": True,
                    "model_name": data["model_name"],
                    "model_version": data["model_version"],
                    "anomaly_status": data["anomaly_status"],
                    "database_persisted": True,
                    "smoke_record_id": inserted_id,
                },
                indent=2,
            )
        )
    finally:
        if inserted_id:
            with psycopg2.connect(database_url, connect_timeout=10) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM anomaly_results WHERE id = %s",
                        (inserted_id,),
                    )


if __name__ == "__main__":
    main()
