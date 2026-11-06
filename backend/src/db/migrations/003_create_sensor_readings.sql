CREATE TABLE IF NOT EXISTS sensor_readings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  machine_id UUID NOT NULL REFERENCES machines(id),
  timestamp TIMESTAMPTZ NOT NULL,
  current_l1 DOUBLE PRECISION,
  current_l2 DOUBLE PRECISION,
  current_l3 DOUBLE PRECISION,
  voltage_l1 DOUBLE PRECISION,
  voltage_l2 DOUBLE PRECISION,
  voltage_l3 DOUBLE PRECISION,
  vibration_x DOUBLE PRECISION,
  vibration_y DOUBLE PRECISION,
  vibration_z DOUBLE PRECISION,
  ambient_temperature DOUBLE PRECISION,
  tool_temperature DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT sensor_readings_machine_timestamp_unique UNIQUE (machine_id, timestamp)
);

CREATE INDEX IF NOT EXISTS sensor_readings_timestamp_idx
  ON sensor_readings (timestamp);
