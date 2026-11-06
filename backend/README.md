# Backend

Express API using CommonJS. It loads configuration from `backend/.env`, requires a reachable PostgreSQL database at startup, and exposes versioned health endpoints.

## Commands

```powershell
npm install
npm run dev
npm start
npm run check
```

Set `DATABASE_URL` to a Neon PostgreSQL connection string in `.env`. Startup performs `SELECT 1` and exits with an error if the database is unavailable. `GET /api/v1/health/db` also performs a real query for each request.
