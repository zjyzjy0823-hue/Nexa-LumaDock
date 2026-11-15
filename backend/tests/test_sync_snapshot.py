"""Core snapshot endpoint (`GET /api/v1/sync/snapshot`) — resync P1.

The snapshot is the recovery path for a client whose `/changes` cursor is ahead of the
workspace revision: it returns full state (tombstones included) pinned to one workspace
revision, so pages cannot tear while the client is paging.
"""

from uuid import uuid4

from app.main import app
from app.runtime_mode import require_core_mode
from app.sync.adapters import get_adapter
from app.sync.protocol import SYNC_PROTOCOL_VERSION
from app.sync.snapshot import decode_cursor, decode_snapshot_id, encode_snapshot_id
from test_sync import ROOT, enroll, mutation, push, user

SNAPSHOT = ROOT + "/snapshot"

CATEGORY = {"name": "Food", "type": "expense", "icon": "shopping"}
TRANSACTION = {"categoryId": None, "type": "expense", "amount": "38.00",
               "description": "Coffee", "merchant": "", "note": "",
               "occurredAt": "2026-11-15T02:30:00Z"}
SITE_CATEGORY = {"name": "Sites", "order": 1}


def site(name="Nexa", category_id=None):
    return {"name": name, "url": "https://example.com", "icon": None, "description": "",
            "categoryId": category_id, "favorite": True, "order": 2, "lastVisitedAt": None,
            "createdAt": "2026-10-01T00:00:00Z", "updatedAt": "2026-11-15T03:00:00Z"}


def credential_for(client):
    """Core mode + enrolled client credential, the shape `/snapshot` accepts."""
    app.dependency_overrides[require_core_mode] = lambda: None
    auth = user(client, "snapshot_owner_" + uuid4().hex[:8])
    return auth, enroll(client, auth)


def seed(client, headers):
    """Eight live entities plus one tombstone, spanning six adapters and a singleton."""
    transaction = {**TRANSACTION, "categoryId": None}
    ids = {"category": str(uuid4()), "transaction": str(uuid4()),
           "site_category": str(uuid4()), "site": str(uuid4()), "dead_site": str(uuid4()),
           "collection": str(uuid4()), "record": str(uuid4()),
           "preferences": get_adapter("user.preferences").entity_id()}
    revisions = {}
    revision = 0

    def apply(key, entity_type, entity_id, data, base=0, operation="upsert"):
        nonlocal revision
        [result] = push(client, headers, mutation(entity_type, entity_id=entity_id,
                                                  base=base, operation=operation,
                                                  data=data))
        assert result["status"] == "applied", result
        revision = revisions[key] = result["revision"]
        return result

    apply("category", "ledger.category", ids["category"], CATEGORY)
    apply("transaction", "ledger.transaction", ids["transaction"],
          {**transaction, "categoryId": ids["category"]})
    apply("site_category", "website.category", ids["site_category"], SITE_CATEGORY)
    apply("site", "website", ids["site"], site(category_id=ids["site_category"]))
    apply("dead_site", "website", ids["dead_site"], site(name="Removed"))
    apply("collection", "data.collection", ids["collection"],
          {"name": "Reading", "description": "", "icon": "custom", "tone": "blue"})
    apply("record", "data.record", ids["record"],
          {"collectionId": ids["collection"], "name": "Row", "status": "active",
           "category": "", "dataJson": {"value": 42}})
    apply("preferences", "user.preferences", ids["preferences"], {"theme": "dark"})
    apply("dead_site", "website", ids["dead_site"], None,
          base=revisions["dead_site"], operation="delete")
    return ids, revisions, revision


