# V0.6.0 REAL AUTOMATION ENGINE REPORT

## STATUS

V0.6.0 IMPLEMENTATION COMPLETE — local implementation and Windows gates verified.
This is not a cross-platform release-ready declaration. No push, PR, tag, release,
upload or macOS build was performed.

## BASELINE

- Repository: `D:\xiangmu\LumaDock` (Nexa-LumaDock).
- Initial branch: `codex/v0.5.9-personal-state-sync`, clean working tree.
- Initial HEAD: `3f4774203056f22a9b4a171e8384c21a38ec17dd`.
- Initial version/migration/protocol: 0.5.9 / 0016_personal_state_sync / 3.
- Implementation branch: `codex/v0.6.0-automation-engine`.
- Baseline audit reused existing definitions, simulation executions, business
  services, personal-state adapter, workspace ownership, Client enrollment,
  Core connection credential store, Agent task/receipt/event paths and Sync
  publication. No replacement sync protocol or parallel business CRUD was added.

## ARCHITECTURE

`backend/app/automation` owns schemas, scheduling, durable event dispatch,
database claims, action execution, webhook transport and Local proxying. Core
lifespan starts/stops the engine. Definitions remain normal syncable business
entities. Runtime state is durable PostgreSQL state, with SQLite compatibility
for migration and tests; Local does not start a runtime worker.

## EXECUTION AUTHORITY

verified: Core-only scheduler and worker. Enrolled Local Clients can request a
manual run and read Core history for their own workspace. Core outage returns a
controlled unavailable response; it never starts a Local fallback executor.
Agent task creation is authoritative on Core; the existing Adapter executes tasks.

## DEFINITION / RUNTIME SEPARATION

Definition synchronization retains the existing UUID, schemaVersion 1, generation
3 and Protocol 3. Allowed fields include validated typed action configuration.
Runtime tables, locks, credentials and receipts have no sync adapters. E2E checks
all four Local runtime tables remain empty after real Core execution. Local
`test-run` retains explicitly simulated history for compatibility only.

## DATABASE / MIGRATION

0017_automation_engine extends the existing automation_executions table and adds
automation_schedule_state, automation_action_receipts and automation_events.
Historical migrations are unchanged. Old simulation rows keep their IDs/results,
gain workspace/created-time backfills and remain simulation executions. Unique
execution identity is enforced by a database constraint, not a pre-insert check.
Downgrade refuses to discard real execution history. SQLite old-data upgrade,
fresh migrations and PostgreSQL upgrade/regression are verified.

## TRIGGER MODEL

verified: Manual, Schedule, Data Changed and Agent Task Completed. Data Changed
matches Ledger transaction, Data record or Website and optional operation.
Agent completion optionally filters a Core Agent ID. Historical unsupported
display definitions remain readable and cannot accidentally execute.

## TRIGGER INSTANCE IDENTITY

- Manual: deterministic UUID from workflow ID and caller request UUID.
- Schedule: normalized UTC scheduled point, persisted across scans/restarts.
- Data Changed: Core workspace revision event ID.
- Agent completion: stable completed task ID event.

Unique `(workspace_id, workflow_id, trigger_instance_id)` coalesces retries and
concurrent delivery. The frontend retains the request UUID after response loss.

## SCHEDULER

One-second scans lock active definitions with PostgreSQL SKIP LOCKED. Schedule
hash and next-due point persist in the database. Configuration changes recompute
the future point; action edits do not replay an already-created execution.
Disabled definitions stop automatic scheduling and cancel queued automatic runs;
deleted definitions cancel all queued runs. An explicit manual run can execute a
disabled definition, but cannot execute a tombstone.

## TIMEZONE / CATCH-UP

verified: once, daily, weekly and fixed interval, explicit IANA timezone, UTC
storage, offset-aware once/interval anchor. Weekdays use Monday=0. DST missing
wall-clock times are skipped; ambiguous times execute once with fold 0.
`catch_up_once` creates at most the latest missed point; `skip` advances missed
points, with a two-second scan grace for on-time execution. No backlog storm.

## EVENT PIPELINE

Core business writes and accepted sync changes append a durable event inside the
same transaction as the accepted revision. Bootstrap and replica pull do not
emit events. Task completion emits only after Core accepts completed status.
Event dispatch marking and execution creation commit together. Origin,
origin_execution_id and ancestry propagate through internal and Agent actions.

## EXECUTION MODEL

States: queued, claimed, running, succeeded, failed, skipped, cancelled; legacy
success denotes simulation. Each real run freezes action/trigger configuration,
definition revision and ancestry. Attempts, lease, retry time, timestamps, safe
error code and safe result identity remain auditable after restart.

## WORKER CLAIM / LEASE

verified on real PostgreSQL: SKIP LOCKED claims, 90-second lease, worker UUID and
attempt fencing, concurrent schedulers/claimers, expired lease takeover and
locked-running-row exclusion. Workspace is locked before execution for business
lock ordering. A stale worker cannot finalize a successor attempt. Action and
receipt run while the execution row remains locked.

