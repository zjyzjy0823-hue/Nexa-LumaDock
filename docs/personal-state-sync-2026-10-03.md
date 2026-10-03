# V0.5.9 PERSONAL STATE SYNC REPORT

## STATUS

V0.5.9 IMPLEMENTATION COMPLETE. Implementation and the checks below are verified
on Windows. macOS physical testing is deferred / not verified.

## BASELINE

Started from clean `codex/v0.5.8-conflict-center` at
`6a20db9b08638aafd363751b95b6b71babb4d7c4`: product 0.5.8, Protocol 2,
Alembic 0015, bootstrap generation 2, six business adapters. Work is on
`codex/v0.5.9-personal-state-sync`. Version files now consistently use 0.5.9;
the independently versioned OpenClaw plugin stays 0.1.0.

## SYNC SCOPE ARCHITECTURE

[sync-scopes.md](sync-scopes.md) was established before implementation. It maps
User, Workspace, Device, Runtime and Secret ownership. Typed allowlists define
cross-device payloads; persistence and settings backup formats do not grant sync
permission.

## PROTOCOL DECISION

Protocol 3 is required. Inspection of the baseline engine showed that Protocol 2
cannot safely consume unknown personal entities. Upgrade Core and every Local
replica together. Rejecting incompatible peers protects mutation queues and
cursors; no entity filtering or silent skipping was introduced.

## ENTITIES

Nine registered entities: the existing Ledger, Website and Data pairs, plus
`user.preferences`, `dashboard.layout`, `automation.definition`. New payloads
carry `schemaVersion: 1`; nested extra fields and unsupported versions are rejected.

## USER PREFERENCES

Verified ordinary API writes, Core publication, bidirectional replica sync and
workspace isolation for theme, language, timezone, supported appearance choices
and notification booleans. The current product has no currency preference.
Numeric local database keys are preserved. A deterministic singleton wire UUID
is looked up within the authenticated workspace; it never uses a local user ID.
Reset publishes defaults; arbitrary singleton IDs and deletes are rejected.
Untouched built-in defaults do not fabricate bootstrap edits or first-connect
conflicts. Core revision-zero defaults adopt the first real upsert in place.

## DASHBOARD LAYOUT

Verified stable catalog widget IDs, membership/visibility, array order, placement
and size. Coordinates are existing 1284 reference-canvas design units, rendered
by the responsive frontend; native window geometry, DPI and viewport dimensions
are excluded. Only catalog widgets are accepted. Catalog titles and datasources
are reconstructed, and arbitrary URLs/configuration never enter payloads.
There are no supported editable per-widget configuration fields in this product.
Singleton identity/reset rules match preferences.

## AUTOMATION DEFINITIONS

Verified UUID-preserving create/edit/delete/restore, name, description, enabled,
trigger type, supported label/cron configuration, and typed WHEN/IF/DO builder
nodes. Unsupported action/runtime blobs and recognizable credentials or local
paths are rejected or removed from legacy projection. Enabled is saved definition
configuration. Test-run remains simulated; execution history stays local.

## EXCLUDED DEVICE STATE

Device records/metrics, installation identity, Agent bindings, native geometry,
OS scaling, filesystem paths, process and port state are outside the adapter
registry. Device regression and serialized-payload exclusion checks passed.

## EXCLUDED RUNTIME STATE

Execution history, jobs, locks, leases, scheduler ownership and retry/runtime
state are excluded. Simulated execution history was created on A and verified
absent on B and in actual Core sync payloads.

## EXCLUDED SECRETS

Core connection/Client credential, Agent and Device tokens, JWT, secret.key,
passwords and authorization data are excluded. Preferences application preserves
local connection/security settings. No real credential literals were added.

## ADAPTER REGISTRY

Three adapters reuse the existing publisher, outbox, engine, revision, cursor,
replay and conflict machinery. Shared adapter identity/lookup hooks accommodate
numeric singleton rows without changing existing six-entity identity rules.
No new frontend mutation transport or scheduler was introduced.

## BOOTSTRAP GENERATION

Generation 3 only adopts eligible revision-zero personal state. SQLite and
PostgreSQL upgrade tests preserve generation-2 rows, revisions, pending mutation
IDs, conflict snapshots and cursor, including transaction rollback and repeat
bootstrap. Ordinary saves publish even when explicitly resetting to defaults.

## DATABASE / MIGRATION

New `0016_personal_state_sync` follows immutable 0015. Preferences gain workspace
and timestamps; all three models gain revision/tombstone metadata. Existing
numeric IDs and business/history rows survive. Downgrade refuses personal sync
history, revisions or tombstones rather than discarding them. Real PostgreSQL
0008/0013/0015 upgrade paths and SQLite 0015 upgrades passed.

## BACKGROUND SYNC

Ordinary business writes and publication share a transaction. Injected failures
verify rollback of both business data and Local outbox/Core change. Existing
after-commit coordination drives production background synchronization without
manual `/sync/run` calls in the new real A/B integration.

## CONFLICT CENTER

Verified new labels, preference comparison, dashboard component/order summaries,
automation enabled/trigger/action summaries, and folded configuration details.
Browser checks used an isolated Local with three persisted conflict fixtures;
actual confirmation and resolution endpoints reduced the count from 3 to 0.
Settings/automation refresh after decisions; dashboard reloads on its existing
refresh interval while no layout edit/save is active. Browser console had no errors.
Local screenshots are in ignored `output/playwright/v059-*-conflict.png`.

