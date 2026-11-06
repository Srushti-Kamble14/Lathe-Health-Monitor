# Runtime architecture

```text
Sensor / database feature vector
             |
             v
Node.js / Express API ---------> Neon PostgreSQL
             |
             v
Python / FastAPI inference service
             |
             v
Loaded Phase 4 Isolation Forest
             |
             +---- score and status ----> Node.js / Express

React Frontend ----------------> Node.js / Express APIs
```

The React frontend communicates with versioned Node.js/Express APIs. The backend validates machine/session context, sends the exact approved nine-feature vector to the Python service, and persists the returned score/status in the existing `anomaly_results` table. The backend is configured with `ML_SERVICE_URL`; inference calls have a timeout and return sanitized errors on dependency failures.

The FastAPI process loads the persisted Phase 4 Isolation Forest and its model/threshold metadata once during startup. Requests only run `score_samples`; they do not train or update a model. The score is `-score_samples`, so larger scores indicate more anomalous behavior, with the Phase 4 warning/anomaly thresholds loaded from the checked-in threshold configuration. Startup fails if these artifacts are missing or incompatible.

The backend stores the approved temperature, 3-axis vibration, 3-phase current, and 3-phase voltage readings in PostgreSQL. Migration `005_unique_anomaly_machine_timestamp.sql` adds a unique `(machine_id, timestamp)` key so retries upsert rather than create duplicate results. Session context is validated and returned by the API; the existing table has no `session_id` column, so the record stores the supported machine, reading, and timestamp context.

The detector is unsupervised and the data has no verified fault labels. An anomaly status is not a confirmed fault diagnosis, and feature-level descriptions do not establish causality. Additional real-world validation is required before operational predictive-maintenance use.

Database tables and ingestion are documented in [database.md](./database.md) and [data-ingestion.md](./data-ingestion.md). RPM and other unapproved fields are excluded from storage and inference APIs.
