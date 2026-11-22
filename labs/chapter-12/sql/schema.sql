-- Meridian Chapter 12 reference schema (PostgreSQL 13+).
-- Safe tables follow the chapter; *_unsafe / counters tables exist only to
-- demonstrate the failures the safe design prevents.

CREATE TABLE IF NOT EXISTS payroll_runs (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  period text NOT NULL,
  approval_version integer NOT NULL CHECK (approval_version > 0),
  state text NOT NULL CHECK (state = 'FINALIZED'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_payroll_tenant_period UNIQUE (tenant_id, period)
);

CREATE TABLE IF NOT EXISTS outbox_events (
  id uuid PRIMARY KEY,
  payroll_run_id uuid NOT NULL REFERENCES payroll_runs(id),
  event_type text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_outbox_payroll_event UNIQUE (payroll_run_id, event_type)
);

-- Deliberately UNSAFE: same shape as payroll_runs but no uniqueness constraint.
CREATE TABLE IF NOT EXISTS payroll_runs_unsafe (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  period text NOT NULL,
  approval_version integer NOT NULL,
  state text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Used for the lost-update / row-lock demonstration.
CREATE TABLE IF NOT EXISTS counters (
  id integer PRIMARY KEY,
  value integer NOT NULL
);
