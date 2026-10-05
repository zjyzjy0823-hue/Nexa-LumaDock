# Nexa v0.5.7 Background Auto Sync

Synchronization belongs to the Local Backend. A business write commits its row
and durable outbox to SQLite before it requests background work. Core availability
does not affect local write success, and no Vue timer invokes the sync engine.
Only the existing Protocol v2 `run_sync_cycle` performs push, pull, revision,
replay and conflict work. Alembic remains `0015_agent_data_actions`; queue/bootstrap
generation remains 2. No migration is required for in-memory scheduler timing.

## Scheduling and lifecycle

FastAPI's Local lifespan starts one coordinator after migrations and stops it on
shutdown. Core mode does not start a coordinator. The production Desktop entry
uses one Uvicorn worker; multiple Local workers are unsupported because the
existing engine's workspace lock and scheduler are process-local.

Saved connections receive an initial attempt after 1 second. Connecting enables
the scheduler and requests an initial attempt; disconnecting disables it and
preserves business data, identity, queue, cursor, revisions and conflict snapshots.
Committed business mutations wake the scheduler with a 0.5-second debounce and
a 2-second maximum debounce. Normal periodic pull runs every 30 seconds, including
when the Sync settings page or main window is closed.

Retryable `unreachable` and `timeout` failures use 5, 10, 20, 30 and then 60 seconds.
HTTP 502/503/504 map to `unreachable`. Success resets the backoff. Local writes
wake the scheduler without defeating an active offline retry floor. Credential,
protocol, binding and invalid-response failures require user attention instead
of indefinite retries. Manual sync joins the same active cycle or explicitly
requests the same engine. New writes during a cycle retain a follow-up request.

Central timing overrides, primarily useful for isolated integration tests, are
`NEXA_SYNC_INITIAL_DELAY_SECONDS`, `NEXA_SYNC_DEBOUNCE_SECONDS`,
`NEXA_SYNC_PERIOD_SECONDS` and `NEXA_SYNC_RETRY_SECONDS` (a comma-separated list).
Unset variables use the defaults above.

Windows close-to-tray and macOS close-main-window hide the window and keep the
sidecar alive. Windows Tray Exit, macOS Tray Exit and Cmd+Q write
`backend.shutdown`. The Backend stops scheduling new work, signals cooperative
cancellation to active engine work and joins it after the bounded current HTTP
request. Tauri waits for the owned sidecar's termination event for up to 20 seconds
before its existing process-kill fallback. It no longer treats an unavailable
health endpoint as proof that lifespan cleanup finished. macOS additionally
retains the existing parent-PID watcher. No new process or daemon is created.

The existing transport retains TLS verification, no redirects, no environment
proxy and bounded timeouts. Status exposes safe allowlisted codes and scheduler
timestamps, never credentials or raw exceptions. Sync conflicts remain persisted
for later user handling; this version does not merge or resolve conflicts.

## Automated PostgreSQL regression

Use an isolated PostgreSQL 16 database with permission to create a temporary
database for the upgrade regression. Do not point these scripts at a user's Core
database. Set `NEXA_MODE=core`, `DATABASE_URL=postgresql+psycopg://...`,
`JWT_SECRET` to a temporary secret, and `ALLOW_REGISTRATION=true`, then run from
`backend`:

```text
python -m alembic -c alembic.ini upgrade head
python tests/postgres_smoke.py
python tests/postgres_upgrade_smoke.py
python tests/postgres_sync_integration.py
python tests/postgres_background_sync_integration.py
```

The original integration requires the built OpenClaw plugin and a supported Node
runtime. The new background integration uses actual Core HTTP/PostgreSQL and two
actual Local source sidecar processes with separate SQLite files, connection
stores, installation identities and JWT secrets. It never calls `/sync/run` and
does not open a frontend. It covers:

- All six entities: A writes, A uploads automatically and B periodically pulls;
  B writes and A receives in the reverse direction.
- Actual Core process shutdown; both Local replicas can still create Ledger,
  Website and Data objects, retain their pending queues and retry.
- Restarting a Local process while Core is unavailable preserves installation,
  secret, mutation IDs, payloads and cursor and resumes background attempts.
