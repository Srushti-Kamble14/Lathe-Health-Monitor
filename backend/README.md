# Backend

Express API using CommonJS. It loads configuration from `backend/.env`, requires a reachable PostgreSQL database at startup, and exposes versioned health, machine, reading, and session endpoints.

## Commands

```powershell
npm install
npm run dev
npm start
npm run migrate
npm run check
```

Set `DATABASE_URL` to a Neon PostgreSQL connection string in `.env`. Startup performs `SELECT 1` and exits with an error if the database is unavailable. Run `npm run migrate` before using the data APIs. Migrations are tracked and are not automatically destructive.

Read endpoints:

- `GET /api/v1/machines`
- `GET /api/v1/machines/:id`
- `GET /api/v1/readings/latest?machineId=...`
- `GET /api/v1/readings?machineId=...&start=...&end=...&limit=100&offset=0`
- `GET /api/v1/sessions?machineId=...`
- `GET /api/v1/health/db`

Readings are paginated (default 100, maximum 500 per page). See `docs/database.md` and `docs/data-ingestion.md` for schema and ingestion details.
