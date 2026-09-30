# Nexa Sync Protocol v2

v0.5.3 introduced manual Ledger synchronization. v0.5.4 extends manual bidirectional Local-first synchronization to `ledger.category`, `ledger.transaction`, `website.category`, `website`, `data.collection` and `data.record`. Local writes remain available while Core is offline. Synchronization is started manually with `POST /api/v1/sync/run`; this release has no background worker or sync UI. Settings, Device, Agent, Automation and Dashboard are not synchronized.

## Authority and identity

Core `/api/v1/sync/changes` and `/api/v1/sync/mutations` requests require an `nc_live_` client credential. Core derives ownership from the authenticated `Client.workspace_id`, then uses the Core workspace owner for owned entities. DataRecord resolves ownership through its DataCollection without duplicate ownership columns. Client payloads never supply `userId`, `workspaceId`, or other ownership IDs. Local binds pulled records to its own user and personal workspace. Local and Core ownership IDs are independent; only entity IDs, business data and Core revisions cross the network.

`CoreConnectionMetadata.schemaVersion: 1` is independent and unchanged. Client and Core must both use `SYNC_PROTOCOL_VERSION = 2`. POST mutations requires JSON `protocolVersion: 2`; GET changes requires query `protocolVersion=2`. Missing versions are treated as legacy v1 and return HTTP 409 `sync_protocol_mismatch` before bootstrap, mutations or feed delivery. Responses declare v2. Local probes the remote version before freezing/replaying mutations and checks every response/page. A v2 Client using a v1 Core reports `protocol_mismatch` and preserves queue/cursor. A v1 Client using a v2 Core receives a mismatch response; its existing UI may render generic `invalid_response`, but cannot skip Website/Data revisions or advance its cursor. Upgrade both ends before resuming manual sync.

## Revisions and changes

Each workspace has a separate integer sequence starting at zero. Core increments it once for each accepted entity change and atomically writes the business row and `SyncChange`. `sync_revision` on an entity row records its last accepted Core revision. Preexisting rows migrate with revision zero. On the first v2 changes request or mutation, Core locks the workspace and adopts active revision-zero rows from unseeded adapter generations, parents before children, in `(created_at, id)` order within each adapter. Each receives a real revision and upsert change; tombstones are skipped. `bootstrap_version` makes adoption idempotent and preserves already seeded Ledger history. Seed order records entry into sync authority, not original creation chronology. The cursor is the last processed workspace revision, never a timestamp or database row ID. Changes and tombstones are retained without compaction.

`GET /api/v1/sync/changes?protocolVersion=2&cursor=0&limit=100` returns up to 100 changes ordered by revision. The response includes `changes`, the last delivered `cursor` (or input cursor when empty), `hasMore`, and `workspaceRevision`. Clients should continue while `hasMore` is true. A cursor past that workspace's current revision returns HTTP 400. A client receives its own changes too.

An upsert change has `revision`, `entityType`, `entityId`, `operation: "upsert"`, and `data` containing only business fields. A delete change has `operation: "delete"` and `data: null`. Neither contains ownership IDs or credentials.

## Mutations

`POST /api/v1/sync/mutations` accepts `{"protocolVersion":2,"mutations":[...]}` with 1–100 entries. Each entry supplies a client generated UUID `mutationId`, stable UUID `entityId`, `entityType`, `operation` (`upsert` or `delete`), `baseRevision`, and `data` for upsert. A new ID requires `baseRevision: 0`; an existing ID requires its exact current revision. A stale write returns a per-item `conflict` with `currentRevision`, `current`, and `deleted`. There is no automatic merge or last-write-wins. One invalid entry returns `rejected` with a stable `reason` and does not roll back unrelated entries. The response has `results` in request order.

The Core records each processed `(client_id, mutationId)` result. A retry by that same Client returns the stored result without another write or revision. The same UUID from another Client is a distinct mutation. Each mutation commits independently. The workspace row and `sync_workspace_state` row are locked during revision allocation on PostgreSQL, so competing writes to one entity yield one apply and one conflict. SQLite uses the same service path.

