# Offline anomaly inference integration

Phase 5 connects the existing offline Phase 4 Isolation Forest to the Express API. The model was trained offline on the Phase 3 TRAIN split. FastAPI loads the exported estimator, metadata, and the original Phase 4 threshold configuration once during startup. Inference does not train or update the estimator.

The feature contract is exactly:

`current_mean`, `current_std`, `current_imbalance`, `voltage_mean`, `voltage_imbalance`, `vibration_rms`, `vibration_magnitude_std`, `temperature_delta`, and `temperature_rate`.

No additional fields are accepted as model inputs. There are no verified fault labels; scores and statuses identify unusual operating behavior, not confirmed machine faults.

## Export the serving artifact

The Phase 4 pipeline persisted model scores, metadata, and thresholds, but did not serialize its fitted estimator. Export the same estimator using the Phase 4 TRAIN rows and settings from `ml-service/`:

```powershell
python -m pip install -r requirements.txt
python export_inference_model.py
```

The exporter writes only `artifacts/anomaly_detection/isolation_forest.joblib`. Before writing it, it verifies that the estimator reproduces all persisted Phase 4 IsolationForest scores. It does not modify the Phase 3 data or the Phase 4 score, evaluation, threshold, or metadata files. The FastAPI application does not fit a fallback model and fails startup when a required artifact is missing or incompatible.

## Environment and startup

Set these values in `backend/.env` (do not commit that file):

```dotenv
ML_SERVICE_URL=http://localhost:8000
ML_SERVICE_TIMEOUT_MS=5000
```

Start FastAPI from the repository root:

```powershell
python -m uvicorn service.main:app --app-dir ml-service --host 127.0.0.1 --port 8000
```

Apply migrations and start the backend from `backend/`:

```powershell
npm run migrate
npm run dev
```

Migration 005 adds a unique index on `(machine_id, timestamp)` to the existing `anomaly_results` table. Scoring uses `INSERT ... ON CONFLICT ... DO UPDATE` for retry safety. It does not create another anomaly table. The existing schema has no session-id column; the API verifies that the requested session belongs to the machine and contains the timestamp, and returns that session context to the caller.

## Health and readiness

- FastAPI `GET /health` reports that the process is running.
- FastAPI `GET /ready` reports ready only after the model and configuration have loaded.
- Existing backend `GET /api/v1/health` and `GET /api/v1/health/db` remain available.

## API contract

FastAPI `POST /api/v1/anomaly/score` accepts exactly the nine feature values as finite JSON numbers. It rejects missing and unknown fields. Its response contains `anomaly_score`, `anomaly_status`, `model_name`, `model_version`, and `features_used`. The score is the existing Phase 4 convention `-IsolationForest.score_samples(...)`; higher is more anomalous. Thresholds are loaded from `artifacts/anomaly_detection/threshold_config.json` without rounding or recalibration.

The backend `POST /api/v1/anomalies/score` accepts machine/session/time context and a nested feature vector:

```json
{
  "machine_id": "00000000-0000-4000-8000-000000000001",
  "session_id": "780fc743-2049-492f-a939-f1096faec6ac",
  "timestamp": "2026-11-01T09:03:01Z",
  "features": {
    "current_mean": 0.8565,
    "current_std": 1.479473808,
    "current_imbalance": 67.4551532,
    "voltage_mean": 231.6988333,
    "voltage_imbalance": 0.06222200183,
    "vibration_rms": 16137.61487,
    "vibration_magnitude_std": 168.0629678,
    "temperature_delta": 0.3485,
    "temperature_rate": 2.505263158
  }
}
```

These are the values of an existing first-row Phase 3 feature window, not fabricated runtime sensor readings. A successful response includes the persisted anomaly result and model metadata. Invalid requests receive a 400 response; unknown machine/session context receives 404; ML service connection/availability failures receive 503, timeouts 504, invalid ML responses 502, and database failures a sanitized 500 response. Secrets, stack traces, and filesystem paths are not returned.

For that feature vector, FastAPI returns the verified Phase 4 score:

```json
{
  "success": true,
  "data": {
    "anomaly_score": 0.5865701300588767,
    "anomaly_status": "NORMAL",
    "model_name": "IsolationForest",
    "model_version": "isolation-forest-v1",
    "features_used": [
      "current_mean",
      "current_std",
      "current_imbalance",
      "voltage_mean",
      "voltage_imbalance",
      "vibration_rms",
      "vibration_magnitude_std",
      "temperature_delta",
      "temperature_rate"
    ]
  }
}
```

## End-to-end smoke test

After both services are running and migration 005 is applied, execute from `ml-service/`:

```powershell
python smoke_test_integration.py
```

The smoke test takes a real feature vector and session context from the existing ML-ready artifact, calls the backend, confirms the prediction was written to `anomaly_results`, and deletes only the newly created smoke-test row. It refuses to run against an already-occupied `(machine_id, timestamp)` key rather than overwriting an existing anomaly record.

## Tests

From `ml-service/`:

```powershell
python -m unittest discover -s tests -p test_inference_service.py
```

From `backend/`:

```powershell
npm test
npm run check
```
