# Frontend

React and Vite application for the landing page and Phase 6 monitoring dashboard. The landing page remains available at `/`; the dashboard is at `/dashboard`.

## Commands

```powershell
npm install
npm run dev
npm run build
npm run preview
```

Set `VITE_API_BASE_URL` in `.env` to the versioned Express API base URL. The default is `http://localhost:3000/api/v1`. This is a public frontend setting; do not put credentials or secrets in Vite environment variables.

The dashboard API service in `src/services/api.js` centralizes requests and safe error handling. It loads machines and sessions from the backend, requests at most 500 readings and persisted anomaly results for the selected session, and displays the latest reading/anomaly plus backend, database, and ML readiness indicators. Recharts renders current, voltage, vibration, and temperature time series. Displayed timestamps are formatted in UTC.

Latest reading/anomaly and service health are refreshed manually or polled every 15 seconds. Historical session data is fetched only when the machine/session changes. Empty and unavailable data are shown explicitly; anomaly scores and statuses come only from persisted backend results, and are not treated as physical fault diagnoses.
