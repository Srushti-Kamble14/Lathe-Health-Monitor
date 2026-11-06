# Backend

Express API using CommonJS. It loads configuration from `backend/.env`, requires a reachable PostgreSQL database at startup, and exposes versioned health, machine, reading, session, persisted anomaly, and ML-readiness endpoints.

## Commands

```powershell
npm install
npm run dev
npm start
npm run migrate
npm run check
npm test
```

Set `DATABASE_URL` to a Neon PostgreSQL connection string in `.env`. Startup performs `SELECT 1` and exits with an error if the database is unavailable. Run `npm run migrate` before using the data APIs. Migrations are tracked and are not automatically destructive.

Read endpoints:

- `GET /api/v1/machines`
- `GET /api/v1/machines/:id`
- `GET /api/v1/readings/latest?machineId=...`
- `GET /api/v1/readings?machineId=...&start=...&end=...&limit=100&offset=0`
- `GET /api/v1/sessions?machineId=...`
- `GET /api/v1/anomalies?machineId=...&start=...&end=...&status=WARNING&limit=50&offset=0`
- `GET /api/v1/anomalies/latest?machineId=...`
- `GET /api/v1/ml/ready`
- `GET /api/v1/health/db`
- `POST /api/v1/anomalies/score`

Readings are paginated (default 100, maximum 500 per page). Anomaly history defaults to 50 records per page (maximum 500), and its GET endpoints read persisted `anomaly_results` only; they do not call the model or calculate scores. Supported anomaly statuses are `NORMAL`, `WARNING`, and `ANOMALOUS`. `GET /api/v1/ml/ready` proxies the FastAPI readiness check and returns sanitized unavailable/timeout errors. See `docs/database.md` and `docs/data-ingestion.md` for schema and ingestion details.

Anomaly scoring validates machine/session/time context, calls the configured Python FastAPI service, and persists its result in the existing `anomaly_results` table. Configure `ML_SERVICE_URL` and `ML_SERVICE_TIMEOUT_MS` in `.env`. Run `npm run migrate` to apply migration 005, which adds the uniqueness key used for idempotent result persistence. See [docs/anomaly-inference.md](../docs/anomaly-inference.md) for the service contract, startup steps, and smoke test.
