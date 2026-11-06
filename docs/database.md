# Database architecture

The Node.js backend connects to Neon PostgreSQL through the shared `pg` connection pool (`backend/src/config/database.js`). Database credentials are configured only through `DATABASE_URL` in the environment or `backend/.env`; never commit `.env`.

## Tables and relationships

- `machines`: one seeded `College Lathe Machine` (`LATHE-001`), initially `INACTIVE` until the machine is commissioned for live monitoring. Status is constrained to `ACTIVE`, `INACTIVE`, or `MAINTENANCE`.
- `machine_sessions`: timestamp-gap-derived recording sessions belonging to a machine. `session_number` is unique per machine; `start_time <= end_time`; sample count is non-negative. Session numbers describe recordings only, not machine health or operating states.
- `sensor_readings`: approved raw temperature, three-axis vibration, three-phase current, and three-phase voltage values belonging to a machine. `(machine_id, timestamp)` is unique for this dataset. Source timestamps have no timezone; ingestion consistently interprets them as UTC for `TIMESTAMPTZ` storage. This convention does not assert the source machine's actual timezone.
- `anomaly_results`: optional future model score/status rows linked to a machine and optionally a reading. Allowed non-null statuses are `NORMAL`, `WARNING`, and `ANOMALOUS`; these mean application-level anomaly states and are not confirmed mechanical faults. No fault type or target label is stored.
- `schema_migrations`: migration filename and application time.

## Indexes

- `sensor_readings(machine_id, timestamp)` unique constraint/index, plus `sensor_readings(timestamp)`.
- `machine_sessions(machine_id, start_time)` and unique `(machine_id, session_number)`.
- `anomaly_results(machine_id, timestamp)` and `anomaly_results(reading_id)`.

Foreign keys prevent readings/sessions/results from referencing missing machines and results from referencing missing readings. No unsupported physical sensor bounds or derived ML features are stored.

## Migration process

SQL migrations are in `backend/src/db/migrations/` and run in filename order:

```powershell
cd backend
npm run migrate
```

The runner takes a PostgreSQL advisory lock, creates `schema_migrations` if needed, and applies each unrecorded migration in its own transaction. Applied migration files are skipped on subsequent runs. Migrations create tables/indexes and seed the single college machine; they do not automatically drop tables or data.

Apply database changes only to the intended Neon database after checking `DATABASE_URL`. API server startup checks database connectivity, but migrations are intentionally a separate command.
