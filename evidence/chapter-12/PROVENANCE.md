# Evidence provenance

The reference results in this folder were supplied by the author from a local run (macOS with a Docker PostgreSQL 16.16 container) on November 21-22, 2026.

- **Python:** PostgreSQL 16.16, `READ COMMITTED`, psycopg 3.3.9; 8 of 8 checks reported PASS (`results_user_supplied.json`).
- **TypeScript:** 3 of 3 scenarios reported PASS against the same lab database. `typescript_console_user_supplied.txt` is a condensed copy of the console output the author pasted (blank lines and prompt lines removed). Node.js and PostgreSQL versions were not recorded for this run.
- **Independently rerun in CI.** The baseline Python and TypeScript tests both completed successfully in GitHub Actions at commit `2ea964fb0352117592f99f5ccd7193cda051033c` ([run](https://github.com/shockymen/engineered-by-design-labs/actions/runs/45056431569)). The archived author-supplied files remain historical evidence of the earlier macOS run; the CI results establish successful execution of the repository's shipped revision. Re-run locally if you want to test another environment.

## Script revision

The Python result was produced by the original revision of `lab/pg_concurrency_lab.py`. The version in this repository adds worker-error counting to three checks, a longer barrier timeout (45 seconds) and a `verification_scope` field in the output. The check scenarios are otherwise unchanged. The shipped script has since passed its CI run at the commit linked above. The earlier result file is intentionally retained with its original provenance; CI artifacts capture execution of the shipped script.

## Expected demonstrations of unsafe behavior

One check is deliberately expected to **demonstrate duplicates** in unsafe code, and another to show lost updates. A PASS means the bad behavior was reproduced as intended, not that the unsafe design is acceptable.

## AI assistance

The lab code and documentation were drafted with AI assistance, including Claude (Anthropic), and were edited and run by the author.
