"""Opt-in bounded reads, with legacy response shapes preserved by default."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select

from app.database import get_db
from app.models import DataCollection, DataRecord, User, Workspace

ROOT = "/api/v1/data"
STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
SUMMARY_KEYS = {"id", "name", "description", "icon", "tone", "recordCount", "createdAt", "updatedAt"}
RECORD_KEYS = {"id", "collectionId", "name", "status", "category", "createdAt", "updatedAt"}


@pytest.fixture
def seeded(client, users):
    a, b = users
    # Initialize each personal workspace through the ordinary API.
    for headers in users:
        client.get(f"{ROOT}/collections", headers=headers)
    dependency = client.app.dependency_overrides[get_db]()
    db = next(dependency)
    owners = db.scalars(select(User).order_by(User.id)).all()
    workspaces = [db.scalar(select(Workspace).where(Workspace.owner_user_id == u.id)) for u in owners]
    for cid, name, description, owner, ws, deleted in (
        ("c1", "Library", "whole-collection", owners[0], workspaces[0], None),
        ("c2", "Servers", "", owners[0], workspaces[0], None),
        ("empty", "Empty", "", owners[0], workspaces[0], None),
        ("gone", "whole-collection", "", owners[0], workspaces[0], STAMP),
        ("other", "whole-collection", "", owners[1], workspaces[1], None),
    ):
        db.add(DataCollection(id=cid, name=name, description=description, user_id=owner.id,
                              workspace_id=ws.id, deleted_at=deleted))
    db.flush()
    rows = []
    for i, status in enumerate(("done", "completed", "完成", "active", "DONE", "", "reading")):
        rows.append(dict(id=f"r{i}", collection_id="c1", name=f"Book {i}", status=status,
                         category="sci-fi" if i == 4 else "", updated_at=STAMP + timedelta(seconds=i // 3)))
    rows += [dict(id="s1", collection_id="c2", name="needle", status="active"),
             dict(id="s2", collection_id="c2", name="Other", status="done"),
             dict(id="deleted", collection_id="c1", name="deleted-only", deleted_at=STAMP),
             dict(id="orphan", collection_id="gone", name="deleted-parent"),
             dict(id="foreign", collection_id="other", name="foreign-only", user_id=owners[1].id,
                  workspace_id=workspaces[1].id),
             dict(id="wrong-user", collection_id="c1", name="invalid-only", user_id=owners[1].id),
             dict(id="wrong-workspace", collection_id="c1", name="invalid-only", workspace_id=workspaces[1].id)]
    for row in rows:
        values = dict(user_id=owners[0].id, workspace_id=workspaces[0].id, name="Hidden",
                      status="active", category="", data_json={"payload": "large"},
                      created_at=STAMP, updated_at=STAMP)
        values.update(row)
        db.add(DataRecord(**values))
    db.commit()
    engine = db.get_bind()
    dependency.close()
    return a, b, engine


@contextmanager
def sql_reads(engine):
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_collection_summary_counts_without_loading_records(client, seeded):
    a, _, engine = seeded
    with sql_reads(engine) as statements:
        response = client.get(f"{ROOT}/collections?include_records=false", headers=a)
    assert response.status_code == 200
    items = response.json()
    assert all(set(item) == SUMMARY_KEYS for item in items)
    assert {item["id"]: item["recordCount"] for item in items} == {"c1": 7, "c2": 2, "empty": 0}
    assert any("count(" in sql and "group by" in sql for sql in statements)
    assert not any("data_records.data_json" in sql for sql in statements)


@pytest.mark.parametrize("q,expected", [
    ("LIBRARY", {"c1": 7}), ("whole-collection", {"c1": 7}),
    ("needle", {"c2": 2}), ("completed", {"c1": 7}), ("SCI-FI", {"c1": 7}),
    ("deleted-only", {}), ("invalid-only", {}), ("foreign-only", {}), ("%", {}),
])
def test_collection_search_parent_or_record_match(client, seeded, q, expected):
    a, _, engine = seeded
    with sql_reads(engine) as statements:
        result = client.get(f"{ROOT}/collections", headers=a,
                            params={"include_records": "false", "q": q})
    assert result.status_code == 200
    assert {c["id"]: c["recordCount"] for c in result.json()} == expected
    assert any("exists (" in sql for sql in statements)


def test_collection_detail_create_patch_summary_and_defaults(client, users):
    a, _ = users
    created = client.post(f"{ROOT}/collections?include_records=false", headers=a, json={"name": "New"})
    assert created.status_code == 201
    assert set(created.json()) == SUMMARY_KEYS
    cid = created.json()["id"]
    client.post(f"{ROOT}/collections/{cid}/records", headers=a, json={"name": "One"})
    for response in (
        client.get(f"{ROOT}/collections/{cid}?include_records=false", headers=a),
        client.patch(f"{ROOT}/collections/{cid}?include_records=false", headers=a, json={"name": "Renamed"}),
    ):
        assert response.status_code == 200
        assert set(response.json()) == SUMMARY_KEYS
        assert response.json()["recordCount"] == 1
    assert len(client.get(f"{ROOT}/collections/{cid}", headers=a).json()["records"]) == 1
    assert "records" in client.get(f"{ROOT}/collections", headers=a).json()[0]
    assert isinstance(client.get(f"{ROOT}/collections/{cid}/records", headers=a).json(), list)
    assert "records" in client.post(f"{ROOT}/collections", headers=a, json={"name": "Default"}).json()
    assert "records" in client.patch(f"{ROOT}/collections/{cid}", headers=a, json={"name": "Default"}).json()
    assert "records" in client.get("/api/data?include_records=false", headers=a).json()["collections"][0]


def test_record_cursor_pages_are_stable_with_tied_timestamps(client, seeded):
    a, _, engine = seeded
    seen, cursor = [], None
    while True:
        params = {"page": "true", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        with sql_reads(engine) as statements:
            response = client.get(f"{ROOT}/collections/c1/records", headers=a, params=params)
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == page["matchedCount"] == 7
        assert all(set(item) == RECORD_KEYS for item in page["items"])
        assert not any("data_records.data_json" in sql for sql in statements)
        assert any("order by data_records.updated_at desc, data_records.id desc" in sql and "limit" in sql
                   for sql in statements)
        seen.extend(item["id"] for item in page["items"])
        cursor = page["nextCursor"]
        assert page["hasMore"] == (cursor is not None)
        if not cursor:
            break
    assert seen == ["r6", "r5", "r4", "r3", "r2", "r1", "r0"]


def test_record_page_search_and_optional_json(client, seeded):
    a, _, _ = seeded
    for q, expected in (("book", 7), ("completed", 1), ("SCI-FI", 1), ("Library", 0), ("missing", 0)):
        response = client.get(f"{ROOT}/collections/c1/records", headers=a,
                              params={"page": "true", "q": q, "include_data_json": "true"})
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == 7 and page["matchedCount"] == expected
        assert len(page["items"]) == expected
        assert page["nextCursor"] is None and not page["hasMore"]
        assert all(item["dataJson"] == {"payload": "large"} for item in page["items"])
    empty = client.get(f"{ROOT}/collections/empty/records?page=true", headers=a).json()
    assert empty == {"items": [], "total": 0, "matchedCount": 0, "nextCursor": None, "hasMore": False}


@pytest.mark.parametrize("params", [
    {"limit": 50}, {"q": ""}, {"include_data_json": "false"},
    {"page": "false", "limit": 50}, {"page": "false", "q": "needle"},
    {"page": "true", "limit": 0}, {"page": "true", "limit": 201},
    # An empty `cursor=` means "first page" on purpose: many HTTP clients
    # serialize an absent optional parameter as an empty string.
    {"page": "true", "cursor": "invalid"},
])
def test_record_page_invalid_parameters(client, users, params):
    a, _ = users
    cid = client.post(f"{ROOT}/collections", headers=a, json={"name": "New"}).json()["id"]
    assert client.get(f"{ROOT}/collections/{cid}/records", headers=a, params=params).status_code == 422


def test_cursor_bound_to_collection_query_and_integrity(client, seeded):
    a, _, _ = seeded
    cursor = client.get(f"{ROOT}/collections/c1/records?page=true&limit=1&q=Book", headers=a).json()["nextCursor"]
    for cid, q, token in (("c2", "Book", cursor), ("c1", "", cursor), ("c1", "Book", cursor + "x")):
        response = client.get(f"{ROOT}/collections/{cid}/records", headers=a,
                              params={"page": "true", "q": q, "cursor": token})
        assert response.status_code == 422


def test_overview_matches_individual_records_and_uses_sql_limit(client, seeded):
    a, _, engine = seeded
    with sql_reads(engine) as statements:
        response = client.get(f"{ROOT}/overview?recent_limit=4", headers=a)
    assert response.status_code == 200
    overview = response.json()
    assert overview["totalCollections"] == 3
    assert (overview["totalRecords"], overview["active"], overview["completed"]) == (9, 5, 4)
    assert [r["id"] for r in overview["recentRecords"]] == ["r6", "r5", "r4", "r3"]
    assert all(set(r) == RECORD_KEYS | {"collectionName"} for r in overview["recentRecords"])
    assert all(r["collectionName"] == "Library" for r in overview["recentRecords"])
    assert any("count(" in sql for sql in statements)
    assert any("order by" in sql and "limit" in sql for sql in statements)
    assert not any("data_records.data_json" in sql for sql in statements)
    records = [record for c in client.get(f"{ROOT}/collections", headers=a).json() for record in c["records"]]
    assert overview["totalRecords"] == len(records)
    assert overview["completed"] == sum(r["status"] in {"done", "completed", "完成"} for r in records)


@pytest.mark.parametrize("limit", [0, 21])
def test_overview_limit_validation(client, users, limit):
    assert client.get(f"{ROOT}/overview?recent_limit={limit}", headers=users[0]).status_code == 422


def test_bounded_reads_tenant_and_deleted_parent_isolation(client, seeded):
    a, b, _ = seeded
    assert client.get(f"{ROOT}/collections?include_records=false", headers=b).json()[0]["id"] == "other"
    overview = client.get(f"{ROOT}/overview", headers=b).json()
    assert (overview["totalCollections"], overview["totalRecords"], overview["active"]) == (1, 1, 1)
    for cid, headers in (("c1", b), ("other", a), ("gone", a)):
        assert client.get(f"{ROOT}/collections/{cid}?include_records=false", headers=headers).status_code == 404
        assert client.get(f"{ROOT}/collections/{cid}/records?page=true", headers=headers).status_code == 404


def test_record_detail_checks_child_user_as_well_as_workspace(client, seeded):
    a, _, _ = seeded
    assert client.get(f"{ROOT}/records/wrong-user", headers=a).status_code == 404


def test_empty_overview(client, users):
    response = client.get(f"{ROOT}/overview", headers=users[0])
    assert response.status_code == 200
    assert response.json() == {"totalCollections": 0, "totalRecords": 0, "active": 0,
                               "completed": 0, "recentRecords": []}


def test_empty_cursor_is_treated_as_the_first_page(client, users):
    """A client that sends `cursor=` (empty) must not be rejected."""
    headers = users[0]
    collection = client.post(f"{ROOT}/collections", headers=headers, json={"name": "Empty cursor"}).json()
    for index in range(3):
        client.post(f"{ROOT}/collections/{collection['id']}/records", headers=headers,
                    json={"name": f"R{index}", "data_json": {"i": index}})
    page = client.get(f"{ROOT}/collections/{collection['id']}/records?page=true&cursor=", headers=headers)
    assert page.status_code == 200, page.text
    assert len(page.json()["items"]) == 3
