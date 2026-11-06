CREATE TABLE IF NOT EXISTS machines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100) NOT NULL,
  machine_code VARCHAR(50) UNIQUE NOT NULL,
  description TEXT,
  location VARCHAR(255),
  status VARCHAR(30) NOT NULL DEFAULT 'INACTIVE',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT machines_status_check
    CHECK (status IN ('ACTIVE', 'INACTIVE', 'MAINTENANCE'))
);

INSERT INTO machines (id, name, machine_code, description, status)
VALUES (
  '00000000-0000-4000-8000-000000000001',
  'College Lathe Machine',
  'LATHE-001',
  'College lathe represented by the supplied CNC lathe dataset.',
  'INACTIVE'
)
ON CONFLICT (machine_code) DO NOTHING;
