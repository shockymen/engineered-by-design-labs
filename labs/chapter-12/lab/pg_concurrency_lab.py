#!/usr/bin/env python3
"""Meridian Chapter 12: PostgreSQL concurrency lab.

Runs real multi-connection tests against PostgreSQL and writes lab/results.json
(PostgreSQL version, isolation level, every check with PASS/FAIL).

    pip install "psycopg[binary]"
    docker compose up -d
    python lab/pg_concurrency_lab.py

Exit code 0 only if every check passes.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DSN = os.environ.get("PG_DSN", "postgresql://meridian:meridian@localhost:5433/meridian")
ROOT = Path(__file__).resolve().parent.parent
BARRIER_TIMEOUT = 45

TENANT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
PERIOD = "2026-11"

CHECKS: list[dict] = []


class InjectedFailure(Exception):
    """Simulates a crash between the payroll insert and the outbox insert."""


def check(name: str, ok: bool, detail: str) -> bool:
    CHECKS.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}: {name} -- {detail}")
    return ok


def connect() -> psycopg.Connection:
    return psycopg.connect(DSN)  # autocommit off: each connection is its own transaction


def reset(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE outbox_events, payroll_runs, payroll_runs_unsafe, counters"
        )
        cur.execute("INSERT INTO counters (id, value) VALUES (1, 0)")
    conn.commit()


def count(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")  # table names are constants here
        n = cur.fetchone()[0]
    conn.commit()
    return n


def run_threads(n: int, target) -> list:
    """Start n threads, each calling target(i, barrier); return their results in order."""
    barrier = threading.Barrier(n)
    results: list = [None] * n

    def wrap(i: int) -> None:
        try:
            results[i] = target(i, barrier)
        except Exception as exc:  # recorded so the lab reports it instead of hanging
            results[i] = ("error", repr(exc))
            barrier.abort()

    threads = [threading.Thread(target=wrap, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# --- the code under test ----------------------------------------------------

def finalize_safe(conn, tenant_id, period, approval_version, fail_after_run=False):
    """Conflict-aware finalization: unique constraint + outbox in one transaction."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO payroll_runs (id, tenant_id, period, approval_version, state)
                   VALUES (%s, %s, %s, %s, 'FINALIZED')
                   ON CONFLICT (tenant_id, period) DO NOTHING
                   RETURNING id""",
                (uuid.uuid4(), tenant_id, period, approval_version),
            )
            row = cur.fetchone()
            if row is not None:  # this request won the insert
                if fail_after_run:
                    raise InjectedFailure("crash before outbox insert")
                cur.execute(
                    """INSERT INTO outbox_events (id, payroll_run_id, event_type)
                       VALUES (%s, %s, 'PAYROLL_FINALIZED')""",
                    (uuid.uuid4(), row[0]),
                )
                conn.commit()
                return ("created", row[0])
            cur.execute(
                "SELECT id, approval_version FROM payroll_runs "
                "WHERE tenant_id = %s AND period = %s",
                (tenant_id, period),
            )
            run_id, existing_version = cur.fetchone()
        conn.commit()
        if existing_version != approval_version:
            return ("conflict", run_id)  # same business key, different approved basis
        return ("existing", run_id)
    except Exception:
        conn.rollback()
        raise


# --- experiments --------------------------------------------------------------

def exp_unsafe_check_then_insert(admin) -> None:
    reset(admin)

    def worker(i, barrier):
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM payroll_runs_unsafe WHERE tenant_id = %s AND period = %s",
                    (TENANT_A, PERIOD),
                )
                existing = cur.fetchone()
                barrier.wait(BARRIER_TIMEOUT)  # both have seen "no run" before either inserts
                if existing is None:
                    cur.execute(
                        """INSERT INTO payroll_runs_unsafe
                           (id, tenant_id, period, approval_version, state)
                           VALUES (%s, %s, %s, 1, 'FINALIZED')""",
                        (uuid.uuid4(), TENANT_A, PERIOD),
                    )
            conn.commit()
            return ("inserted",)
        finally:
            conn.close()

    outcomes = run_threads(2, worker)
    errors = [outcome for outcome in outcomes if outcome[0] == "error"]
    rows = count(admin, "payroll_runs_unsafe")
    check("UNSAFE check-then-insert produces duplicates", rows == 2 and not errors,
          f"2 concurrent requests produced {rows} payroll rows; {len(errors)} worker error(s): {errors}")


def exp_safe_unique_and_outbox(admin) -> None:
    reset(admin)
    n = 32

    def worker(i, barrier):
        conn = connect()
        try:
            barrier.wait(BARRIER_TIMEOUT)
            return finalize_safe(conn, TENANT_A, PERIOD, 1)
        finally:
            conn.close()

    results = run_threads(n, worker)
    created = sum(1 for r in results if r[0] == "created")
    existing = sum(1 for r in results if r[0] == "existing")
    errors = [r for r in results if r[0] == "error"]
    runs, outbox = count(admin, "payroll_runs"), count(admin, "outbox_events")
    run_ids = {r[1] for r in results if r[0] in ("created", "existing")}
    check("SAFE finalization is unique under competition",
          runs == 1 and outbox == 1 and created == 1 and existing == n - 1
          and not errors and len(run_ids) == 1,
          f"{n} requests -> {runs} run, {outbox} outbox row, {created} created, "
          f"{existing} existing, {len(errors)} errors, {len(run_ids)} distinct run id(s) returned")


def exp_conflicting_versions(admin) -> None:
    reset(admin)
    n = 8
    versions = [1 if i % 2 == 0 else 2 for i in range(n)]

    def worker(i, barrier):
        conn = connect()
        try:
            barrier.wait(BARRIER_TIMEOUT)
            return finalize_safe(conn, TENANT_A, PERIOD, versions[i])
        finally:
            conn.close()

    results = run_threads(n, worker)
    with admin.cursor() as cur:
        cur.execute("SELECT approval_version FROM payroll_runs WHERE tenant_id = %s", (TENANT_A,))
        rows = cur.fetchall()
    admin.commit()
    runs = len(rows)
    winner = rows[0][0] if rows else None
    expected_conflicts = sum(1 for v in versions if v != winner)
    conflicts = sum(1 for r in results if r[0] == "conflict")
    created = sum(1 for r in results if r[0] == "created")
    errors = [r for r in results if r[0] == "error"]
    check("Conflicting approval versions are surfaced, not hidden",
          runs == 1 and created == 1 and conflicts == expected_conflicts and not errors,
          f"{runs} run (winning version {winner}); {conflicts} of {expected_conflicts} "
          f"mismatched requests reported a conflict; {len(errors)} errors")


def exp_rollback_atomicity(admin) -> None:
    reset(admin)
    conn = connect()
    try:
        try:
            finalize_safe(conn, TENANT_A, PERIOD, 1, fail_after_run=True)
            raised = False
        except InjectedFailure:
            raised = True
    finally:
        conn.close()
    runs, outbox = count(admin, "payroll_runs"), count(admin, "outbox_events")
    check("Crash before commit rolls back run and outbox together",
          raised and runs == 0 and outbox == 0,
          f"after injected failure: {runs} runs, {outbox} outbox rows (expected 0 and 0)")

    conn = connect()
    try:
        status, _ = finalize_safe(conn, TENANT_A, PERIOD, 1)
    finally:
        conn.close()
    runs, outbox = count(admin, "payroll_runs"), count(admin, "outbox_events")
    check("Retry after the crash succeeds exactly once",
          status == "created" and runs == 1 and outbox == 1,
          f"retry status={status}: {runs} run, {outbox} outbox row")


def exp_tenant_scope(admin) -> None:
    reset(admin)
    conn = connect()
    try:
        a = finalize_safe(conn, TENANT_A, PERIOD, 1)
        b = finalize_safe(conn, TENANT_B, PERIOD, 1)
    finally:
        conn.close()
    runs = count(admin, "payroll_runs")
    check("Uniqueness is scoped per tenant",
          a[0] == "created" and b[0] == "created" and runs == 2,
          f"same period, two tenants -> {runs} runs (a global unique period would give 1)")


def exp_lost_update(admin) -> None:
    n = 16

    def unsafe_worker(i, barrier):
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM counters WHERE id = 1")
                v = cur.fetchone()[0]
                barrier.wait(BARRIER_TIMEOUT)  # everyone has read the same value
                cur.execute("UPDATE counters SET value = %s WHERE id = 1", (v + 1,))
            conn.commit()
            return ("ok",)
        finally:
            conn.close()

    reset(admin)
    unsafe_outcomes = run_threads(n, unsafe_worker)
    unsafe_errors = [outcome for outcome in unsafe_outcomes if outcome[0] == "error"]
    with admin.cursor() as cur:
        cur.execute("SELECT value FROM counters WHERE id = 1")
        unsafe_value = cur.fetchone()[0]
    admin.commit()
    check("UNSAFE read-modify-write loses updates",
          unsafe_value < n and not unsafe_errors,
          f"{n} increments produced a final value of {unsafe_value}; {len(unsafe_errors)} worker error(s): {unsafe_errors}")

    def safe_worker(i, barrier):
        conn = connect()
        try:
            barrier.wait(BARRIER_TIMEOUT)
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM counters WHERE id = 1 FOR UPDATE")
                v = cur.fetchone()[0]
                cur.execute("UPDATE counters SET value = %s WHERE id = 1", (v + 1,))
            conn.commit()
            return ("ok",)
        finally:
            conn.close()

    reset(admin)
    safe_outcomes = run_threads(n, safe_worker)
    safe_errors = [outcome for outcome in safe_outcomes if outcome[0] == "error"]
    with admin.cursor() as cur:
        cur.execute("SELECT value FROM counters WHERE id = 1")
        safe_value = cur.fetchone()[0]
    admin.commit()
    check("SELECT ... FOR UPDATE serializes the same update",
          safe_value == n and not safe_errors,
          f"{n} increments produced a final value of {safe_value}; {len(safe_errors)} worker error(s): {safe_errors}")


def main() -> int:
    try:
        admin = connect()
    except psycopg.OperationalError as exc:
        print(f"Cannot connect to PostgreSQL at {DSN}\n{exc}\n"
              "Start it with: docker compose up -d", file=sys.stderr)
        return 2

    with admin.cursor() as cur:
        cur.execute((ROOT / "sql" / "schema.sql").read_text())
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        cur.execute("SHOW transaction_isolation")
        isolation = cur.fetchone()[0]
    admin.commit()
    print(f"Connected: {version}\nDefault isolation level: {isolation}\n")

    exp_unsafe_check_then_insert(admin)
    exp_safe_unique_and_outbox(admin)
    exp_conflicting_versions(admin)
    exp_rollback_atomicity(admin)
    exp_tenant_scope(admin)
    exp_lost_update(admin)
    admin.close()

    failed = [c for c in CHECKS if c["result"] != "PASS"]
    out = {
        "verification_scope": "single PostgreSQL instance; concurrent connections; no external provider",
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "postgres_version": version,
        "default_isolation_level": isolation,
        "psycopg_version": psycopg.__version__,
        "checks": CHECKS,
        "all_passed": not failed,
    }
    (ROOT / "lab" / "results.json").write_text(json.dumps(out, indent=2))
    print(f"\n{'ALL CHECKS PASSED' if not failed else str(len(failed)) + ' CHECK(S) FAILED'}"
          f" ({len(CHECKS)} total). Results written to lab/results.json")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
