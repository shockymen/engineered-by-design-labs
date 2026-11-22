# Evidence provenance

The reference results in this folder were supplied by the author from a local run (macOS with a Docker PostgreSQL 16.16 container) on November 21-22, 2026.

- **Python:** PostgreSQL 16.16, `READ COMMITTED`, psycopg 3.3.9; 8 of 8 checks reported PASS (`results_user_supplied.json`).
- **TypeScript:** 3 of 3 scenarios reported PASS against the same lab database. `typescript_console_user_supplied.txt` is a condensed copy of the console output the author pasted (blank lines and prompt lines removed). Node.js and PostgreSQL versions were not recorded for this run.
- **Not independently replicated.** Each push to this repository runs both suites in GitHub Actions; those runs are the independent check. Re-run the tests on your own system and report the environment and results.

## Script revision

The Python result was produced by the original revision of `lab/pg_concurrency_lab.py`. The version in this repository adds worker-error counting to three checks, a longer barrier timeout (45 seconds) and a `verification_scope` field in the output. The check scenarios are otherwise unchanged. A re-run with the shipped script is pending. When it is done, replace the files in this folder and update this note.

## Expected demonstrations of unsafe behavior

One check is deliberately expected to **demonstrate duplicates** in unsafe code, and another to show lost updates. A PASS means the bad behavior was reproduced as intended, not that the unsafe design is acceptable.

## AI assistance

The lab code and documentation were drafted with AI assistance, including Claude (Anthropic), and were edited and run by the author.
