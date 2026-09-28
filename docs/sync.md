# Nexa Sync Protocol v1

v0.5.3 Phase 3 provides bidirectional Local-first synchronization for `ledger.category` and `ledger.transaction`. Local Ledger writes remain available while Core is offline. Synchronization is started manually with `POST /api/v1/sync/run`; this release has no background worker or sync UI. Other product data is not synchronized.

## Authority and identity

Core `/api/v1/sync/changes` and `/api/v1/sync/mutations` requests require an `nc_live_` client credential. Core derives ownership from the authenticated `Client.workspace_id`, then uses the Core workspace owner for Ledger rows. Client payloads never supply `userId`, `workspaceId`, or other ownership IDs. Local binds pulled records to its own user and personal workspace. Local and Core ownership IDs are independent; only entity IDs, business data and Core revisions cross the network.

`CoreConnectionMetadata.schemaVersion` is unrelated to this protocol version. Requests to `POST /mutations` may include `protocolVersion: 1` (the default); both endpoints return `protocolVersion: 1`.

## Revisions and changes

Each workspace has a separate integer sequence starting at zero. Core increments it once for each accepted Ledger change and atomically writes the business row and `SyncChange`. `sync_revision` on a Ledger row records its last accepted Core revision. Preexisting rows migrate with revision zero. On the first Core changes request or mutation, Core locks the workspace and seeds active revision-zero categories first, then transactions, in `(created_at, id)` order. Each receives a real revision and upsert change; revision-zero tombstones are skipped. `initialized_at` makes this idempotent across concurrent clients. Seed order records entry into sync authority, not original creation chronology. The cursor is the last processed workspace revision, never a timestamp or database row ID. Changes and tombstones are retained without compaction.

`GET /api/v1/sync/changes?cursor=0&limit=100` returns up to 100 changes ordered by revision. The response includes `changes`, the last delivered `cursor` (or input cursor when empty), `hasMore`, and `workspaceRevision`. Clients should continue while `hasMore` is true. A cursor past that workspace's current revision returns HTTP 400. A client receives its own changes too.

An upsert change has `revision`, `entityType`, `entityId`, `operation: "upsert"`, and `data` containing only business fields. A delete change has `operation: "delete"` and `data: null`. Neither contains ownership IDs or credentials.

## Mutations

`POST /api/v1/sync/mutations` accepts `{"protocolVersion":1,"mutations":[...]}` with 1–100 entries. Each entry supplies a client generated UUID `mutationId`, stable UUID `entityId`, `entityType`, `operation` (`upsert` or `delete`), `baseRevision`, and `data` for upsert. A new ID requires `baseRevision: 0`; an existing ID requires its exact current revision. A stale write returns a per-item `conflict` with `currentRevision`, `current`, and `deleted`. There is no automatic merge or last-write-wins. One invalid entry returns `rejected` with a stable `reason` and does not roll back unrelated entries. The response has `results` in request order.

The Core records each processed `(client_id, mutationId)` result. A retry by that same Client returns the stored result without another write or revision. The same UUID from another Client is a distinct mutation. Each mutation commits independently. The workspace row and `sync_workspace_state` row are locked during revision allocation on PostgreSQL, so competing writes to one entity yield one apply and one conflict. SQLite uses the same service path.

Category `data` is `{ "name": "餐饮", "type": "expense", "icon": "shopping" }`. Transaction `data` uses `categoryId`, `type`, decimal-string `amount`, `description`, `merchant`, `note`, and `occurredAt`. Core validates active category ownership and matching transaction type. The serializers exclude record IDs, ownership IDs, database timestamps, and revision from `data`.

## Tombstones and ordinary Ledger API

Deletes keep Ledger rows with `deleted_at`. Ordinary Ledger reads and summary hide deleted rows. Core category deletion preserves transaction `category_id` and historical category names. Core ordinary Ledger writes allocate an authoritative revision and append a change, with no client origin. Local ordinary writes update the business row and a `LocalMutation` in one SQLite transaction. Local never increments `sync_revision`.

## Local transactional outbox

`local_sync_state` tracks a **Local** workspace's last fully applied Core revision, remote Core URL, remote workspace and client IDs, queue seeding time, and sync diagnostics. The cursor starts at zero and advances in the same SQLite transaction as each applied change or persistent conflict. Remote IDs are separate from Local `workspace_id`; binding to a different Core identity raises a conflict without resetting the cursor. Connection metadata and credentials stay outside this table. Disconnecting or revoking a Core Client does not remove Local Ledger, queue or cursor.

`local_mutation_queue` is a durable intent log, distinct from Core's processed `sync_mutations`. A never-sent `pending` item may compact further edits while retaining its mutation ID and base revision. Before its first HTTP attempt, Local commits `in_flight` and increments `attempt_count`. From then on its mutation ID, base revision, operation and complete Protocol v1 payload are immutable. A timeout or lost response keeps this frozen item for exact replay. Edits made meanwhile form one editable `pending` tail with a new mutation ID and `depends_on_mutation_id` pointing to the predecessor. Acknowledging an applied predecessor sets the business row's Core revision, rebases the tail, clears its dependency and removes the predecessor. It never overwrites newer local edits.

Deleting a confirmed row compacts an unsent pending upsert into a delete. Deleting a never-confirmed row removes its never-sent pending create and keeps a hidden Local tombstone. A frozen create is never canceled: a later delete becomes a dependent tail and is sent after the create is acknowledged. Deleting an unsynced category first clears that category from active unsynced transactions and refreshes their pending payloads. A synced transaction referencing an unsynced category causes a controlled conflict. Deleting a confirmed category keeps historical transaction references.

On first Local Ledger API use, active revision-zero categories and transactions are scanned once and queued as upserts, categories first. Revision-zero tombstones are skipped. Repeating the seed service is safe. Local Ledger writes and seeding do not access Core, credentials, or the network.

## Local sync cycle

`POST /api/v1/sync/run` is Local-only, user-scoped and requires the saved Core connection and `nc_live_` Client credential. A per-workspace process lock prevents concurrent cycles. The cycle binds the saved Core identity, seeds legacy Local rows, retries frozen attempts, pulls Core changes through the `hasMore` cursor pages, marks stale pending writes as conflicts, sends eligible pending mutations, pulls again and records success. Push order is category upsert, transaction upsert, transaction delete, category delete; a dependent tail waits for its predecessor. Network calls use TLS verification, no redirects, no environment proxy settings and a bounded timeout. No SQLite transaction spans an HTTP request.

An applied response removes the queue row and updates `sync_revision`; a `conflict` stores the remote revision and business state in `conflict_json` while preserving local edits and their previous `sync_revision`; a `rejected` result stores a stable reason and is not retried automatically. Timeout, connection failures and HTTP 502/503/504 keep `in_flight` for exact replay. HTTP 401 records `unauthorized` without deleting the connection, queue, Ledger or cursor. The cycle response reports status, pushed/pulled counts, pending/in-flight/conflict/rejected counts, cursor and workspace revision. `GET /api/v1/sync/status` reports the same local queue counts, cursor, seed status, last success and safe last-error code without secrets.

Changes are applied strictly in Core revision order. Local creates use the Local user and personal workspace IDs. An acknowledged change echoed back by Core is a business no-op but still advances the cursor. A newer change to an entity with unresolved local intent marks that intent `conflict` without overwriting Local data. A transaction referring to an absent Local category stops the cycle at that revision. The engine does not resolve conflicts, merge fields or synchronize other entities. Recovery after a crash replays the frozen mutation or the unapplied change from the last committed cursor.