## CRASH RECOVERY

Durable queued work resumes after Core restart. Expired claimed/running work is
reclaimed. Internal side effect and receipt commit together; a crash after that
commit returns the receipt without creating a second Ledger row, Data row or
Agent task. A committed receipt can finalize even after disable/delete or the
last allowed attempt. Both injected response-loss recovery and actual Core
process kill/restart are verified.

## ACTION EXECUTOR

One typed DO action per definition. Reuses business services with exact workspace
ownership and safe error translation. No shell, arbitrary Python, workflow DSL,
dynamic templating or user-supplied executable code.

## LEDGER ACTION

verified: create transaction using existing Ledger validation/publication,
decimal amount and explicit transaction timestamp. Transaction and action receipt
are atomic. Summary contains entity type and ID only.

## DATA ACTION

verified: create and update through existing Data services; omitted patch fields
remain omitted. Collection/record ownership is enforced in the execution workspace.
Changes publish through ordinary Sync and produce bounded downstream events.

## AGENT ACTION

verified: reusable task creation through existing Agent permissions and workspace
scope, durable task ID receipt, actual OpenClaw Adapter deterministic executor,
Core completion event and follow-up Data update. Gateway/model-provider live
execution is deferred / not verified. Plugin version remains 0.1.0.

## WEBHOOK ACTION

verified: JSON POST to public HTTPS port 443, bounded DNS/connect/read/deadline,
TLS hostname verification, pinned validated DNS address, no redirect following,
64 KiB response limit, safe status-only summary and stable Idempotency-Key.
Unsafe literal/DNS destinations, mixed answers, mapped IPv6, credentials,
unsupported headers and header injection are rejected. Real local TLS fixture
tests exercise the production HTTPS connection and committed-receipt replay;
only fixture DNS/trust/port are injected. Production SSRF rejection is tested
separately. Public external service delivery is deferred / not verified.

## IDEMPOTENCY

verified: database trigger uniqueness and transactional internal action receipts.
Successful Webhook receipts avoid resending after local receipt commit. Delivery
is at least once: a remote acceptance followed by lost response/receipt can resend
the same Idempotency-Key. External exactly-once requires receiver cooperation;
this implementation does not claim it.

## RETRY / BACKOFF

Five maximum attempts. Retry waits are 5, 15, 30 and 60 seconds before attempts
2–5; the backoff table is capped at 300 seconds. Retryable network/DNS errors,
429/502/503/504 and temporarily unavailable Agent execution are distinguished
from invalid configuration, missing entity, permission failure, redirect and
oversize response. Attempt exhaustion terminates with a safe error. verified.

## LOOP PROTECTION

verified: self-loop, A→B→A cross-loop, maximum depth 8 and a valid bounded chain.
Ancestry tracks automation IDs through Data/Ledger and Agent task receipts.
Rejected downstream runs are persisted as skipped/loop_guard for audit.

## AUTOMATION API

Definition CRUD keeps the existing API. Added run, runtime, execution detail and
authoritative history on `/api/v1/automations/{id}`; Local history opts in with
`?runtime=true`. Core Client endpoints are under `/api/v1/client/automations`.
JWT/Client credential scopes are separate; API Key, Device Token, Agent Token,
revoked Client and another workspace cannot acquire execution authority. Input
failures and Core proxy failures do not echo arbitrary payloads or secrets.

## UI

verified: simple trigger/action forms, schedule/timezone/catch-up controls,
definition CRUD, enable/disable, explicit real run versus simulation, next/last
Core status, execution states, attempt count and detail. Five-second polling
cleans up on unmount and session changes. Core unavailable clears runtime
authority while definitions remain editable. Native Nexa WebView2 tested through
CDP: login, creation, real Ledger run, detail, offline edit, recovery and confirmed
delete. Modal sizing/overflow and Dashboard terminal status display were corrected.

## EXECUTION HISTORY

Core history is read through the authenticated proxy, never copied into Local
SQLite or Sync payloads. Result summaries contain generated entity/task IDs or
HTTP status; raw response bodies/tracebacks are not retained. Client history is
limited to the latest 100 rows per definition. Audit retention/pagination is a
future improvement. Completed internal actions clear nextAttemptAt.

## SECURITY

verified: existing workspace authorization, strict nested allowlists, rejection
of secret/token/password/credential fields, safe text checks, public DNS/TLS
restriction, no redirect or filesystem/shell actions, bounded Webhook response,
safe logs and safe API errors. E2E scans process logs against issued credentials.
Git whitespace and added-content secret scans pass. Fixture passwords are dummy
values; TLS private keys and enrollment credentials stay in ignored/temp files.
Arbitrary unlabelled text cannot be universally identified as a secret; users
must not place credentials in ordinary business text.

