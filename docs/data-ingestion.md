# Dataset ingestion

The Python loader imports only the supplied local college lathe CSV:

```text
ml-service/data/Raw data CNC LATHE MACHINE.csv
```

It does not modify or copy the source. The raw CSV is Git-ignored. Phase 0.1/0.2 analysis found 67,258 rows, six recording sessions, complete approved sensor fields, and no duplicate timestamps; the loader revalidates these facts on every run.

## Explicit mapping

| Source CSV fields | Database columns |
| --- | --- |
| `time` + `time.1` | `timestamp` |
| `c1`, `c2`, `c3` | `current_l1`, `current_l2`, `current_l3` |
| `v1`, `v2`, `v3` | `voltage_l1`, `voltage_l2`, `voltage_l3` |
| `accx`, `accy`, `accz` | `vibration_x`, `vibration_y`, `vibration_z` |
| `ambient_temp` | `ambient_temperature` |
| `tool_temp` | `tool_temperature` |

`time` parses as `%d-%m-%y`; `time.1` parses as `%I:%M:%S %p`. The resulting timezone-naive timestamps are consistently interpreted as UTC when inserted into `TIMESTAMPTZ`. This is a storage convention; the source has no timezone metadata. Rows are sorted chronologically.

No other source columns are selected. RPM, unnamed export columns, and all unapproved fields are excluded.

## Duplicate and missing-value handling

The loader rejects the full ingestion before connecting if approved sensor values are missing/non-numeric, timestamps cannot be parsed, or duplicate timestamps are found. It reports duplicate timestamp examples rather than silently dropping data. The verified source has unique timestamps, so the database enforces `(machine_id, timestamp)` uniqueness.

Bulk inserts use `psycopg2.extras.execute_values` in 2,000-row batches. Session and sensor rows are upserted, so a rerun updates rows for an existing timestamp rather than creating duplicate readings. All data changes and database validation run in one transaction; failed validation rolls back.

## Run and validate

1. Configure `DATABASE_URL` in `backend/.env` or the process environment.
2. Apply migrations:

   ```powershell
   cd backend
   npm run migrate
   ```

3. Install analysis/ingestion dependencies and run the loader:

   ```powershell
   cd ..\ml-service
   python -m pip install -r requirements.txt
   python ingest_dataset.py
   ```

4. Inspect `ml-service/reports/ingestion_validation.json`. It includes source/database row counts, earliest/latest timestamps, session counts and boundaries, per-sensor missing counts, duplicate timestamp count, and min/max/mean values for each approved sensor.

The script fails unless database and CSV row counts match, all required database sensor fields are populated, there are no duplicate timestamps, and the expected session count matches. Run it a second time to verify idempotence; the row count should remain 67,258.

Before/after manual ingestion, the source SHA-256 can be checked with:

```powershell
Get-FileHash ".\data\Raw data CNC LATHE MACHINE.csv" -Algorithm SHA256
```

Do not commit the CSV, connection string, or `.env`.