Category `data` is `{ "name": "餐饮", "type": "expense", "icon": "shopping" }`. Transaction `data` uses `categoryId`, `type`, decimal-string `amount`, `description`, `merchant`, `note`, and `occurredAt`. Core validates active category ownership and matching transaction type. All serializers exclude record IDs, ownership IDs and revisions. Ledger/Data follow existing locally managed database timestamp semantics; Website explicitly carries createdAt/updatedAt/lastVisitedAt as business timestamps.

## Tombstones and ordinary business APIs

Deletes keep synchronized rows with `deleted_at`. Ordinary reads and Ledger summary hide deleted rows; Data recordCount/records and legacy `/api/data` also hide tombstones. Core category deletion preserves transaction `category_id` and historical category names. Core ordinary Ledger/Website/Data writes allocate an authoritative revision and append a change, with no client origin. Local ordinary writes update the business row and a `LocalMutation` in one SQLite transaction. Local never increments `sync_revision`.

## Local transactional outbox

`local_sync_state` tracks a **Local** workspace's last fully applied Core revision, remote Core URL, remote workspace and client IDs, queue seeding time, and sync diagnostics. The cursor starts at zero and advances in the same SQLite transaction as each applied change or persistent conflict. Remote IDs are separate from Local `workspace_id`; binding to a different Core identity raises a conflict without resetting the cursor. Connection metadata and credentials stay outside this table. Disconnecting or revoking a Core Client does not remove Local business data, queue or cursor.

`local_mutation_queue` is a durable intent log, distinct from Core's processed `sync_mutations`. A never-sent `pending` item may compact further edits while retaining its mutation ID and base revision. Before its first HTTP attempt, Local commits `in_flight` and increments `attempt_count`. From then on its mutation ID, base revision, operation and complete Protocol v2 payload are immutable. A timeout or lost response keeps this frozen item for exact replay. Edits made meanwhile form one editable `pending` tail with a new mutation ID and `depends_on_mutation_id` pointing to the predecessor. Acknowledging an applied predecessor sets the business row's Core revision, rebases the tail, clears its dependency and removes the predecessor. It never overwrites newer local edits.

Deleting a confirmed row compacts an unsent pending upsert into a delete. Deleting a never-confirmed row removes its never-sent pending create and keeps a hidden Local tombstone. A frozen create is never canceled: a later delete becomes a dependent tail and is sent after the create is acknowledged. Deleting an unsynced category first clears that category from active unsynced transactions and refreshes their pending payloads. A synced transaction referencing an unsynced category causes a controlled conflict. Deleting a confirmed category keeps historical transaction references.

Local status, writes and sync adopt active revision-zero rows from unseeded generations, parents first. Ledger API initialization remains compatible. Revision-zero tombstones are skipped. Repeating the seed service is safe. Local writes and seeding do not access Core, credentials, or the network.

## Local sync cycle

`POST /api/v1/sync/run` is Local-only, user-scoped and requires the saved Core connection and `nc_live_` Client credential. A per-workspace process lock prevents concurrent cycles. The cycle binds the saved Core identity, seeds legacy Local rows, retries frozen attempts, pulls Core changes through the `hasMore` cursor pages, marks stale pending writes as conflicts, sends eligible pending mutations, pulls again and records success. Push priority comes from each adapter: parent upsert before child upsert, child delete before parent delete; a dependent tail waits for its predecessor. Network calls use TLS verification, no redirects, no environment proxy settings and a bounded timeout. No SQLite transaction spans an HTTP request.

An applied response removes the queue row and updates `sync_revision`; a `conflict` stores the remote revision and business state in `conflict_json` while preserving local edits and their previous `sync_revision`; a `rejected` result stores a stable reason and is not retried automatically. Timeout, connection failures and HTTP 502/503/504 keep `in_flight` for exact replay. HTTP 401 records `unauthorized` without deleting the connection, queue, Ledger or cursor. The cycle response reports status, pushed/pulled counts, pending/in-flight/conflict/rejected counts, cursor and workspace revision. `GET /api/v1/sync/status` reports the same local queue counts, cursor, seed status, last success and safe last-error code without secrets.

