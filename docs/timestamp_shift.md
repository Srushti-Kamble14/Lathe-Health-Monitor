# Dataset Timestamp Translation Report

This operation was a deterministic constant timestamp translation. Every affected measurement/session timestamp received the same offset; no readings were synthesized, dropped, reordered, or independently retimed. Sensor and feature calculations were not rerun.

Original minimum timestamp: `2020-02-22T09:03:01+00:00`

Original maximum timestamp: `2020-02-28T18:15:21+00:00`

New minimum timestamp: `2026-11-01T09:03:01+00:00`

New maximum timestamp: `2026-11-07T18:15:21+00:00`

Timestamp offset applied: `2444 days, 0:00:00` (`211161600` seconds)

Rows affected: `67258`

Sessions affected: `6`

Original sampling interval distribution (seconds: count): `{"3": 67252}`

New sampling interval distribution (seconds: count): `{"3": 67252}`

Original and new session durations / inter-session gaps (seconds):

| Session | Original duration | New duration | Original preceding gap | New preceding gap |
|---:|---:|---:|---:|---:|
| 1 | 34212.0 | 34212.0 | None | None |
| 2 | 33420.0 | 33420.0 | 138657.0 | 138657.0 |
| 3 | 33246.0 | 33246.0 | 52805.0 | 52805.0 |
| 4 | 34212.0 | 34212.0 | 53260.0 | 53260.0 |
| 5 | 33420.0 | 33420.0 | 52257.0 | 52257.0 |
| 6 | 33246.0 | 33246.0 | 52805.0 | 52805.0 |

Sensor values changed: `No` (database sensor-value digest unchanged)

Feature values changed: `No` (all non-time ML-ready artifact columns unchanged)

Split assignments changed: `No` (session split digest unchanged; sessions 1–3 TRAIN, 4 VALIDATION, 5–6 TEST)

Raw CSV checksum before: `a9a162109d8654d113d4ccb81cb8b7a62bbf7f55e02c4c3420653295d601b3ec`

Raw CSV checksum after: `a9a162109d8654d113d4ccb81cb8b7a62bbf7f55e02c4c3420653295d601b3ec`

Validation result: `PASS` — database rows and sessions, temporal interval distribution, session durations and gaps, feature values, split assignments, timestamp range, and raw CSV checksum all verified.

The database update was transactional and affected only `sensor_readings.timestamp`, `machine_sessions.start_time/end_time`, and any anomaly-result timestamp linked to one of this machine's readings. Creation/update metadata and schema were not changed. Phase 3 temporal plots were redrawn from the existing feature rows solely to display their translated timestamps.
