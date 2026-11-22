import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Pool } from "pg";
import { ApprovalConflictError, finalizePayroll } from "./finalize.js";

const dsn = process.env.PG_DSN ?? "postgresql://meridian:meridian@localhost:5433/meridian";
const TENANT = "11111111-1111-1111-1111-111111111111";
const PERIOD = "2026-11";
const N = 32;

async function counts(pool: Pool) {
  const runs = await pool.query("SELECT count(*)::int AS n FROM payroll_runs");
  const outbox = await pool.query("SELECT count(*)::int AS n FROM outbox_events");
  return { runs: runs.rows[0].n as number, outbox: outbox.rows[0].n as number };
}

async function main() {
  const pool = new Pool({ connectionString: dsn, max: N });
  await pool.query(readFileSync(new URL("../sql/schema.sql", import.meta.url), "utf8"));
  const reset = () => pool.query("TRUNCATE outbox_events, payroll_runs CASCADE");
  const results: string[] = [];

  // 1. Competing identical requests -> one run, one outbox row.
  await reset();
  const settled = await Promise.allSettled(
    Array.from({ length: N }, () =>
      finalizePayroll(pool, { tenantId: TENANT, period: PERIOD, approvalVersion: 1 }),
    ),
  );
  const ok = settled.filter((s) => s.status === "fulfilled") as PromiseFulfilledResult<
    Awaited<ReturnType<typeof finalizePayroll>>
  >[];
  const created = ok.filter((s) => s.value.status === "created").length;
  const ids = new Set(ok.map((s) => s.value.runId));
  const c1 = await counts(pool);
  assert.equal(ok.length, N, "every request should succeed");
  assert.deepEqual(c1, { runs: 1, outbox: 1 });
  assert.equal(created, 1);
  assert.equal(ids.size, 1);
  results.push(`PASS: ${N} concurrent requests -> ${c1.runs} run, ${c1.outbox} outbox row, 1 created`);

  // 2. A request for a different approval version is a conflict, not a silent success.
  await assert.rejects(
    finalizePayroll(pool, { tenantId: TENANT, period: PERIOD, approvalVersion: 2 }),
    ApprovalConflictError,
  );
  results.push("PASS: different approval version rejected with ApprovalConflictError");

  // 3. Injected crash before the outbox insert rolls everything back; retry then succeeds once.
  await reset();
  await assert.rejects(
    finalizePayroll(pool, { tenantId: TENANT, period: PERIOD, approvalVersion: 1 }, { failAfterRunInsert: true }),
  );
  assert.deepEqual(await counts(pool), { runs: 0, outbox: 0 });
  const retry = await finalizePayroll(pool, { tenantId: TENANT, period: PERIOD, approvalVersion: 1 });
  assert.equal(retry.status, "created");
  assert.deepEqual(await counts(pool), { runs: 1, outbox: 1 });
  results.push("PASS: crash rolled back run + outbox; retry created exactly one of each");

  await pool.end();
  console.log(results.join("\n"));
  console.log("ALL TYPESCRIPT CHECKS PASSED");
}

main().catch((err) => {
  console.error("FAIL:", err);
  process.exit(1);
});