Changes are applied strictly in Core revision order. Local creates use the Local user and personal workspace IDs. An acknowledged change echoed back by Core is a business no-op but still advances the cursor. A newer change to an entity with unresolved local intent marks that intent `conflict` without overwriting Local data. An upsert referring to an absent Local parent stops at that revision. Website/Data require active parents. Authoritative Ledger history retains support for historical tombstoned category references. The engine does not resolve conflicts, merge fields or synchronize unregistered entities. Recovery after a crash replays the frozen mutation or the unapplied change from the last committed cursor.

An existing conflict follows later authoritative changes: `conflict_json.currentRevision`, `current`, `deleted`, and `result_revision` refresh to the latest remote state in the same transaction as cursor advancement. If a push conflict already knows a revision beyond the pull cursor, older history advances the cursor without regressing that snapshot. A remote delete sets `current: null` and `deleted: true`; a later accepted restore replaces that snapshot with the active state. Local business data and its `sync_revision` stay unchanged. If the conflict owner has a dependent pending tail, that tail remains editable and blocked, without becoming a second conflict or changing the frozen request.

## Integration verification

`backend/tests/postgres_sync_integration.py` starts a temporary localhost Core HTTP server using the PostgreSQL test database at Alembic head `0014_multi_entity_sync`. It migrates two separate Local SQLite databases, enrolls distinct Clients, saves their credentials separately, and drives their ordinary Ledger/Website/Data APIs and manual sync APIs. Sync requests use the production HTTP client and Core authentication endpoints. Coverage includes ownership mapping, create/update/delete propagation, independent-record merge, same-record conflict and snapshot refresh, ordinary Core API writes, actual Core shutdown/recovery, and credential revocation. Existing deterministic state-machine tests cover commit followed by response loss and immutable replay with later local edits.

After installing `requirements-postgres.txt`, set `DATABASE_URL` to an isolated test PostgreSQL database and `JWT_SECRET` to a temporary secret, run `python -m alembic upgrade head`, then `python tests/postgres_sync_integration.py` from `backend`. The script never contacts public services or prints credentials. CI runs it in the PostgreSQL 16 job alongside migration preservation and concurrency smoke tests.

## Adapter registry

`backend/app/sync/adapters/registry.py` provides `get_adapter(entity_type)` and `adapter_for(item)`. Unknown types return stable `unknown_entity_type`, never KeyError or silent cursor skip. `base.py` defines the small dataclass contract: entity/model/schema, field serialization/application, ownership resolution, replica creation, dependency validation, push readiness/priority, ordinary timestamp updates, delete semantics and legacy discovery. Ledger, Website and Data modules provide the six adapters.

The engine retains pending/in_flight/conflict/rejected, freeze-before-HTTP, immutable replay, attempt counts, response-loss recovery, pending tail/rebase, cursor/revision ordering, echo handling, conflict snapshots, workspace locks and network diagnostics. Adapters own business fields, parents and ownership. The Core service retains authoritative revision allocation, idempotency and history. Engine code contains no business-entity branches.

| Entity | Business fields | Parent |
| --- | --- | --- |
| ledger.category | name, type, icon | none |
| ledger.transaction | categoryId, type, decimal-string amount, description, merchant, note, occurredAt | optional LedgerCategory |
| website.category | name, order | none |
| website | name, url, icon, description, categoryId, favorite, order, lastVisitedAt, createdAt, updatedAt | optional WebsiteCategory |
| data.collection | name, description, icon, tone | none |
| data.record | collectionId, name, status, category, dataJson | required DataCollection |

