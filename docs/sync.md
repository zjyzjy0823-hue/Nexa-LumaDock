# Nexa Sync Protocol v1

v0.5.3 Phase 2 supports `ledger.category` and `ledger.transaction` with a Core protocol and a durable Local mutation queue. It performs no network synchronization: there is no automatic push, pull, background worker, or UI sync control.

## Authority and identity

Core `/api/v1/sync/changes` and `/api/v1/sync/mutations` requests require an `nc_live_` client credential. Core derives ownership from the authenticated `Client.workspace_id`, then uses the Core workspace owner for Ledger rows. Client payloads never supply `userId`, `workspaceId`, or other ownership IDs. A Local installation must bind pulled records to its own local user and personal workspace in a later phase; Local and Core ownership IDs are independent.

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

`local_sync_state` tracks a **Local** workspace's cursor, optional remote Core URL, remote workspace and client IDs, queue seeding time, and sync diagnostics. The cursor starts at zero and Phase 2 never advances it. Remote IDs are separate from Local `workspace_id`; binding to a different Core identity raises a conflict without resetting the cursor. Connection metadata and credentials stay outside this table. Disconnecting or revoking a Core Client does not remove the Local queue.

`local_mutation_queue` is a durable intent log, distinct from Core's processed `sync_mutations`. Each `(local workspace, entity type, entity ID)` has at most one queue row, with a client-generated `mutation_id`, `base_revision`, full Protocol v1 business payload, and `pending` status. On Local create, `base_revision=0`. On an edit to a previously confirmed row, it is the row's current `sync_revision`. Later offline edits replace the payload while retaining that base revision and mutation ID. A conflict or attempted send requires a fresh mutation ID before a new intent is recorded; reusing the old ID would replay Core's stored result. Phase 2 does not send any mutation, so ordinary writes have zero attempts.

Deleting a confirmed row compacts its pending upsert into a delete, preserving the unsent mutation ID and base revision. Deleting a never-confirmed row removes its pending upsert and keeps a hidden Local tombstone; it does not send a delete with base revision zero. Deleting an unsynced category first clears that category from active unsynced transactions and refreshes their pending payloads. A synced transaction referencing an unsynced category causes a controlled conflict. Deleting a confirmed category keeps historical transaction references.

On first Local Ledger API use, active revision-zero categories and transactions are scanned once and queued as upserts, categories first. Revision-zero tombstones are skipped. Repeating the seed service is safe. `GET /api/v1/sync/status` is Local-only and user-scoped; it returns pending/conflict counts, cursor, seeding state, and last success time without credentials. Local Ledger writes and seeding do not access Core, credentials, or the network. Phase 3 will use the queue in dependency order: category upsert, transaction upsert, transaction delete, category delete. Phase 3 will own push, pull, remote application, and cursor advancement.
