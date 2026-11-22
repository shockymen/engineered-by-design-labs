-- Voiding a finalized payroll run (agent-session task). PostgreSQL 13+.
-- Business rules (decided by the human):
--   R1  A finalized run may be voided only if no payment has been submitted for it.
--   R2  After a void, the same tenant and period may get a new run (a new revision).
--   R3  At most one ACTIVE run per (tenant, period); voided history is kept.

CREATE TABLE IF NOT EXISTS payroll_runs_rev (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  period text NOT NULL,
  revision integer NOT NULL CHECK (revision > 0),
  approval_version integer NOT NULL CHECK (approval_version > 0),
  status text NOT NULL CHECK (status IN ('ACTIVE', 'VOIDED')),
  void_reason text,
  voided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_rev_tenant_period_revision UNIQUE (tenant_id, period, revision),
  -- Lets other tables reference "this run, while it is in this status".
  CONSTRAINT uq_rev_id_status UNIQUE (id, status),
  CONSTRAINT ck_rev_void_fields CHECK (
    (status = 'VOIDED') = (void_reason IS NOT NULL AND voided_at IS NOT NULL)
  )
);

-- R3: only one ACTIVE run per tenant and period.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rev_one_active
  ON payroll_runs_rev (tenant_id, period) WHERE status = 'ACTIVE';

-- R1, enforced by the database: a payment row references (run, 'ACTIVE').
--   * Inserting a payment for a voided run fails: no (id, 'ACTIVE') row exists.
--   * Voiding a run that has payments fails: the referenced key (id, 'ACTIVE') is still in use.
CREATE TABLE IF NOT EXISTS payment_instructions (
  id uuid PRIMARY KEY,
  run_id uuid NOT NULL,
  run_status text NOT NULL DEFAULT 'ACTIVE' CHECK (run_status = 'ACTIVE'),
  amount_cents bigint NOT NULL CHECK (amount_cents > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_payment_active_run
    FOREIGN KEY (run_id, run_status) REFERENCES payroll_runs_rev (id, status)
);

CREATE TABLE IF NOT EXISTS run_outbox (
  id uuid PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES payroll_runs_rev (id),
  event_type text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_run_outbox_event UNIQUE (run_id, event_type)
);

-- Control tables for the deliberately unsafe check-then-void experiment (no constraints).
CREATE TABLE IF NOT EXISTS void_ctrl_runs (id uuid PRIMARY KEY, status text NOT NULL);
CREATE TABLE IF NOT EXISTS void_ctrl_payments (id uuid PRIMARY KEY, run_id uuid NOT NULL);
