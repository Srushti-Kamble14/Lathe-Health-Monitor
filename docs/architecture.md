# Intended architecture

```text
ESP32-S3 → Node.js/Express → Neon PostgreSQL
                    ↕
             Python/FastAPI ML Service

React Frontend → Node.js/Express APIs
```

The React frontend communicates with versioned Node.js/Express APIs. The backend is the boundary for future device data ingestion and persistence in Neon PostgreSQL. A separately developed Python/FastAPI service is intended to provide machine-learning capabilities and will communicate with the backend through a defined service integration.

The backend stores the approved temperature, 3-axis vibration, 3-phase current, and 3-phase voltage readings in PostgreSQL. The supplied historical dataset is imported through the separate Python batch ingestion script. A later device-ingestion path and separately developed Python/FastAPI inference service are not implemented yet.

Database tables and ingestion are documented in [database.md](./database.md) and [data-ingestion.md](./data-ingestion.md). RPM and other unapproved CSV fields are excluded from the database, ML inputs, and APIs.
