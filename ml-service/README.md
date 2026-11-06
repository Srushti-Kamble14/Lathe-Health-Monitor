# ML service

The Python/FastAPI ML service will be implemented separately in a later phase. No API service or production model is included here.

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

## Dataset ingestion

After applying the backend migrations, install the Python requirements and run:

```powershell
python -m pip install -r requirements.txt
python ingest_dataset.py
```

The script reads only approved source columns, validates timestamps/sensor completeness/uniqueness, upserts in batches, and writes a database validation summary to `reports/ingestion_validation.json`. It reads `DATABASE_URL` from the process environment or `backend/.env`. The original CSV remains local and Git-ignored.
