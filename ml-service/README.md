# ML service

The Python/FastAPI ML service will be implemented separately in a later phase. No service code or model is included here.

## Dataset audit

`data_audit.py` profiles the supplied `data/Raw data CNC LATHE MACHINE.csv` without modifying it or using RPM as an analysis feature. It writes `reports/dataset_audit.md` and plots to `reports/figures/`.

Install the analysis dependencies and run from this directory:

```powershell
python -m pip install -r requirements.txt
python data_audit.py
```

The original CSV is excluded from Git. The audit must be run where that supplied file is available. It does not create labels, train a model, or implement an API/database schema.
