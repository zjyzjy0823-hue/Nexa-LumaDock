# Nexa v0.5.8 Conflict Center

## Baseline audit

Development starts from `codex/v0.5.7-background-sync` at
`a7efeec1b8ff9e2645864ea5de0419165eee9f89`, with a clean working tree.
The local development branch is `codex/v0.5.8-conflict-center`.
Protocol remains v2; Alembic remains `0015_agent_data_actions`; queue/bootstrap
generation remains 2. The product version sources were consistently 0.5.7.
OpenClaw's independent plugin version remains 0.1.0.

The baseline conflict owner is a frozen `LocalMutation`, with
`conflict_json = {currentRevision, current, deleted}`. An optional pending tail
depends on its mutation ID. The business row retains the newest Local edit.
Push acknowledgement detects conflicts; pull refreshes their authoritative
snapshots without replacing Local data. Core already enforces exact
`baseRevision`, ownership, mutation replay, authoritative revisions and tombstones.

## Resolution contract

Conflict resolution is a Local operation requiring the authenticated personal
workspace owner. It uses the existing adapter registry and synchronization lock.
No credential, network request, force-write, timestamp winner or automatic merge
is involved in choosing a side.

Detection now adds a Local-only `detectedAt` to `conflict_json`, preserving it
when pull refreshes the remote snapshot. Legacy snapshots remain valid with an
existing timestamp fallback. No Protocol v2 wire fields change.

- `GET /api/v1/sync/conflicts` lists unresolved conflicts.
- `GET /api/v1/sync/conflicts/{id}` reads the latest Local business version and
  stored authoritative Core snapshot.
- `POST /api/v1/sync/conflicts/{id}/resolve` accepts `strategy: local | remote`
  and optional `expectedRemoteRevision`. The UI supplies the displayed revision.

Keep Local discards the superseded owner/tail relationship and queues one new
mutation from the **current business row**, including later Local edits. Its
`baseRevision` is the explicitly selected remote revision. The commit wakes
Background Auto Sync. If Core has since changed, ordinary Protocol v2 concurrency
checks produce a new conflict; the client never silently rebases that choice.

Keep Remote validates and applies the stored authoritative snapshot or tombstone,
sets `sync_revision`, and discards every live mutation for the same entity. It
does not enqueue an outgoing mutation or advance the workspace pull cursor.
Later Core history still arrives through the existing ordered pull stream.
Missing parent dependencies return a controlled error and roll back the operation.

The former conflict owner becomes a `resolved` receipt in the existing queue
table. Its business payload and remote snapshot are removed; retained metadata
records entity identity, strategy, selected revision, result, timestamp and fresh
mutation ID. The receipt supports retrying the same request after response loss;
choosing another strategy for that ID returns a controlled conflict. Resolved
receipts are excluded from active queue, parent readiness and predecessor checks.
No migration or historical migration edit is needed.

Ordinary Local business writes acquire a database writer gate in shared
`publisher.prepare_write` before reading business rows. Cached synchronized rows
are refreshed after the gate; auth and Agent audit objects remain loaded. This
prevents concurrent patches from replaying untouched pre-resolution attributes
after a Keep Remote decision. The Core publisher and desktop lifecycle are unchanged.

Edit versus remote delete supports an explicit Local restore using the delete
revision as its upsert base. Local delete versus remote edit supports either a
new delete based on the remote revision or restoring the remote entity locally.
Remote absence at revision zero also hides the Local entity without a push.

Resolution returns a durable decision receipt, not a claim that the subsequent
Core push has completed. Old receipt replay cannot remove a newly detected race
conflict. A busy sync engine returns controlled `409`; the user may try again.

## User interface

Settings → Sync opens Conflict Center from the conflict count or attention entry.
Six adapter entity types have readable fields. Differing values are highlighted;
deleted versions are explicit. Data record JSON is available in a collapsed
formatted view. Both choices require confirmation, including the warning that
Keep Remote abandons later Local edits. A changed snapshot requires a fresh
review and confirmation. Resolution refreshes the conflict list and sync status.

## Validation boundary

Implementation validation and release validation are separate. This version
does not require a macOS physical build. Shared Backend and frontend code remain
platform neutral; no desktop lifecycle change is required.

macOS physical validation: **deferred**. Real Windows ↔ Core ↔ Mac final device
acceptance: **not verified**. Automated source/frozen process tests do not replace
that physical release gate. Do not label this implementation cross-platform
release ready.

## Verification record

Final product sources are aligned to **0.5.8** across package/lock, Backend,
Tauri and Cargo. Independent plugin version remains **0.1.0**. Implementation
completion does not publish a release, push a branch, create a PR, merge or tag.

Local validation used Windows, Python 3.14.3, system Node 24.13.0 for frontend,
portable Node 24.16.0 for the existing OpenClaw requirement, and a disposable
PostgreSQL 16 container. No user Core database was used.

