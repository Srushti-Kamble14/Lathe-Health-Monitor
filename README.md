# AI-Based IoT Lathe Machine Health Monitoring and Predictive Maintenance System

This project establishes a React frontend and Express API for a lathe machine health monitoring system, with Neon PostgreSQL connectivity, reviewed dataset analysis, schema migrations, and idempotent ingestion of the supplied college lathe dataset. The API remains read-only for machine/readings/sessions; dashboard, device ingestion, alerts, and production ML are not included.

## Technology stack

- Frontend: React, Vite, JavaScript, React Router DOM, and CSS
- Backend: Node.js, Express, CommonJS, Helmet, CORS, dotenv, and `pg`
- Database: Neon PostgreSQL
- Data analysis and ingestion: Python, pandas, psycopg2, and scikit-learn (exploratory analysis only; no production model)
- Future ML service: Python and FastAPI

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
│   ├── reports/
│   ├── data_audit.py
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

The backend listens on port `3000` by default, after verifying the configured database connection.

## Ingest the supplied dataset

Install the Python requirements and run the idempotent bulk loader from `ml-service/`:

```powershell
python -m pip install -r requirements.txt
python ingest_dataset.py
```

The script reads `DATABASE_URL` from the process environment or `backend/.env`. It reads only the approved sensor columns, maps date/time to UTC-interpreted PostgreSQL timestamps, checks duplicates and missing values, and verifies database counts/statistics. See [docs/database.md](./docs/database.md) and [docs/data-ingestion.md](./docs/data-ingestion.md).

## Run the frontend

From `frontend/`:

```powershell
npm run dev
```

Vite prints the local URL when the development server starts. To create and preview a production build, run `npm run build` followed by `npm run preview`.

## Test health endpoints

With the backend running:

```powershell
Invoke-RestMethod http://localhost:3000/api/v1/health
Invoke-RestMethod http://localhost:3000/api/v1/health/db
```

The database health endpoint reports success only after PostgreSQL responds to `SELECT 1`. Unknown API routes return a JSON 404 response.

Machine/readings/sessions APIs return versioned JSON responses. Reading queries support `machineId`, `start`, `end`, `limit`, and `offset`; page size is bounded. RPM is excluded from storage and API responses.
