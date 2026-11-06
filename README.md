# AI-Based IoT Lathe Machine Health Monitoring and Predictive Maintenance System

Phase 1 establishes the frontend and backend foundations for a lathe machine health monitoring system. It includes a React landing page, an Express API, a Neon PostgreSQL connection check, and architecture documentation. Machine dashboards, sensor ingestion, application tables, and machine-health analytics are not part of this phase.

## Technology stack

- Frontend: React, Vite, JavaScript, React Router DOM, and CSS
- Backend: Node.js, Express, CommonJS, Helmet, CORS, dotenv, and `pg`
- Database: Neon PostgreSQL
- Future ML service: Python and FastAPI (placeholder documentation only in this phase)

## Folder structure

```text
lathe-health-monitor/
├── backend/
│   ├── src/
│   │   ├── config/
│   │   ├── controllers/
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

For production mode, run `npm start`. The backend listens on port `3000` by default, after verifying the configured database connection.

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
