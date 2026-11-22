# Agent session record: voiding a finalized payroll run

**Status:** steps 1-3 done, step 4 (running the tests) pending. Nothing below has been run against PostgreSQL yet.

## Provenance (state this in the chapter)
- Agent: Claude (Anthropic), in a chat session with the author. Model and tool versions: record from the session before publishing.
- This is **not a clean-room session**. The agent already knew the project, the earlier lab and the chapter's thesis. The agent could not run PostgreSQL in its sandbox, so every result comes from the author's machine.
- Business decisions in step 1 were made by the human. Everything else was proposed by the agent.

## Step 1: requirements challenge
The agent asked two business questions. The human's answers:
1. When may a finalized run be voided? **Only before any payment is submitted.**
2. What happens to that tenant and period afterwards? **A new run is allowed (a new revision).**

Assumptions the agent added without being asked (the human should confirm or override):
- A void targets a run by **id**, not by tenant and period, so a retry cannot hit a newer revision.
- Repeating a void with the same reason is a no-op; a different reason is a conflict.
- A void writes a PAYROLL_VOIDED outbox event in the same transaction.
- At most one ACTIVE run per tenant and period; voided runs are kept as history.

## Step 2: competing designs for "no void once a payment exists"
| Design | How it enforces the rule | Weakness |
|---|---|---|
| A. Check, then void | Application reads "any payments?" then updates | Racy: a payment can land between the check and the update |
| B. Row lock in application code | Void and payment both `SELECT ... FOR UPDATE` the run first | Correct, but every future code path must remember to take the lock |
| C. Composite foreign key (chosen) | Payments reference `(run_id, 'ACTIVE')`; voiding changes the key, so the database refuses while payments exist, and refuses payments on a voided run | Subtle; depends on how PostgreSQL locks key updates, so it must be tested, not assumed |

Chosen: **C**, because it holds even if application code is bypassed, which is the chapter's thesis. A is kept only as a labeled control.

## Step 3: attempt 1 (frozen before any run)
Files in `attempt1/`, with checksums:
```
d438291dd097619f43da9028cfb24fe3e43c157e49de0f9c0b5ea057efd8de5f  void_schema.sql
2f60e67a80701120fd2b8077c3dbbe256fb69f63f841e91c78b20cf47cc5cf25  void_lab.py
```
Where the agent expects it could be wrong (so the tests aim there):
- the locking behavior behind design C under a real race;
- revision numbering when two re-finalizations compute the same next revision;
- `ON CONFLICT DO NOTHING` without a target catching an unintended conflict.

## Step 4: run it
```
# start PostgreSQL from labs/chapter-12:  docker compose up -d --wait
# then, from labs/chapter-12-void-run:
python lab/void_lab.py
```
Paste back the terminal output and `lab/void_results.json`. Record failures as they are.

## Step 5: after the run
Record each failure, the agent's diagnosis and fix as a diff against `attempt1/`, and the final passing results. If attempt 1 passes everything, record that too.
