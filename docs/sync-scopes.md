# Sync scopes — v0.5.9

Not every persistent row is syncable. Sync uses an allowlist, never a denylist.

| Resource | Scope | Sync |
| --- | --- | --- |
| Ledger, Website, Data (six adapters) | Workspace | Yes |
| User preferences | Personal user/workspace | Yes |
| Dashboard layout | Personal user/workspace | Yes |
| Automation definition | Workspace | Yes |
| Device identity, installation.id | Device | No |
| Device metrics, Agent bindings | Device/runtime | No |
| Agent definition | Outside this version | No |
| Automation executions, jobs, locks, leases, retry state | Runtime | No |
| Core connection, client credential, Agent/Device tokens, JWT, secret.key | Secret/device | No |
| Filesystem paths, ports, process data, native window geometry | Device | No |

Preferences synchronize existing theme, language, timezone, appearance choices,
and notification event/channel booleans. There is no currency preference in the
current product. Sync/security sections of settings_json remain local. Replica
application merges only the allowed sections, preserving local connection state.
Settings import/export is a local backup schema, distinct from the sync schema;
export permission never grants sync permission.

Preferences and Dashboard retain local numeric database primary keys. Their wire
identity is a deterministic UUID per entity kind, scoped by the authenticated
workspace. The adapter resolves it within that workspace, never by a local user
number. Different workspaces may use the same singleton wire key; their business
rows and revisions are isolated. Arbitrary singleton IDs and deletes are rejected.
Reset is an upsert of defaults.

Dashboard positions/sizes are design units on the existing fixed 1284 reference
canvas, scaled by useWidgetLayout to each viewport. They are not native screen
coordinates, window dimensions or OS scale. Mobile uses the existing responsive
renderer. Only system widget keys/types and supported configuration are published;
datasources are reconstructed from the built-in catalog, never copied as arbitrary
URLs. Visibility is represented by membership in the widget list. Order is the
list order; placement and size retain the existing reference-canvas semantics.

Automation keeps its UUID through creation, edits, deletion and restoration.
Only name, description, enabled, trigger type, supported trigger configuration,
and builder nodes are synchronized. Arbitrary runtime/action blobs, credentials,
paths and device bindings are excluded. enabled=true is definition configuration,
not an assertion that any device schedules execution. Execution ownership and a
real scheduler belong to v0.6.0. This release retains simulated test-run only.

JSON payloads use schemaVersion=1, with strict nested schemas and conservative
text validation. Unknown versions/fields are rejected without echoing input.
Publication remains in the ordinary business transaction: Local outbox or Core
revision/change, followed by the existing after-commit coordinator wakeup.
Conflict decisions reuse entity-level Keep Local/Keep Remote and stale revision
protection. No field merge is performed.

Generation 3 adopts only new active revision-zero personal rows. It does not
reset the cursor, replay generations 1/2, remove queued changes or conflicts.
Unedited built-in singleton defaults are not bootstrap mutations: opening a page
is not a user edit. Explicit saves, including reset-to-default, always publish.
This avoids fabricating first-connect conflicts from a new device's default UI.
Migration 0016 preserves rows and refuses downgrade while personal sync history
or tombstones exist. Historical migrations are immutable.

Protocol 3 is required: v0.5.8 Protocol 2 clients abort at an unknown entity and
cannot safely consume Personal State. Both endpoints reject other protocol
versions with 409 sync_protocol_mismatch before bootstrap or mutation. New Local
probes before sending/advancing, retains its queue/cursor, and exposes the existing
protocol_mismatch blocked diagnostic. Upgrade Core and every replica together;
Protocol 2/3 do not silently filter or skip changes.

macOS physical validation is deferred. Backend/Frontend remain shared and
cross-platform; this version does not claim cross-platform release readiness.
