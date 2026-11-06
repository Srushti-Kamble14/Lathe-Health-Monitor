CREATE TABLE IF NOT EXISTS machine_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  machine_id UUID NOT NULL REFERENCES machines(id),
  session_number INTEGER NOT NULL,
  start_time TIMESTAMPTZ NOT NULL,
  end_time TIMESTAMPTZ NOT NULL,
  sample_count INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT machine_sessions_time_order_check CHECK (start_time <= end_time),
  CONSTRAINT machine_sessions_sample_count_check CHECK (sample_count >= 0),
  CONSTRAINT machine_sessions_number_check CHECK (session_number > 0),
  CONSTRAINT machine_sessions_machine_number_unique UNIQUE (machine_id, session_number)
);

CREATE INDEX IF NOT EXISTS machine_sessions_machine_start_idx
  ON machine_sessions (machine_id, start_time);
