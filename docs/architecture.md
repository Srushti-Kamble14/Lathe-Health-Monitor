# Intended architecture

```text
ESP32-S3 → Node.js/Express → Neon PostgreSQL
                    ↕
             Python/FastAPI ML Service

React Frontend → Node.js/Express APIs
```

The React frontend communicates with versioned Node.js/Express APIs. The backend is the boundary for future device data ingestion and persistence in Neon PostgreSQL. A separately developed Python/FastAPI service is intended to provide machine-learning capabilities and will communicate with the backend through a defined service integration.

This Phase 1 foundation does not implement device connectivity, sensor ingestion, application tables, predictions, or the ML service. The only database operation currently exposed is the real `SELECT 1` connectivity check.