| Verification | Result |
| --- | --- |
| `npm run build`, `npm run build:desktop` | PASS |
| `npm run test:desktop` (including macOS shortcut behavior) | 5 passed |
| `npm run test:core-sync` | 30 passed: 15 existing + 15 Conflict Center |
| Backend `python -m pytest -q` | 263 passed, 1 skipped |
| Conflict Center deterministic cases within Backend | 59 passed |
| PostgreSQL smoke and 0008 → 0015 upgrade preservation | PASS |
| Original PostgreSQL sync integration, including real Node Agent tools | PASS |
| Source PostgreSQL background six-entity integration | PASS |
| Source PostgreSQL Conflict Center A/B integration | PASS |
| `npm run desktop:build:windows` | PASS; final 0.5.8 NSIS installer generated |
| Final packaged Windows sidecar smoke | PASS |
| Final packaged Windows PostgreSQL Conflict Center integration | PASS |
| Final packaged Windows PostgreSQL background/offline/restart integration | PASS |
| Windows Rust release target tests | 2 passed |
| Device client | 20 passed |
| OpenClaw Python adapter | 11 passed |
| Plugin `npm ci`, build, plugin build, validate, test (Node 24.16.0) | PASS; 13 tests |
| `python scripts/export-agent-tools.py --check` | PASS; 29 schemas |
| Actual browser + real isolated Local HTTP/SQLite | PASS |
| macOS physical validation | deferred |
| Physical Windows ↔ Core ↔ Mac final acceptance | not verified |

The Backend skip is the existing Unix desktop parent-process test on Windows.
Existing Python dependency deprecation/Pydantic warnings and the Rust linker
message remain non-failing. No new Windows-only Backend dependency was added.

Deterministic cases cover all requested API/strategy/tail/race/status/security
scenarios, all six adapters with both strategies, parent rollback and receipt
unblocking, Core absence, response replay, receipt tampering, persisted detection
time, concurrent business writers and restart persistence. Both a change learned
before the next pull and a real push-response conflict after pull preserve Local
data and require another decision.

The new PostgreSQL script uses two independent production Local processes and a
real HTTP/PostgreSQL Core; it never calls `/sync/run`. It verifies automatic Local
push and peer pull, exact resolution `baseRevision` in Core mutation history,
fresh mutation IDs, pending-tail acceptance/discard, frozen-conflict no-retry,
unresolved restart, stale resolution re-conflict, all four edit/delete choices,
owner isolation and idempotent old-receipt replay. Source and packaged runs both
verify process exit/port release and scan logs for passwords, JWT/Client secrets
and Authorization headers. The existing background integration retains its six
entity, actual Core stop, offline writes/retries, restart and convergence checks.

Browser QA used six seeded conflicts with actual Local APIs. It verified readable
amount/category/collection values, different-field highlights, Local/Core deleted
states, collapsed JSON, confirmation cancellation, Keep Remote and count 6 → 5,
stale snapshot 409 with refreshed data and required new confirmation, then Keep
Local and count 5 → 4. SQLite assertions confirmed remote amount 42 with no old
tail and latest Local record content in a fresh pending mutation with base 7.
Screenshots remain local in ignored `output/playwright/v058-*.png`.

## Known limitations

- Single-process Local scheduling/engine ownership remains the v0.5.7 constraint.
- Missing parents must be synchronized or resolved before dependent resolution.
  Validation returns a controlled error and preserves both versions.
- Broken/unknown internal conflict snapshots return a controlled error; this
  version provides no database repair interface or arbitrary JSON merge editor.
- Metadata-only resolution receipts are retained locally for audit/replay;
  retention management and an audit-history UI are outside this version.
- Keep Local while disconnected remains pending until Core can be reached.
- macOS native build/lifecycle and physical dual-device release acceptance remain
  deferred; Windows/browser/process regression is not their substitute.

Status: **V0.5.8 IMPLEMENTATION COMPLETE**. Cross-platform release readiness is
not claimed.

## Files changed

```text
.github/workflows/ci.yml
README.md
backend/app/api/sync.py
backend/app/main.py
backend/app/sync/adapters/base.py
backend/app/sync/conflicts.py
backend/app/sync/engine.py
backend/app/sync/local.py
backend/app/sync/publisher.py
backend/tests/postgres_conflict_integration.py
backend/tests/postgres_smoke.py
backend/tests/postgres_sync_integration.py
backend/tests/test_conflicts.py
backend/tests/test_desktop.py
backend/tests/test_sync_engine.py
docs/conflict-center-2026-10-03.md
docs/sync.md
package-lock.json
package.json
scripts/smoke-backend-sidecar.py
src-tauri/Cargo.lock
src-tauri/Cargo.toml
src-tauri/tauri.conf.json
src/api/sync.ts
src/components/settings/ConflictCenter.vue
src/components/settings/SyncSettings.vue
src/components/ui/Modal.vue
src/composables/useSyncConflicts.ts
src/services/conflictPresentation.ts
src/stores/data.ts
src/stores/ledger.ts
src/stores/websites.ts
tests/core-sync.test.mjs
```
