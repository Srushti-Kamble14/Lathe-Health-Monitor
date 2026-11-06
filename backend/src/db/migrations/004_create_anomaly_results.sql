CREATE TABLE IF NOT EXISTS anomaly_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  machine_id UUID NOT NULL REFERENCES machines(id),
  reading_id UUID REFERENCES sensor_readings(id),
  timestamp TIMESTAMPTZ NOT NULL,
  anomaly_score DOUBLE PRECISION,
  anomaly_status VARCHAR(30),
  model_name VARCHAR(100),
  model_version VARCHAR(50),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT anomaly_results_status_check
    CHECK (anomaly_status IS NULL OR anomaly_status IN ('NORMAL', 'WARNING', 'ANOMALOUS'))
);

CREATE INDEX IF NOT EXISTS anomaly_results_machine_timestamp_idx
  ON anomaly_results (machine_id, timestamp);

CREATE INDEX IF NOT EXISTS anomaly_results_reading_id_idx
  ON anomaly_results (reading_id);