## KEEP LOCAL / KEEP REMOTE

Both strategies passed for every new entity in deterministic and real PostgreSQL
A/B tests, including pending tails and stale expected revisions. Keep Local
publishes latest local state with a fresh mutation and latest base; Keep Remote
discards the conflicting mutation and dependent tail before applying Core state.
Automation tombstone/restore cases passed. Singleton tombstones are unsupported.

## MIXED VERSION COMPATIBILITY

Verified Protocol 1/2/4 requests receive 409 from current Core before mutation or
bootstrap history. New Local's Protocol-2 probe rejection preserves cursor and
queue and reports the existing protocol mismatch diagnostic. Baseline Protocol-2
handling was audited in code; an archived v0.5.8 binary was not separately run.

## OFFLINE / RECOVERY

Verified actual Core shutdown, ordinary edits on both SQLite replicas, background
retry and automatic convergence after Core restart. New personal state and the
existing six entities passed; no manual sync or direct database copying was used
to drive the production integration scenarios.

## RESTART PERSISTENCE

Verified process restart retains personal business data, stable wire identities,
pending mutation IDs and immutable queued payloads. Conflict resolution and
generation-3 metadata survive restart. Source and packaged sidecar checks passed.

## SECURITY

Strict ownership is determined by authentication, never injected user/workspace
fields. Two authenticated Core Clients in different workspaces cannot access
each other's definitions or singleton rows, even though singleton wire keys are
shared. Tests scan actual outgoing mutations, Core changes, conflict responses,
public responses and process logs for fixture and generated credentials. Invalid
personal input returns generic 422 without echoing supplied secrets. Delivery
source scan passed; historical migrations were unchanged.

## UNIT TESTS

Verified final-version Backend: `python -m pytest -q` → **301 passed, 1 skipped**,
including 36 personal sync and two personal upgrade cases. The skipped test
requires Unix desktop process ownership and cannot run on Windows. Existing
Python 3.14 FastAPI deprecation and Pydantic alias warnings remain.
Frontend `npm ci`, `npm run build`, `npm run build:desktop` passed;
`npm run test:core-sync` → **33 passed**, `npm run test:desktop` → **5 passed**.
Windows release Rust tests → **2 passed**.

## POSTGRES INTEGRATION

Verified disposable PostgreSQL 16 with production Core HTTP and two independently
migrated SQLite Local processes. Smoke, upgrade, ordinary sync/Agent action,
six-entity background, existing conflict, and new personal-state integrations
all passed. New integration covers both directions, local-only histories,
offline/restart recovery, all three entities × both strategies, tails, stale
revision races, tombstones, ownership and credential exclusions. Temporary Core,
replicas and Docker containers were shut down after checks.

## WINDOWS PACKAGED E2E

Verified `npm run desktop:build:windows`, final 0.5.9 PyInstaller sidecar smoke,
nine-entity outbox/restart persistence and packaged A/B PostgreSQL personal,
background and conflict integrations. Installer generated locally:
`src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/Nexa_0.5.9_x64-setup.exe`.
The production packaged backend was tested; NSIS installation and native GUI
interaction were not separately automated. Nothing was uploaded or released.

## DEVICE REGRESSION

Verified Device client suite: **20 passed**. Device protocol/data remain local;
Device definitions and runtime state are not new sync entities.

## OPENCLAW REGRESSION

Verified Python adapter: **11 passed**. Plugin npm ci/build/plugin:build/validate
and test succeeded using Node 24.16.0; **13 plugin tests passed**. Generated Agent
tool export check passed for **29 tools**. Existing real Agent → Local → Core →
replica action regression passed. Plugin remains version 0.1.0.

## MACOS STATUS

Deferred / not verified: physical macOS desktop, packaged sidecar and real
two-device Windows/macOS testing. Shared Python/frontend architecture was kept;
this report does not claim cross-platform release readiness.

## KNOWN LIMITATIONS

Core and replicas require coordinated Protocol-3 upgrades. Personal singletons
use whole-entity conflict decisions, with no field merge. Layout configuration is
limited to the current catalog. Automation has no real scheduler or execution
ownership; these belong to v0.6.0. Existing dependency warnings are documented
above. Native installation/GUI and physical macOS checks are not verified.
Automatic approval policy blocked removal of the stopped browser fixture's
temporary data under the system Temp directory. It is outside the repository
and is not staged or delivered; the fixture HTTP listener is stopped.

## FILES CHANGED

Scope docs/report and README; typed personal adapters and shared identity hooks;
models/migration; ordinary settings/dashboard/automation APIs and safe validation
responses; conflict summaries and store reloads; generation/protocol/version
expectations; SQLite/PostgreSQL/packaged tests; CI integration. Historical
migrations, Device protocol and OpenClaw plugin version were preserved. Use the
delivery commit's `git show --stat` for the exact file inventory.

## GIT STATUS

Delivery is a local commit on `codex/v0.5.9-personal-state-sync`, with a clean
tracked working tree verified after commit. No push, PR, merge, tag, Release or
artifact upload was performed. Build and local QA artifacts are ignored.

## FINAL HEAD

The final delivery response records the exact `git rev-parse HEAD` after committing
this report and implementation. The immutable starting HEAD is listed in BASELINE.
