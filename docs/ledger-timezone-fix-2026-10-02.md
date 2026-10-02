# Ledger timezone blocker fix — 2026-10-02

Status: **v0.5.6 TIMEZONE BLOCKER FIXED LOCALLY**

Branch: `codex/v0.5.6-macos-local-client`.
Fetched remote base: `c7f87cd21ce17860a437ab4a3e3fdec3d9a690d1`.
This change is committed locally only. Real cross-device acceptance must restart
after rebuilding the Mac client, using a new RUN_ID.

## Cause and implementation

Ledger input schemas accepted timezone-aware values without converting them to
UTC before ORM persistence. SQLite discarded the offset while retaining the
input wall-clock value. A later read interpreted that naive value as UTC, so
`2026-10-02T17:48:00+08:00` became the incorrect `17:48 UTC`.

Three field validators now reuse the existing `aware_utc` helper:

- `TransactionInput.occurred_at` covers ordinary REST and Agent create.
- `TransactionPatch.occurred_at` covers REST and Agent update, preserving schema
  handling of `None` and the business API's rejection of an explicit null.
- `TransactionData.occurredAt` covers Core Sync processing and Local remote apply.

Agent actions continue to reconstruct the ordinary business schema. The generic
Sync adapter, publisher, Local queue and ORM datetime column are unchanged.
Naive datetimes continue to mean UTC.

Migration: **NONE**. Sync Protocol: **still v2**.

## Persistence proof

REST create/get, Agent create/update, REST patch and actual Sync execution all
assert the stored business value, rather than only testing a datetime helper.

| Input | Expected persisted/output UTC value |
| --- | --- |
| `2026-10-02T17:48:00+08:00` | `2026-10-02T09:48:00+00:00` |
| `2026-10-02T05:48:00-04:00` | `2026-10-02T09:48:00+00:00` |
| `2026-10-02T09:48:00Z` | `2026-10-02T09:48:00+00:00` |
| `2026-10-02T09:48:00` | `2026-10-02T09:48:00+00:00` |

SQLite rows contain the UTC wall-clock `2026-10-02 09:48:00`; assertions do not
depend on SQLite retaining tzinfo. Local outbox snapshots contain the UTC ISO
value. The existing Agent replay test additionally verifies that
`2026-09-30T09:00:00+08:00` persists and publishes as `01:00 UTC`.

The Sync regression sends a nonzero-offset mutation through Core processing and
an equivalent negative-offset snapshot through Local remote apply. Local A,
Core and Local B all persist the same UTC instant.

The PostgreSQL integration uses a separate disposable PostgreSQL 16 database,
real Core HTTP, two independent Local SQLite replicas and the real Node Agent
Tool. REST create, negative-offset patch and Agent create all preserve
`09:48 UTC` through manual sync. CRUD, conflict, offline recovery and revoke regression
also pass. The test database reaches migration `0015_agent_data_actions` using
existing migrations. The user's live Core and Local databases are untouched.

## Verification on Windows

| Check | Result |
| --- | --- |
| Focused timezone tests plus strengthened Agent cases | 13 passed |
| Full backend suite | 166 passed, 1 skipped; previous baseline 155 passed, 1 skipped |
| Device client | 20 passed |
| OpenClaw Runtime adapter | 11 passed |
| OpenClaw Plugin build, metadata and official validator | PASS |
| OpenClaw Plugin tests | 13 passed |
| Static Agent tool schema drift | PASS, 29 schemas |
| Root and Plugin `npm ci` | PASS, zero reported vulnerabilities |
| Frontend `build` and `build:desktop` | PASS |
| Desktop frontend tests | 5 passed |
| Core sync frontend tests | 6 passed |
| Windows `desktop:build` | PASS, v0.5.6 NSIS installer produced |
| Packaged backend sidecar smoke | PASS |
| PostgreSQL sync integration | PASS |

The one backend skip is the existing Unix process-ownership check on Windows.
The packaged sidecar smoke covers Agent scopes/create/replay/audit, offline
outbox, tombstones, persistence and login.

## Historical data and acceptance follow-up

Existing rows that already lost their original timezone offset cannot be safely auto-corrected.

No historical rows are rewritten. It is impossible to infer whether an old
naive row originally came from +08:00, another offset or an intentional UTC
input.

The known unsynced Mac QA entity is untouched during this code fix:

- Description: `E2E-MAC-20261002-151001-COFFEE`
- Entity: `5d7bcb9a-5704-4922-a2a2-2d20b3bb4adc`

After a fresh Mac build, the acceptance flow must delete this QA entity through
normal Nexa UI or a business API and verify that its corresponding pending
mutation will not push. Do not use SQL DELETE. Then restart the complete real
Mac ↔ Core ↔ Windows acceptance with a new RUN_ID, including offline recovery
and connection persistence. These regressions and builds do not complete that
cross-device acceptance.
