# AI-Based IoT Lathe Machine Health Monitoring and Predictive Maintenance System

This project includes a React monitoring dashboard, Express API, Neon PostgreSQL persistence, reviewed dataset analysis, database-backed feature engineering, and an offline-trained exploratory anomaly detector exposed through FastAPI. It does not include device ingestion, alerts, or supervised fault classification.

## Technology stack

- Frontend: React, Vite, JavaScript, React Router DOM, and CSS
- Backend: Node.js, Express, CommonJS, Helmet, CORS, dotenv, and `pg`
- Database: Neon PostgreSQL
- Data analysis and ingestion: Python, pandas, psycopg2, and scikit-learn
- ML inference: Python, FastAPI, and the persisted Phase 4 Isolation Forest

## Folder structure

```text
lathe-health-monitor/
├── backend/
│   ├── src/
│   │   ├── config/
│   │   ├── controllers/
│   │   ├── db/migrations/
│   │   ├── middleware/
│   │   ├── routes/
│   │   └── services/
│   ├── .env.example
│   ├── package.json
│   └── README.md
├── docs/
│   ├── anomaly-inference.md
│   └── architecture.md
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   └── styles/
│   ├── .env.example
│   ├── package.json
│   └── README.md
├── ml-service/
│   ├── data/ (local-only, Git-ignored source CSV)
│   ├── artifacts/features/ (ML-ready dataset and diagnostics)
│   ├── artifacts/anomaly_detection/ (scores, thresholds, metadata, serving model)
│   ├── service/ (FastAPI inference application)
│   ├── reports/ (audit, feature engineering, and anomaly evaluation)
│   ├── data_audit.py
│   ├── feature_config.py
│   ├── feature_engineering.py
│   ├── ingest_dataset.py
│   ├── ml_target_analysis.py
│   └── README.md
├── .env.example
└── .gitignore
```

## Prerequisites

- Node.js 20.19+ or 22.12+ and npm
- A Neon PostgreSQL database and its connection string

## Installation

Install dependencies separately:

```powershell
cd backend
npm install
cd ..\frontend
npm install
```

## Environment configuration

Copy `backend/.env.example` to `backend/.env` and set `DATABASE_URL` to the connection string from Neon. Do not commit `.env` or share its contents. The application requires a valid database connection at startup and performs a real `SELECT 1` before accepting traffic.

Set `ML_SERVICE_URL=http://localhost:8000` and `ML_SERVICE_TIMEOUT_MS=5000` in `backend/.env` for anomaly scoring.

Copy `frontend/.env.example` to `frontend/.env` if you need to change the API URL. Its default points to `http://localhost:3000/api/v1`.

## Run the backend

From `backend/`:

```powershell
npm run dev
```

For production mode, run `npm start`. Before starting the backend, apply schema migrations from `backend/`:

```powershell
npm run migrate
npm run dev
```

The backend listens on port `3000` by default, after verifying the configured database connection. For Phase 5 inference startup, model export, and the API contract, see [docs/anomaly-inference.md](./docs/anomaly-inference.md).

## Ingest the supplied dataset

Install the Python requirements and run the idempotent bulk loader from `ml-service/`:

```powershell
python -m pip install -r requirements.txt
python ingest_dataset.py
```

The script reads `DATABASE_URL` from the process environment or `backend/.env`. It reads only the approved sensor columns, maps date/time to UTC-interpreted PostgreSQL timestamps, checks duplicates and missing values, and verifies database counts/statistics. See [docs/database.md](./docs/database.md) and [docs/data-ingestion.md](./docs/data-ingestion.md).

## Prepare ML-ready features

After ingestion, run the database-backed Phase 3 feature pipeline from `ml-service/`:

```powershell
python feature_engineering.py
```

It compares 30/60/120/300-second windows, prevents windows crossing recording sessions or detected gaps, and writes selected features with chronological session-level splits to `ml-service/artifacts/features/ml_ready_features.csv`. Details and figures are generated under `ml-service/reports/`. The approved artifact is used by the offline Phase 4 anomaly detector. See [ml-service/README.md](./ml-service/README.md).

## Run the frontend

From `frontend/`:

```powershell
npm run dev
```

Vite prints the local URL when the development server starts. To create and preview a production build, run `npm run build` followed by `npm run preview`.

Open `/dashboard` to view backend-provided machine, sensor, session, and persisted anomaly data. The dashboard reads through the versioned Express API configured by `VITE_API_BASE_URL`; it does not calculate anomaly scores or use simulated sensor values. See [frontend/README.md](./frontend/README.md) for dashboard details.

## Test health endpoints

With the backend running:

```powershell
Invoke-RestMethod http://localhost:3000/api/v1/health
Invoke-RestMethod http://localhost:3000/api/v1/health/db
```

The database health endpoint reports success only after PostgreSQL responds to `SELECT 1`. Unknown API routes return a JSON 404 response.

Machine/readings/sessions APIs return versioned JSON responses. Reading queries support `machineId`, `start`, `end`, `limit`, and `offset`; page size is bounded. RPM is excluded from storage and API responses.