- Restarting Core on the same port recovers both replicas automatically with
  zero pending/in-flight entries, stable UUIDs, exactly one row per entity,
  matching authoritative revisions and durable converged cursors.
- A second Local restart after recovery retains its cursor. Graceful Local
  shutdown releases each test port; temporary passwords/JWTs do not enter logs.

Response-loss frozen replay and freeze-before-HTTP remain covered by the existing
deterministic engine regressions; stopping Core before its preflight request does
not claim to simulate a committed mutation response loss.

The script shortens test timings to 0.2-second initial delay, 0.1-second debounce,
1-second periodic sync and 0.5/1/2-second retries; production defaults are
unchanged. CI runs it in the existing `backend-postgres` job, after the original
regressions. Coordinator deterministic tests remain in the existing Backend job.

After building a native sidecar, set `NEXA_BACKGROUND_SIDECAR` to its absolute
executable path and rerun `postgres_background_sync_integration.py` with the same
isolated PostgreSQL environment. Both Local replicas then execute that packaged
binary instead of source Python; Core still runs the production source backend.
This repeats the background/offline/restart/cleanup assertions through the frozen
runtime and detects missing bundled modules or lifecycle differences. Clear the
variable afterward to return to the ordinary source integration.

## Desktop and physical release gate

Windows packaged regression uses:

```text
npm run desktop:build:windows
python scripts/smoke-backend-sidecar.py --target x86_64-pc-windows-msvc
cargo test --manifest-path src-tauri/Cargo.toml --release --target x86_64-pc-windows-msvc
```

On Intel macOS, build and smoke the same source with native Intel Python and
`x86_64-apple-darwin`. Verify close-main-window keeps Backend synchronization
alive, Cmd+Q/Tray Exit stops the sidecar and releases 17800, and restart resumes
pending work. Windows regression cannot substitute for physical macOS testing.

Before release, validate real Windows Local ↔ real Core PostgreSQL ↔ real Mac
Local: Windows creates Ledger and it appears on Mac without clicking Sync; Mac
creates Website and it appears on Windows; stop Core while both devices continue
local Ledger/Website/Data writes; restore Core and wait for both queues to drain
and both devices to converge. Also test close-to-tray/window closure, application
restart with pending changes, and explicit application exit on each platform.

Automated HTTP subprocess regression is not physical multi-device E2E. Until the
real Windows/Mac gate is completed, the implementation must not be labeled
`V0.5.7 RELEASE READY`.

## Local verification record

Final product version `0.5.7` was tested on Windows against a disposable
PostgreSQL 16 container, separate from the existing user's Core database. The
container and its test database were removed after verification. Python was
3.14.3; the original Agent tool integration used portable Node 24.16.0. Existing
Python dependency warnings did not prevent the regressions from passing.

| Actual verification | Result |
| --- | --- |
| PostgreSQL schema, ownership/isolation, legacy seeding and concurrent revisions | PASS |
| PostgreSQL 0008 → 0015 upgrade and retained business/Client/sync history | PASS |
| Original real Node Agent tools → Local HTTP/SQLite → manual sync → PostgreSQL → other replica, including offline recovery and revocation | PASS |
| Background-only source Local A/SQLite ↔ Core/PostgreSQL ↔ Local B/SQLite | PASS |
| Background-only packaged Windows sidecar A/SQLite ↔ Core/PostgreSQL ↔ packaged sidecar B/SQLite | PASS |
| Both background runs: six entity types, exact business values/references, Core stop, offline writes/retries, Local restart with pending queue, automatic recovery, stable IDs/revisions/cursors | PASS |
| Both background runs: normal Local exit code 0, released test ports and password/JWT/Client credential/Authorization log scan | PASS |
| Physical Windows ↔ Core ↔ Mac background sync and current macOS desktop regression | NOT VERIFIED |

The packaged run executes the final `nexa-backend-x86_64-pc-windows-msvc.exe`;
it is a real frozen-runtime integration rather than a source-only unit test.
No remote CI run, push, pull request, tag or release was performed by these local
verification steps.
