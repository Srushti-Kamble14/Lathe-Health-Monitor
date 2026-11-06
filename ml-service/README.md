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

## Dataset ingestion

After applying the backend migrations, install the Python requirements and run:

```powershell
python -m pip install -r requirements.txt
python ingest_dataset.py
```

The script reads only approved source columns, validates timestamps/sensor completeness/uniqueness, upserts in batches, and writes a database validation summary to `reports/ingestion_validation.json`. It reads `DATABASE_URL` from the process environment or `backend/.env`. The original CSV remains local and Git-ignored.
