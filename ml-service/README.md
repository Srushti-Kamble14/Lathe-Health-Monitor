# ML service

The offline analysis scripts and Phase 3/Phase 4 artifacts are accompanied by a Python/FastAPI inference service. The service loads the Phase 4 Isolation Forest once during startup and scores requests without retraining. The dataset has no verified health/fault labels, so the output is exploratory anomaly detection and is not a confirmed fault diagnosis.

## Offline anomaly inference

Phase 4's persisted scores/metadata did not include a serialized estimator. To generate the serving artifact using the same fixed IsolationForest configuration and TRAIN data, run once from this directory:

```powershell
python -m pip install -r requirements.txt
python export_inference_model.py
```

The exporter verifies exact score parity with the existing Phase 4 IsolationForest scores before writing `artifacts/anomaly_detection/isolation_forest.joblib`. It does not alter the Phase 3 feature dataset or other Phase 4 artifacts. Runtime inference fails startup if the model, metadata, thresholds, or feature order are invalid; there is no fallback training.

Start the API from the repository root:

```powershell
python -m uvicorn service.main:app --app-dir ml-service --host 127.0.0.1 --port 8000
```

Endpoints:

- `GET /health` — process liveness.
- `GET /ready` — model/artifact readiness.
- `POST /api/v1/anomaly/score` — score exactly the nine Phase 3 features.

The backend reaches the ML API using `ML_SERVICE_URL` and `ML_SERVICE_TIMEOUT_MS` from `backend/.env`. The backend performs machine/session validation and writes scores to the existing `anomaly_results` table. See [docs/anomaly-inference.md](../docs/anomaly-inference.md) for the request/response contract and the end-to-end smoke test.

## Dataset audit

`data_audit.py` profiles the supplied `data/Raw data CNC LATHE MACHINE.csv` without modifying it or using RPM as an analysis feature. It writes `reports/dataset_audit.md` and plots to `reports/figures/`.

Install the analysis dependencies and run from this directory:

```powershell
python -m pip install -r requirements.txt
python data_audit.py
```

The original CSV is excluded from Git. The audit must be run where that supplied file is available. It does not create labels, train a model, or implement an API/database schema.

## ML target strategy

`ml_target_analysis.py` performs session-aware descriptive regime analysis, feature derivation, a prior-window robust-z screen, and a preliminary Isolation Forest fit on earlier sessions with later sessions held out. It writes `reports/ml_target_strategy.md` and plots to `reports/figures/target_analysis/`.

```powershell
python ml_target_analysis.py
```

Scores are unlabeled candidate anomalies, not fault predictions; no production threshold or health label is selected.

## Phase 3 feature preparation

`feature_engineering.py` reads approved sensor columns from PostgreSQL, joins each reading to its persisted recording session, validates timestamps and sensor values, compares time-window candidates, engineers statistical features, and writes a session-isolated chronological train/validation/test dataset. It does not read or modify the source CSV and does not train a model.

Configure `DATABASE_URL` in the process environment or `backend/.env`, then run:

```powershell
python feature_engineering.py
```

Generated ML data and diagnostics are written to `artifacts/features/`; the report is `reports/feature_engineering_report.md`, and figures are in `reports/figures/feature_analysis/`. The report records current database counts and session boundaries, window selection evidence, feature quality/correlation, selected inputs, split assignments, and validation results. Re-running overwrites these generated outputs deterministically.

After the one-time November 2026 working-timestamp translation, verify the unchanged raw data, sensor/feature values, and temporal structure with:

```powershell
python validate_timestamp_shift.py --validate
```

The timestamp translation itself is a separate, one-time operation (`python validate_timestamp_shift.py --apply`) and must not be rerun after completion.

Generate the additional sensor-specific November 2026 time-series figures without rerunning feature selection or changing the ML-ready dataset:

```powershell
python generate_sensor_visualizations.py
```

The script reads raw sensor measurements from PostgreSQL and the selected feature values from the existing ML-ready feature artifact. It validates the shifted timestamp range and persisted session boundaries before saving plots.

## Dataset ingestion

After applying the backend migrations, install the Python requirements and run:

```powershell
python -m pip install -r requirements.txt
python ingest_dataset.py
```

The script reads only approved source columns, validates timestamps/sensor completeness/uniqueness, upserts in batches, and writes a database validation summary to `reports/ingestion_validation.json`. It reads `DATABASE_URL` from the process environment or `backend/.env`. The original CSV remains local and Git-ignored.
