#!/usr/bin/env python3
"""Agent-session lab: voiding a finalized payroll run (PostgreSQL).

    python lab/void_lab.py          # writes lab/void_results.json

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
from psycopg import errors as pgerr

DSN = os.environ.get("PG_DSN", "postgresql://meridian:meridian@localhost:5433/meridian")
ROOT = Path(__file__).resolve().parent.parent
BARRIER_TIMEOUT = 15
TRIALS = 100
PERIOD = "2026-11"
CHECKS: list[dict] = []


class InjectedFailure(Exception):
    pass


def check(name: str, ok: bool, detail: str) -> bool:
    CHECKS.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}: {name} -- {detail}")
    return ok


def connect() -> psycopg.Connection:
    return psycopg.connect(DSN)


def scalar(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def reset(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE run_outbox, payment_instructions, payroll_runs_rev, "
                    "void_ctrl_payments, void_ctrl_runs")
    conn.commit()


def run_threads(n: int, target) -> list:
    barrier = threading.Barrier(n)
    results: list = [None] * n

    def wrap(i: int) -> None:
        try:
            results[i] = target(i, barrier)
        except Exception as exc:
            results[i] = ("error", repr(exc))
            barrier.abort()

    threads = [threading.Thread(target=wrap, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# ---------------------------------------------------------------- code under test

def finalize_revision(conn, tenant_id, period, approval_version):
    """Create the next revision for (tenant, period) unless an ACTIVE run exists."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO payroll_runs_rev
                       (id, tenant_id, period, revision, approval_version, status)
                   SELECT %s, %s, %s, COALESCE(MAX(revision), 0) + 1, %s, 'ACTIVE'
                   FROM payroll_runs_rev WHERE tenant_id = %s AND period = %s
                   ON CONFLICT DO NOTHING
                   RETURNING id, revision""",
                (uuid.uuid4(), tenant_id, period, approval_version, tenant_id, period),
            )
            row = cur.fetchone()
            if row is not None:
                cur.execute(
                    "INSERT INTO run_outbox (id, run_id, event_type) "
                    "VALUES (%s, %s, 'PAYROLL_FINALIZED')", (uuid.uuid4(), row[0]))
                conn.commit()
                return ("created", row[0], row[1])
            cur.execute(
                "SELECT id, revision, approval_version FROM payroll_runs_rev "
                "WHERE tenant_id = %s AND period = %s AND status = 'ACTIVE'",
                (tenant_id, period))
            active = cur.fetchone()
        conn.commit()
        if active is None:
            raise RuntimeError("insert conflicted but no ACTIVE run found")
        if active[2] != approval_version:
            return ("conflict", active[0], active[1])
        return ("existing", active[0], active[1])
    except Exception:
        conn.rollback()
        raise


def void_run(conn, run_id, reason, fail_after_void=False):
    """Void one run by its id (not by period, so a retry cannot hit a newer revision)."""
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """UPDATE payroll_runs_rev
                       SET status = 'VOIDED', void_reason = %s, voided_at = now()
                       WHERE id = %s AND status = 'ACTIVE' RETURNING id""",
                    (reason, run_id))
            except pgerr.ForeignKeyViolation:
                conn.rollback()
                return ("payments_submitted", run_id)
            row = cur.fetchone()
            if row is not None:
                if fail_after_void:
                    raise InjectedFailure("crash before outbox insert")
                cur.execute(
                    "INSERT INTO run_outbox (id, run_id, event_type) "
                    "VALUES (%s, %s, 'PAYROLL_VOIDED')", (uuid.uuid4(), run_id))
                conn.commit()
                return ("voided", run_id)
            cur.execute("SELECT status, void_reason FROM payroll_runs_rev WHERE id = %s",
                        (run_id,))
            existing = cur.fetchone()
        conn.commit()
        if existing is None:
            return ("not_found", run_id)
        if existing[0] == "VOIDED" and existing[1] == reason:
            return ("already_voided", run_id)
        return ("conflict", run_id)
    except Exception:
        conn.rollback()
        raise


def submit_payment(conn, run_id, amount_cents=10_000):
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO payment_instructions (id, run_id, amount_cents) "
                    "VALUES (%s, %s, %s)", (uuid.uuid4(), run_id, amount_cents))
            except pgerr.ForeignKeyViolation:
                conn.rollback()
                return ("run_not_active", run_id)
        conn.commit()
        return ("submitted", run_id)
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------- experiments

def new_run(admin, version=1):
    tenant = uuid.uuid4()
    status, run_id, _ = finalize_revision(admin, tenant, PERIOD, version)
    assert status == "created"
    return tenant, run_id


def exp_control_unsafe_check_then_void(admin):
    reset(admin)
    run_id = uuid.uuid4()
    with admin.cursor() as cur:
        cur.execute("INSERT INTO void_ctrl_runs (id, status) VALUES (%s, 'ACTIVE')", (run_id,))
    admin.commit()

    def worker(i, barrier):
        conn = connect()
        try:
            with conn.cursor() as cur:
                if i == 0:  # voider: check "no payments", then void
                    cur.execute("SELECT count(*) FROM void_ctrl_payments WHERE run_id = %s", (run_id,))
                    ok = cur.fetchone()[0] == 0
                    barrier.wait(BARRIER_TIMEOUT)
                    if ok:
                        cur.execute("UPDATE void_ctrl_runs SET status = 'VOIDED' WHERE id = %s", (run_id,))
                else:       # payer: check "run active", then pay
                    cur.execute("SELECT status FROM void_ctrl_runs WHERE id = %s", (run_id,))
                    ok = cur.fetchone()[0] == "ACTIVE"
                    barrier.wait(BARRIER_TIMEOUT)
                    if ok:
                        cur.execute("INSERT INTO void_ctrl_payments (id, run_id) VALUES (%s, %s)",
                                    (uuid.uuid4(), run_id))
            conn.commit()
            return ("done",)
        finally:
            conn.close()

    run_threads(2, worker)
    status = scalar(admin, "SELECT status FROM void_ctrl_runs WHERE id = %s", (run_id,))
    pays = scalar(admin, "SELECT count(*) FROM void_ctrl_payments WHERE run_id = %s", (run_id,))
    check("CONTROL check-then-void violates R1", status == "VOIDED" and pays == 1,
          f"run status={status}, payments={pays} (the rule says these cannot both hold)")


def exp_race_void_vs_payment(admin):
    reset(admin)
    conns = [connect(), connect()]
    void_won = pay_won = bad = 0
    bad_examples = []
    try:
        for _ in range(TRIALS):
            _, run_id = new_run(admin)

            def worker(i, barrier):
                barrier.wait(BARRIER_TIMEOUT)
                if i == 0:
                    return void_run(conns[0], run_id, "duplicate upload")
                return submit_payment(conns[1], run_id)

            v, p = run_threads(2, worker)
            status = scalar(admin, "SELECT status FROM payroll_runs_rev WHERE id = %s", (run_id,))
            pays = scalar(admin, "SELECT count(*) FROM payment_instructions WHERE run_id = %s", (run_id,))
            if v[0] == "voided" and p[0] == "run_not_active" and status == "VOIDED" and pays == 0:
                void_won += 1
            elif v[0] == "payments_submitted" and p[0] == "submitted" and status == "ACTIVE" and pays == 1:
                pay_won += 1
            else:
                bad += 1
                bad_examples.append((v, p, status, pays))
    finally:
        for c in conns:
            c.close()
    check("SAFE void and payment never both succeed (R1 under race)", bad == 0,
          f"{TRIALS} trials: void won {void_won}, payment won {pay_won}, violations {bad}"
          + (f", examples {bad_examples[:2]}" if bad else ""))
    return {"void_won": void_won, "payment_won": pay_won}


def exp_void_after_payment(admin):
    reset(admin)
    _, run_id = new_run(admin)
    submit_payment(admin, run_id)
    res = void_run(admin, run_id, "late discovery")
    status = scalar(admin, "SELECT status FROM payroll_runs_rev WHERE id = %s", (run_id,))
    voided_events = scalar(admin, "SELECT count(*) FROM run_outbox WHERE event_type = 'PAYROLL_VOIDED'")
    check("Void is refused once a payment exists", res[0] == "payments_submitted"
          and status == "ACTIVE" and voided_events == 0,
          f"result={res[0]}, run status={status}, VOIDED outbox events={voided_events}")


def exp_concurrent_idempotent_void(admin):
    reset(admin)
    _, run_id = new_run(admin)
    n = 16

    def worker(i, barrier):
        conn = connect()
        try:
            barrier.wait(BARRIER_TIMEOUT)
            return void_run(conn, run_id, "duplicate upload")
        finally:
            conn.close()

    res = run_threads(n, worker)
    voided = sum(1 for r in res if r[0] == "voided")
    already = sum(1 for r in res if r[0] == "already_voided")
    errors = [r for r in res if r[0] == "error"]
    events = scalar(admin, "SELECT count(*) FROM run_outbox WHERE event_type = 'PAYROLL_VOIDED'")
    check("Concurrent identical voids are idempotent", voided == 1 and already == n - 1
          and events == 1 and not errors,
          f"{n} requests -> {voided} voided, {already} already_voided, {events} VOIDED event(s), {len(errors)} errors")

    other = void_run(admin, run_id, "a different reason")
    check("Void with a different reason is a conflict, not a silent success",
          other[0] == "conflict", f"result={other[0]}")


def exp_revision_flow(admin):
    reset(admin)
    tenant, rev1 = new_run(admin)
    void_run(admin, rev1, "wrong approval")
    status, rev2, revno = finalize_revision(admin, tenant, PERIOD, 2)
    with admin.cursor() as cur:
        cur.execute("SELECT revision, status FROM payroll_runs_rev WHERE tenant_id = %s ORDER BY revision",
                    (tenant,))
        rows = cur.fetchall()
    admin.commit()
    events = scalar(admin, "SELECT count(*) FROM run_outbox")
    check("Re-finalizing after a void creates revision 2 and keeps history",
          status == "created" and revno == 2 and rows == [(1, "VOIDED"), (2, "ACTIVE")] and events == 3,
          f"status={status}, rows={rows}, outbox events={events} (expected 3)")

    retry = void_run(admin, rev1, "wrong approval")
    still = scalar(admin, "SELECT status FROM payroll_runs_rev WHERE id = %s", (rev2,))
    check("Retrying the void of revision 1 does not touch revision 2",
          retry[0] == "already_voided" and still == "ACTIVE",
          f"retry={retry[0]}, revision 2 status={still}")

    again = finalize_revision(admin, tenant, PERIOD, 2)
    check("Finalizing while a run is ACTIVE returns the existing run",
          again[0] == "existing" and again[1] == rev2, f"result={again[0]}")


def exp_concurrent_refinalize(admin):
    reset(admin)
    tenant, rev1 = new_run(admin)
    void_run(admin, rev1, "wrong approval")
    n = 16

    def worker(i, barrier):
        conn = connect()
        try:
            barrier.wait(BARRIER_TIMEOUT)
            return finalize_revision(conn, tenant, PERIOD, 2)
        finally:
            conn.close()

    res = run_threads(n, worker)
    created = sum(1 for r in res if r[0] == "created")
    existing = sum(1 for r in res if r[0] == "existing")
    errors = [r for r in res if r[0] == "error"]
    active = scalar(admin, "SELECT count(*) FROM payroll_runs_rev WHERE tenant_id = %s AND status = 'ACTIVE'", (tenant,))
    total = scalar(admin, "SELECT count(*) FROM payroll_runs_rev WHERE tenant_id = %s", (tenant,))
    check("Concurrent re-finalize after a void yields one new ACTIVE run",
          created == 1 and existing == n - 1 and active == 1 and total == 2 and not errors,
          f"{n} requests -> {created} created, {existing} existing, {active} active, {total} total rows, {len(errors)} errors")


def exp_payment_on_voided_run(admin):
    reset(admin)
    _, run_id = new_run(admin)
    void_run(admin, run_id, "duplicate upload")
    res = submit_payment(admin, run_id)
    pays = scalar(admin, "SELECT count(*) FROM payment_instructions")
    check("Payment on a voided run is rejected", res[0] == "run_not_active" and pays == 0,
          f"result={res[0]}, payments={pays}")


def exp_void_rollback(admin):
    reset(admin)
    _, run_id = new_run(admin)
    conn = connect()
    try:
        try:
            void_run(conn, run_id, "duplicate upload", fail_after_void=True)
            raised = False
        except InjectedFailure:
            raised = True
    finally:
        conn.close()
    status = scalar(admin, "SELECT status FROM payroll_runs_rev WHERE id = %s", (run_id,))
    events = scalar(admin, "SELECT count(*) FROM run_outbox WHERE event_type = 'PAYROLL_VOIDED'")
    check("Crash during void rolls back status and outbox together",
          raised and status == "ACTIVE" and events == 0,
          f"after injected failure: status={status}, VOIDED events={events}")


def exp_bypass_application(admin):
    reset(admin)
    _, run_id = new_run(admin)
    submit_payment(admin, run_id)
    try:
        with admin.cursor() as cur:
            cur.execute("UPDATE payroll_runs_rev SET status = 'VOIDED', void_reason = 'raw sql', "
                        "voided_at = now() WHERE id = %s", (run_id,))
        admin.commit()
        raw_update = "allowed"
    except pgerr.ForeignKeyViolation:
        admin.rollback()
        raw_update = "ForeignKeyViolation"
    try:
        with admin.cursor() as cur:
            cur.execute("INSERT INTO payment_instructions (id, run_id, run_status, amount_cents) "
                        "VALUES (%s, %s, 'VOIDED', 1)", (uuid.uuid4(), run_id))
        admin.commit()
        raw_insert = "allowed"
    except (pgerr.CheckViolation, pgerr.ForeignKeyViolation) as exc:
        admin.rollback()
        raw_insert = type(exc).__name__
    check("The database enforces R1 even when application code is bypassed",
          raw_update == "ForeignKeyViolation" and raw_insert in ("CheckViolation", "ForeignKeyViolation"),
          f"raw UPDATE to VOIDED with a payment: {raw_update}; raw INSERT with run_status VOIDED: {raw_insert}")


def main() -> int:
    try:
        admin = connect()
    except psycopg.OperationalError as exc:
        print(f"Cannot connect to PostgreSQL at {DSN}\n{exc}", file=sys.stderr)
        return 2
    with admin.cursor() as cur:
        cur.execute((ROOT / "sql" / "void_schema.sql").read_text())
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        cur.execute("SHOW transaction_isolation")
        isolation = cur.fetchone()[0]
    admin.commit()
    print(f"Connected: {version}\nDefault isolation level: {isolation}\n")

    exp_control_unsafe_check_then_void(admin)
    race = exp_race_void_vs_payment(admin)
    exp_void_after_payment(admin)
    exp_concurrent_idempotent_void(admin)
    exp_revision_flow(admin)
    exp_concurrent_refinalize(admin)
    exp_payment_on_voided_run(admin)
    exp_void_rollback(admin)
    exp_bypass_application(admin)
    admin.close()

    failed = [c for c in CHECKS if c["result"] != "PASS"]
    out = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "postgres_version": version,
        "default_isolation_level": isolation,
        "psycopg_version": psycopg.__version__,
        "race_trials": TRIALS,
        "race_outcomes": race,
        "checks": CHECKS,
        "all_passed": not failed,
    }
    (ROOT / "lab" / "void_results.json").write_text(json.dumps(out, indent=2))
    print(f"\n{'ALL CHECKS PASSED' if not failed else str(len(failed)) + ' CHECK(S) FAILED'}"
          f" ({len(CHECKS)} total). Results written to lab/void_results.json")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
