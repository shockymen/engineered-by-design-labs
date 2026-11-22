import { randomUUID } from "node:crypto";
import type { Pool } from "pg";

export interface FinalizeInput {
  tenantId: string;
  period: string;
  approvalVersion: number;
}

export type FinalizeResult = { status: "created" | "existing"; runId: string };

export class ApprovalConflictError extends Error {
  constructor(public readonly runId: string, public readonly existingVersion: number) {
    super(`Period already finalized with approval version ${existingVersion}`);
  }
}

/**
 * Finalize a payroll run exactly once per (tenant, period).
 * The unique constraint decides the winner; the outbox row is written in the
 * same transaction, and only by the winner. A repeat request returns the
 * existing run only if it refers to the same approved calculation version.
 * `failAfterRunInsert` exists solely so tests can simulate a crash.
 */
export async function finalizePayroll(
  pool: Pool,
  input: FinalizeInput,
  opts: { failAfterRunInsert?: boolean } = {},
): Promise<FinalizeResult> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const inserted = await client.query<{ id: string }>(
      `INSERT INTO payroll_runs (id, tenant_id, period, approval_version, state)
       VALUES ($1, $2, $3, $4, 'FINALIZED')
       ON CONFLICT (tenant_id, period) DO NOTHING
       RETURNING id`,
      [randomUUID(), input.tenantId, input.period, input.approvalVersion],
    );

    if (inserted.rowCount === 1) {
      if (opts.failAfterRunInsert) throw new Error("injected failure before outbox insert");
      const runId = inserted.rows[0].id;
      await client.query(
        `INSERT INTO outbox_events (id, payroll_run_id, event_type)
         VALUES ($1, $2, 'PAYROLL_FINALIZED')`,
        [randomUUID(), runId],
      );
      await client.query("COMMIT");
      return { status: "created", runId };
    }

    const existing = await client.query<{ id: string; approval_version: number }>(
      `SELECT id, approval_version FROM payroll_runs WHERE tenant_id = $1 AND period = $2`,
      [input.tenantId, input.period],
    );
    await client.query("COMMIT");
    const row = existing.rows[0];
    if (row.approval_version !== input.approvalVersion) {
      throw new ApprovalConflictError(row.id, row.approval_version);
    }
    return { status: "existing", runId: row.id };
  } catch (err) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw err;
  } finally {
    client.release();
  }
}