## UNIT TESTS

- Backend full suite: **355 passed, 2 skipped**; newly added old-history migration
  test subsequently passed separately (**1 passed**).
- SQLite/PostgreSQL engine + real TLS + migration suite: **34 passed, 1 skipped**.
  The skip is the SQLite parameter of the PostgreSQL-only row-lock test; the real
  PostgreSQL parameter passes.
- Frontend: Automation 4, Core Sync 33, desktop shortcuts 5 passed.
- TypeScript/Vite production and desktop builds passed; npm ci passed.
- Rust release tests: 2 passed.

## POSTGRES MULTI-WORKER TESTS

verified on disposable PostgreSQL 16: concurrent schedule scans produce one
execution, parallel claims distribute work, locked expired work is fenced,
receipt recovery works across attempts, loop guards and schedule persistence
work with real database transactions. SQLite is not used as evidence for locks.

## AUTOMATION E2E

verified source and packaged Local replicas against Core/PostgreSQL: A offline
write→background sync→Core event→Ledger action; B pull causes no second run;
shared authoritative history; duplicate manual request; Data create/update;
Agent→real Adapter→completed event→Data; scheduled queue→Core killed→restart→one
side effect; offline editing/recovery; all Local runtime tables empty.

## WINDOWS PACKAGED E2E

verified: actual final Nexa.exe/packaged backend, native WebView2 UI, automatic
backend start, persisted login/database, Core proxy runtime, sidecar smoke,
packaged Automation E2E and packaged background/conflict/personal-state sync.
NSIS build passed: `Nexa_0.6.0_x64-setup.exe`, approximately 41.70 MiB. Installer
wizard installation/uninstallation and another Windows machine are deferred /
not verified. Build once encountered a running QA executable file lock; closing
only task-owned processes resolved it. No installer upload occurred.

## SYNC REGRESSION

verified: PostgreSQL smoke, upgrade, six-entity sync, background sync, conflicts,
personal-state sync; Protocol 3 and generation 3 remain unchanged. Packaged
background/conflict/personal-state regressions passed. One personal-state run
returned expected concurrent `sync_in_progress`; an unmodified rerun passed.
Legacy migration expectations advanced to 0017, while the focused personal-state
0015→0016 test remains explicit. No bootstrap/runtime replication was added.

## DEVICE REGRESSION

verified: 20 Device client tests passed; backend Device authorization/runtime
tests passed in the full suite. No Device protocol, token, heartbeat or binding
behavior changed. Physical Device hardware measurement remains existing scope.

## OPENCLAW REGRESSION

verified: Python Adapter 11 tests; Plugin 13 tests, build, build:plugin and validate;
29 Agent tool exports; actual deterministic Adapter task E2E. Adapter HTTP client
now disables environment proxy inheritance for explicit Core connections after
a system proxy caused the first E2E connection to time out. Plugin 0.1.0 unchanged.
Initial default Node 24.13.0 was below OpenClaw's engine requirement; cached Node
24.16.0 was used for the successful install/build/test run.

## MACOS STATUS

deferred / not verified: no macOS build, native lifecycle/package/hardware test,
or real Windows↔Core↔Mac acceptance. Shared backend/frontend source is portable;
no cross-platform release-ready claim is made.

## KNOWN LIMITATIONS

Static validated JSON action configuration and one action per definition; targets
are entered as IDs rather than a full selector. Agent definitions do not sync, so
the ID must refer to the Core Agent. No credential-backed Webhooks, external
exactly-once guarantee, execution retention UI, unrestricted cron/DSL, distributed
broker, fleet throughput benchmark or live Gateway/provider test. Workspace
business actions serialize under a lock. Upgrade Core and all Local replicas
together for new definition fields. Local simulation history remains a separate
compatibility API; authoritative runtime history requires Core availability.

## FILES CHANGED

New: automation package (schemas/schedule/events/engine/actions/webhook/connection),
shared Agent task service, migration 0017, engine/security/TLS/upgrade tests,
PostgreSQL Automation E2E, frontend store tests and this report.
Updated: models, Core lifespan, Automation/Agent APIs, Agent business actions,
Sync service/personal adapter, frontend page/store/service/types/widget, version
sources/locks, CI, regression migration expectations, sidecar smoke, OpenClaw
Adapter proxy behavior, README, sync scope documentation and ignored QA outputs.

## GIT STATUS

Implementation committed locally on `codex/v0.6.0-automation-engine`. Working tree
checked clean after commit. No remote mutation performed. Disposable test Core,
Local processes and PostgreSQL container stopped after verification. The native
QA account and its cascading fixture rows were removed with an unchanged-source
hash fence; other native users were preserved. Screenshots and logs remain
ignored local evidence under output.

## FINAL HEAD

The exact final commit is reported in the delivery message and is obtainable with
`git rev-parse HEAD`. A commit cannot embed its own hash in its tracked contents.