Schemas forbid extra fields and retain existing API length/name/URL validation. Parent UUIDs are business identity and remain unchanged across replicas. DataRecord cannot change collections through sync, matching the ordinary API. Website timestamps use UTC ISO strings; updating sync metadata alone does not change Website.updatedAt. Website URLs and DataRecord JSON remain user business data. Rejection reasons use an allowlist, and remote conflict payloads are validated before entering diagnostics. Credentials, Authorization headers, passwords and Core JWTs are never injected by system serialization or copied from HTTP errors.

## Migration and extensible bootstrap

`0014_multi_entity_sync` follows immutable 0013. It adds BigInteger sync_revision (zero) and nullable UTC deleted_at to WebsiteCategory, Website, DataCollection and DataRecord, preserving business rows and Ledger revisions. It adds LocalSyncState.queue_seed_version and SyncWorkspaceState.bootstrap_version. Rows with existing queue_seeded_at/initialized_at become generation 1; new state begins at 0. Ledger adapters belong to generation 1, Website/Data to generation 2. Future adapters can introduce subsequent generations.

Local adopts only unseeded generations, skips existing queue entries and tombstones, and preserves cursor and frozen payloads. Core adopts only new generations under the workspace lock, allocating normal revisions and SyncChanges after existing history. Version state and adoption commit atomically; rollback/crash retries cannot duplicate queue rows, revisions or changes. Existing Ledger history is never reseeded. Downgrade refuses to discard multi-entity history or tombstones.

## Website/Data deletion and ordinary publication

Website category deletion clears category_id on every active Website and publishes each normal Website upsert before the category tombstone delete. DataCollection deletion tombstones and publishes active DataRecord deletes before the Collection delete. Core mutation deletes also handle Core children absent on the requesting replica. Local unsent create/delete cancellation retains hidden tombstones; a frozen create's delete remains a dependent tail.

Website CRUD, category CRUD and visit plus Data CRUD use `sync/publisher.py`: Local business changes and outbox are in one transaction; Core locks the workspace before reading mutable rows and writes authoritative revision/change history. Core Web/API edits therefore reach other replicas. Frequent visit updates compact pending Website payloads. Ledger uses the same generic outbox/Core services and retains established category history semantics.

## Settings boundary

UserPreference retains its integer primary key and settings_json; no Settings migration or adapter is added. Future cross-device preferences may include theme, language, timezone, notifications and appearance. Sync/security settings, Core URL, Client credential, installation id, DB path and device-specific configuration must remain Local-only. These are mixed in the current settings row, so wholesale settings_json sync would copy installation and security state. Settings, Device, Agent and Automation sync remain outside v0.5.4.

## v0.5.4 regression coverage

Existing Ledger tests remain, with HTTP fixtures declaring v2. New tests cover Registry, priorities, dependencies, payload/ownership isolation, Website/Data two-replica bidirectional sync, independent edits, same-entity conflicts/latest snapshots, cascade/tombstone reads, Website visits, immutable tails, response loss/idempotency, protocol mismatch, and ordinary Core publication. Upgrade tests migrate an already seeded 0013 database to 0014 and verify rollback/retry adoption without Ledger duplication.

PostgreSQL upgrade smoke also tests initialized 0013 → 0014 adoption on real PostgreSQL. HTTP integration includes Website/Data A → Core → B and B → Core → A, distinct ownership, visit/category detach, cascade deletes and ordinary Core writes alongside the original Ledger/offline/revoke scenarios. Deterministic transport injection verifies lost responses without flaky socket timing. Full checks include Backend pytest, Frontend build, Device/OpenClaw tests, Windows sidecar smoke and Tauri/NSIS packaging.

## v0.5.5 Agent Data Actions

Agent writes enter the same transactional Local outbox through shared business services. They never directly call Core or force connectivity/synchronization. Protocol v2 and bootstrap/queue generations remain unchanged. New migration `0015_agent_data_actions` follows 0014, defaults Agent data scopes to none, and stores local-only safe Action receipts. Agent settings/audit are not new sync entity types. See [Agent Data Actions](agent-data-actions.md).
