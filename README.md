# Engineered by Design

**Verifiable Software Engineering with AI Coding Agents**
Edward Osafo Ohemeng

Companion engineering labs for the proposed professional book *Engineered by Design*. The book explores how engineers specify, constrain, review, and verify software built with AI coding agents.

> **Status:** Early public laboratory release. This repository is not the book manuscript, and the demonstrations are not production payroll software. All business data and examples are synthetic.

## Start here

**[Chapter 12: Concurrency, Transactions, and Financial Correctness](labs/chapter-12/README.md)**

This laboratory reproduces an unsafe payroll-finalization race, then tests the safeguards with independent PostgreSQL connections and a TypeScript reference implementation.

Reported runs from November 2026:

| Suite | Reported outcome | Evidence |
| --- | --- | --- |
| Python against PostgreSQL 16.16 | 8 of 8 checks passed | [Python result record](evidence/chapter-12/results_user_supplied.json) |
| TypeScript against PostgreSQL | 3 of 3 scenarios passed | [TypeScript console transcript](evidence/chapter-12/typescript_console_user_supplied.txt) |

**Evidence provenance:** These outputs were supplied by the author from a local Mac + Docker run. The Python result came from an earlier revision of the script than the one in this repository (details in [PROVENANCE](evidence/chapter-12/PROVENANCE.md)), and the shipped revision was subsequently executed successfully in [GitHub Actions](https://github.com/shockymen/engineered-by-design-labs/actions/runs/45056431569). GitHub Actions runs on each push are the independent check. The tests include *expected demonstrations of unsafe behavior*. A PASS does not mean an unsafe design is acceptable.

## Also in this repository

**[Voiding a finalized run (experimental)](labs/chapter-12-void-run/README.md):** a follow-on lab with a database-enforced "no void once paid" rule, plus the recorded AI-agent workflow that produced it. The frozen first attempt passed all 12 checks in [GitHub Actions](https://github.com/shockymen/engineered-by-design-labs/actions/runs/45056431569); the session record now links the observed evidence.

## Guarantees and limits

The current tests cover concurrent connections to one PostgreSQL instance at `READ COMMITTED`, conflicting approval versions, rollback after injected exceptions, retry, tenant-scoped uniqueness, and row locks. They do **not** establish safety under real multi-process terminations, network partitions, duplicate outbox deliveries, or interactions with a payment provider. See the chapter lab README for details.

## AI assistance

The lab code and documentation were drafted with AI assistance, including Claude (Anthropic), and were edited and run by the author. Treat AI-drafted code like any other untrusted contribution: run the tests yourself.

## How to contribute

Issue reports and reproducibility feedback are welcome. Pull requests are considered case by case. Please do not submit personal or proprietary payroll data, tokens, or employer code.

## License

MIT. See [LICENSE](LICENSE).

## Book manuscript

The book proposal and full unpublished manuscript are **not** included in this repository.
