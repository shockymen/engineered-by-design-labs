# Voiding a finalized payroll run (experimental)

A follow-on lab that adds one business rule to the Chapter 12 model: **a finalized run may be voided only before any payment has been submitted**, and a voided period may get a new revision. The rule is enforced by a composite foreign key, so it holds even when application code is bypassed. This lab is a teaching example, not production payroll software. **Run only against a disposable database: the harness truncates tables.**

**Status: first run completed and passed (12/12 checks).** The frozen first attempt ran against PostgreSQL 16.16 on GitHub Actions at commit `2ea964fb0352117592f99f5ccd7193cda051033c` ([run and logs](https://github.com/shockymen/engineered-by-design-labs/actions/runs/45056431569)). The test included 100 competing void/payment trials, with zero observed violations of the tested invariant. See `agent-session/SESSION.md` for the recorded AI-agent workflow and post-run review, and `agent-session/attempt1/` for the preserved first attempt. This is an observed test result, not a proof of safety under all schedules or environments.

## Run it

Start the database from `labs/chapter-12` (`docker compose up -d --wait`), then, from this folder:

```sh
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt
python lab/void_lab.py          # writes lab/void_results.json
```

Record the terminal output and `lab/void_results.json` exactly as produced, including any failures.

## Limits

Same scope as Chapter 12: one PostgreSQL instance, concurrent connections inside one test process, default `READ COMMITTED` isolation, no external payment provider, no operating-system process crashes.
