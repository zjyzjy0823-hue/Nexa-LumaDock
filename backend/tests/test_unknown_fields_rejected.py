"""业务输入模型必须拒绝未知字段。

同步通道用 camelCase、业务 REST 用 snake_case。以前写错字段名不会报错，
只会静默丢数据（``categoryId`` 被忽略 → 交易没有分类），Android 接入必然踩。
"""

import pytest

LEDGER = "/api/v1/ledger"
DATA = "/api/v1/data"

TRANSACTION = {
    "type": "expense",
    "amount": "12.00",
    "description": "unknown field probe",
    "occurred_at": "2026-11-15T10:00:00Z",
}


def assert_rejected(response):
    """422 is the contract; FastAPI lists the field, SafePersonalRoute returns a message."""
    assert response.status_code == 422, response.text
    detail = response.json().get("detail")
    if isinstance(detail, list):
        assert any("extra_forbidden" in str(item.get("type", ""))
                   or "Extra inputs" in str(item.get("message", "")) for item in detail), detail
    else:
        assert isinstance(detail, str) and detail, detail


def test_transaction_rejects_camel_case_category(client, users):
    owner, _ = users
    response = client.post(f"{LEDGER}/transactions", headers=owner,
                           json={**TRANSACTION, "categoryId": "e20e5250-85b6-4fe8-882e-14bfa1b5445a"})
    assert_rejected(response)


def test_transaction_patch_rejects_unknown_field(client, users):
    owner, _ = users
    created = client.post(f"{LEDGER}/transactions", headers=owner, json=TRANSACTION).json()
    assert_rejected(client.patch(f"{LEDGER}/transactions/{created['id']}", headers=owner,
                                 json={"amount": "13.00", "occurredAt": "2026-11-16T10:00:00Z"}))


def test_category_rejects_unknown_field(client, users):
    owner, _ = users
    assert_rejected(client.post(f"{LEDGER}/categories", headers=owner,
                                json={"name": "probe", "type": "expense", "color": "#fff"}))


def test_website_rejects_unknown_field(client, users):
    owner, _ = users
    assert_rejected(client.post("/api/v1/websites", headers=owner,
                                json={"name": "probe", "url": "https://probe.example.com", "favicon": "x"}))


def test_record_rejects_unknown_field(client, users):
    owner, _ = users
    collection = client.post(f"{DATA}/collections", headers=owner, json={"name": "probe"}).json()
    assert_rejected(client.post(f"{DATA}/collections/{collection['id']}/records", headers=owner,
                                json={"name": "probe", "payload": {}}))


def test_settings_rejects_unknown_field(client, users):
    owner, _ = users
    assert_rejected(client.patch("/api/v1/settings", headers=owner, json={"theme": "dark", "accent": "x"}))


@pytest.mark.parametrize("payload", [
    TRANSACTION,
    {**TRANSACTION, "merchant": "shop", "note": "ok"},
])
def test_valid_payloads_still_accepted(client, users, payload):
    owner, _ = users
    assert client.post(f"{LEDGER}/transactions", headers=owner, json=payload).status_code == 201
