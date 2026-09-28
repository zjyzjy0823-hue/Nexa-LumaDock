# Nexa Sync Protocol v1

v0.5.3 Phase 1 establishes a Core protocol for `ledger.category` and `ledger.transaction`. Local mutation queues, automatic push/pull, and UI sync controls are not active.

## Authority and identity

Every `/api/v1/sync/*` request requires a Core `nc_live_` client credential. Core derives ownership from the authenticated `Client.workspace_id`, then uses the Core workspace owner for Ledger rows. Client payloads never supply `userId`, `workspaceId`, or other ownership IDs. A Local installation must bind pulled records to its own local user and personal workspace in a later phase; Local and Core ownership IDs are independent.

`CoreConnectionMetadata.schemaVersion` is unrelated to this protocol version. Requests to `POST /mutations` may include `protocolVersion: 1` (the default); both endpoints return `protocolVersion: 1`.

## Revisions and changes

Each workspace has a separate integer sequence starting at zero. Core increments it once for each accepted Ledger change and atomically writes the business row and `SyncChange`. `sync_revision` on a Ledger row records its last accepted Core revision. Preexisting rows migrate with revision zero; they are retained without invented change events. The cursor is the last processed workspace revision, never a timestamp or database row ID. Changes are retained without compaction in Phase 1.

`GET /api/v1/sync/changes?cursor=0&limit=100` returns up to 100 changes ordered by revision. The response includes `changes`, the last delivered `cursor` (or input cursor when empty), `hasMore`, and `workspaceRevision`. Clients should continue while `hasMore` is true. A cursor past that workspace's current revision returns HTTP 400. A client receives its own changes too.

An upsert change has `revision`, `entityType`, `entityId`, `operation: "upsert"`, and `data` containing only business fields. A delete change has `operation: "delete"` and `data: null`. Neither contains ownership IDs or credentials.

## Mutations

`POST /api/v1/sync/mutations` accepts `{"protocolVersion":1,"mutations":[...]}` with 1–100 entries. Each entry supplies a client generated UUID `mutationId`, stable UUID `entityId`, `entityType`, `operation` (`upsert` or `delete`), `baseRevision`, and `data` for upsert. A new ID requires `baseRevision: 0`; an existing ID requires its exact current revision. A stale write returns a per-item `conflict` with `currentRevision`, `current`, and `deleted`. There is no automatic merge or last-write-wins. One invalid entry returns `rejected` with a stable `reason` and does not roll back unrelated entries. The response has `results` in request order.

The Core records each processed `(client_id, mutationId)` result. A retry by that same Client returns the stored result without another write or revision. The same UUID from another Client is a distinct mutation. Each mutation commits independently. The workspace row and `sync_workspace_state` row are locked during revision allocation on PostgreSQL, so competing writes to one entity yield one apply and one conflict. SQLite uses the same service path.

Category `data` is `{ "name": "餐饮", "type": "expense", "icon": "shopping" }`. Transaction `data` uses `categoryId`, `type`, decimal-string `amount`, `description`, `merchant`, `note`, and `occurredAt`. Core validates active category ownership and matching transaction type. The serializers exclude record IDs, ownership IDs, database timestamps, and revision from `data`.

## Tombstones and ordinary Ledger API

Deletes keep Ledger rows with `deleted_at` and a new revision. Ordinary Ledger reads and summary hide deleted rows. Category deletion preserves transaction `category_id` and historical category names. Core ordinary Ledger writes also allocate a revision and append a change, with no client origin. Local ordinary Ledger writes remain local only and do not claim a Core revision. Phase 2 will add the Local queue and outbound mutations.
