# Chapter 12 — Concurrency, Transactions, and Financial Correctness

This companion lab is a teaching example, not production payroll software. **Run only against a disposable dedicated database: the harness resets test tables.**

## Requirements

- Docker with Compose
- Node.js 20+ and npm
- Python 3.12+ (dependencies pinned in `requirements.txt`), or Docker for Python

Tested with PostgreSQL 16.16 (Docker image `postgres:16`), psycopg 3.3.9 and Node.js 20+.

## Quick start (from this folder)

```sh
docker compose up -d --wait
npm install
npm test
```

To run the independent Python concurrency harness using Docker, without requiring Python installed on the host:

```sh
docker run --rm -v "$PWD:/work" -w /work \
  -e PG_DSN=postgresql://meridian:meridian@host.docker.internal:5433/meridian \
  python:3.12-slim sh -c 'pip install --quiet -r requirements.txt && python lab/pg_concurrency_lab.py'
```

**Note:** The Docker command above uses `host.docker.internal` on Docker Desktop (macOS/Windows). On Linux or in CI, use a local Python virtual environment and the default `localhost:5433` DSN:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python lab/pg_concurrency_lab.py
```

The Python harness writes `lab/results.json`. Keep that file for your own evidence; it is ignored by Git to avoid overwriting the archived November 2026 reference result.

### Test coverage

1. An intentionally unsafe check-then-insert operation duplicates a run under a forced race.
2. A safe conflict-aware insert creates one run and one outbox row under 32 competing requests.
3. An approval-version mismatch is reported as a conflict.
4. An injected pre-commit failure rolls back both database writes.
5. A retry after that failure creates one run and one outbox row.
6. Uniqueness applies separately to each tenant.
7. An unsafe read-modify-write loses increments.
8. `SELECT ... FOR UPDATE` preserves all 16 increments in the tested schedule.

TypeScript scenarios independently verify the concurrent finalization, approval conflict, and injected failure/retry behavior.

### Limitations

A forced exception is **not** a demonstration of an operating-system process crash. No outbox dispatcher, provider-side deduplication, partitioned network, or real payment processor is exercised. The implemented approval-version check is not proof that the underlying financial snapshot is immutable.