def snapshot(client, headers, **params):
    params.setdefault("protocolVersion", SYNC_PROTOCOL_VERSION)
    response = client.get(SNAPSHOT, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def walk(client, headers, limit):
    """Follow `hasMore` to exhaustion, exactly as a client must."""
    pages, cursor, snapshot_id = [], None, None
    while True:
        params = {"limit": limit}
        if cursor is not None:
            params.update(cursor=cursor, snapshotId=snapshot_id)
        page = snapshot(client, headers, **params)
        pages.append(page)
        snapshot_id = page["snapshotId"]
        cursor = page["cursor"]
        if not page["hasMore"]:
            assert cursor is None
            return pages
        assert isinstance(cursor, str) and cursor


def test_snapshot_returns_the_whole_workspace_including_tombstones(client):
    auth, headers = credential_for(client)
    workspace_id = client.get("/api/v1/workspace", headers=auth).json()["id"]
    ids, revisions, revision = seed(client, headers)

    body = snapshot(client, headers)
    assert body["protocolVersion"] == SYNC_PROTOCOL_VERSION
    assert body["workspaceRevision"] == revision
    assert body["hasMore"] is False and body["cursor"] is None
    assert decode_snapshot_id(body["snapshotId"]) == (workspace_id, revision)

    entities = body["entities"]
    actual = {(row["entityType"], row["entityId"]) for row in entities}
    # The workspace already owns its default personal-state rows (a dashboard layout is
    # created at registration), so the seeded set is a subset of the snapshot, not equal
    # to it. Completeness is asserted by the pagination round trip below.
    assert {("ledger.category", ids["category"]), ("ledger.transaction", ids["transaction"]),
            ("website.category", ids["site_category"]), ("website", ids["site"]),
            ("website", ids["dead_site"]), ("data.collection", ids["collection"]),
            ("data.record", ids["record"]),
            ("user.preferences", ids["preferences"])} <= actual
    assert len(actual) == len(entities), "an entity must not appear twice in one snapshot"
    assert [row["entityType"] for row in entities] == sorted(
        row["entityType"] for row in entities), "pages must be ordered by entityType"
    for entity_type in {row["entityType"] for row in entities}:
        entity_ids = [row["entityId"] for row in entities if row["entityType"] == entity_type]
        assert entity_ids == sorted(entity_ids), entity_type

    by_id = {(row["entityType"], row["entityId"]): row for row in entities}
    for row in entities:
        assert set(row) == {"entityType", "entityId", "syncRevision", "deleted", "data"}
        assert 0 <= row["syncRevision"] <= body["workspaceRevision"]
        if row["deleted"]:
            assert row["data"] is None
        else:
            assert isinstance(row["data"], dict)
    website = by_id[("website", ids["site"])]
    assert website["data"]["name"] == "Nexa"
    assert website["data"]["url"] == "https://example.com"
    assert website["data"]["categoryId"] == ids["site_category"]
    assert website["syncRevision"] == revisions["site"]
    assert by_id[("ledger.transaction", ids["transaction"])]["data"]["amount"] == "38.00"

    # The tombstone is reported by identity only: no payload, no resurrection data.
    tombstone = by_id[("website", ids["dead_site"])]
    assert tombstone["deleted"] is True and tombstone["data"] is None
    assert tombstone["syncRevision"] == revision

    # Personal state keeps its UUID5-derived identity and its projected payload.
    preferences = by_id[("user.preferences", ids["preferences"])]
    assert preferences["entityId"] == get_adapter("user.preferences").entity_id()
    assert preferences["data"]["theme"] == "dark"
    assert "workspaceId" not in str(body) and "userId" not in str(body)
    assert "nc_live_" not in str(body)


def test_snapshot_pagination_of_single_entities_matches_the_full_page(client):
    _auth, headers = credential_for(client)
    seed(client, headers)
    full = snapshot(client, headers)

    pages = walk(client, headers, limit=1)
    assert len(pages) == len(full["entities"])
    assert [page["hasMore"] for page in pages] == [True] * (len(pages) - 1) + [False]
    assert all(len(page["entities"]) == 1 for page in pages)
    assert [row for page in pages for row in page["entities"]] == full["entities"]
    assert {page["workspaceRevision"] for page in pages} == {full["workspaceRevision"]}
    assert {page["snapshotId"] for page in pages} == {pages[0]["snapshotId"]}
    for page in pages[:-1]:
        assert decode_cursor(page["cursor"]) == (
            page["entities"][-1]["entityType"], page["entities"][-1]["entityId"])


def test_snapshot_pagination_is_pinned_to_the_first_revision(client):
    _auth, headers = credential_for(client)
    ids, _revisions, revision = seed(client, headers)
    full = snapshot(client, headers)
    assert full["workspaceRevision"] == revision

    first = snapshot(client, headers, limit=2)
    assert first["hasMore"] is True
    late_id = str(uuid4())
    late = push(client, headers, mutation("website", entity_id=late_id, data=site("Late")))
    assert late[0]["status"] == "applied" and late[0]["revision"] == revision + 1

    collected, cursor, snapshot_id = list(first["entities"]), first["cursor"], first["snapshotId"]
    workspace_revision = first["workspaceRevision"]
    while cursor is not None:
        page = snapshot(client, headers, limit=2, cursor=cursor, snapshotId=snapshot_id)
        assert page["snapshotId"] == snapshot_id
        assert page["workspaceRevision"] == workspace_revision == revision
        collected.extend(page["entities"])
        cursor = page["cursor"]

    assert len(collected) == len(full["entities"]), "every entity exactly once"
    assert len({(row["entityType"], row["entityId"]) for row in collected}) == len(full["entities"])
    assert ids["dead_site"] in {row["entityId"] for row in collected}
    assert late_id not in {row["entityId"] for row in collected}, "a later write tore the snapshot"
    assert all(row["syncRevision"] <= revision for row in collected)

    # A *new* snapshot is a new logical read and does see the late row.
    fresh = snapshot(client, headers)
    assert fresh["workspaceRevision"] == revision + 1
    assert fresh["snapshotId"] != snapshot_id
    assert late_id in {row["entityId"] for row in fresh["entities"]}


def test_snapshot_rejects_a_revision_outside_the_workspace_history(client):
    auth, headers = credential_for(client)
    workspace_id = client.get("/api/v1/workspace", headers=auth).json()["id"]
    _ids, _revisions, revision = seed(client, headers)
    current = snapshot(client, headers)["workspaceRevision"]
    future = encode_snapshot_id(workspace_id, current + 1)
    response = client.get(SNAPSHOT, headers=headers,
                          params={"protocolVersion": 3, "snapshotId": future})
    assert response.status_code == 409 and response.json()["detail"] == "snapshot_expired"
    for malformed in ("not-base64!", "", encode_snapshot_id(str(uuid4()), revision)):
        response = client.get(SNAPSHOT, headers=headers,
                              params={"protocolVersion": 3, "snapshotId": malformed})
        assert response.status_code == 409, malformed
        assert response.json()["detail"] == "snapshot_expired"


def test_snapshot_cursor_contract(client):
    _auth, headers = credential_for(client)
    _ids, _revisions, revision = seed(client, headers)
    page = snapshot(client, headers, limit=1)
    for cursor in ("not-base64!", "bm90LWEtY3Vyc29y", "d2Vic2l0ZXw"):  # garbage / no id
        response = client.get(SNAPSHOT, headers=headers, params={
            "protocolVersion": 3, "cursor": cursor, "snapshotId": page["snapshotId"]})
        assert response.status_code == 400, cursor
        assert response.json() == {"detail": "Invalid sync cursor", "resyncRequired": True,
                                   "workspaceRevision": revision}

    # A cursor without its pinned revision would page across two different snapshots.
    response = client.get(SNAPSHOT, headers=headers,
                          params={"protocolVersion": 3, "cursor": page["cursor"]})
    assert response.status_code == 400
    assert response.json()["resyncRequired"] is True
    assert response.json()["workspaceRevision"] == revision

    for limit in (0, 501):
        response = client.get(SNAPSHOT, headers=headers,
                              params={"protocolVersion": 3, "limit": limit})
        assert response.status_code == 422, limit


def test_snapshot_and_changes_require_protocol_v3(client):
    _auth, headers = credential_for(client)
    for path in ("/snapshot", "/changes"):
        response = client.get(ROOT + path, headers=headers, params={"protocolVersion": 2})
        assert response.status_code == 409, path
        assert response.json()["detail"] == "sync_protocol_mismatch"
    # `protocolVersion` is mandatory on the snapshot endpoint (422), unlike `/changes`
    # where the incompatible default (1) produces the 409 above.
    assert client.get(SNAPSHOT, headers=headers).status_code == 422


def test_snapshot_requires_core_mode(client):
    app.dependency_overrides.pop(require_core_mode, None)
    response = client.get(SNAPSHOT, headers={"Authorization": "Bearer nc_live_fake"},
                          params={"protocolVersion": 3})
    assert response.status_code == 404


def test_changes_invalid_cursor_asks_for_resync(client):
    _auth, headers = credential_for(client)
    before = client.get(f"{ROOT}/changes", headers=headers, params={"protocolVersion": 3}).json()
    assert "resyncRequired" not in before and before["changes"] == []
    _ids, _revisions, revision = seed(client, headers)

    response = client.get(f"{ROOT}/changes", headers=headers,
                          params={"protocolVersion": 3, "cursor": revision + 1})
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid sync cursor", "resyncRequired": True,
                               "workspaceRevision": revision}

    caught_up = client.get(f"{ROOT}/changes", headers=headers,
                           params={"protocolVersion": 3, "cursor": revision})
    assert caught_up.status_code == 200
    assert caught_up.json()["changes"] == [] and caught_up.json()["hasMore"] is False
    assert "resyncRequired" not in caught_up.json()
