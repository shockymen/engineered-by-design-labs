# Agent session record: voiding a finalized payroll run

**Status:** Steps 1–4 complete: the frozen initial implementation was executed against PostgreSQL in GitHub Actions and all 12 checks passed. The post-run assessment is recorded below; model/tool-version metadata still needs to be recovered from the original chat if available.

## Provenance (state this in the chapter)
- Agent: Claude (Anthropic), in a chat session with the author. Model and tool versions: record from the session before publishing.
- This is **not a clean-room session**. The agent already knew the project, the earlier lab and the chapter's thesis. The agent could not run PostgreSQL in its sandbox. The preserved implementation was subsequently tested by GitHub Actions against PostgreSQL; earlier local-run results belong to the separate Chapter 12 baseline.
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

## Step 4: executed run and evidence

- GitHub Actions workflow: https://github.com/shockymen/engineered-by-design-labs/actions/runs/45056431569
- Tested commit: `2ea964fb0352117592f99f5ccd7193cda051033c`
- Job: `chapter-12-void-run` — successful.
- PostgreSQL: 16.16 on GitHub-hosted Ubuntu runner; isolated database service.
- Results: **12 of 12 checks passed**. These include the deliberately unsafe control reproducing the forbidden state, 100 safe void/payment races (6 void wins, 94 payment wins, 0 violations), 16 concurrent identical voids resulting in one void event, re-finalization with preserved revision history, and database-enforced rejection of bypass attempts.
- Evidence: workflow job logs and uploaded `void-run-results` artifact for the run. Expected PostgreSQL foreign-key/check violations in the logs are intentional negative tests, not unexpected job failures.

To reproduce locally:
```
# start PostgreSQL from labs/chapter-12:  docker compose up -d --wait
# then, from labs/chapter-12-void-run:
python lab/void_lab.py
```
Record terminal output and `lab/void_results.json` exactly as produced, including any failures.

## Step 5: post-run engineering assessment

**Observed:** The first frozen agent-generated implementation passed the 12 checks without a corrective code change in this recorded execution. The database constraint rejected the unsafe payment/void combination in the tested race schedules; the negative-control test reproduced the forbidden state without the database guard.

**Decision:** Accept the design only for the narrow laboratory invariant and tested environment. Do **not** infer safety under process termination, network partitions, an external payment provider, arbitrary transaction schedules or production workloads. In particular, 100 passing races are evidence, not a mathematical proof. No correction diff was needed after the first run.

**Provenance still outstanding:** The original Claude model/version, exact tool versions and complete conversation transcript have not been published in this session record. Do not describe this as a complete agent transcript until those are supplied.
