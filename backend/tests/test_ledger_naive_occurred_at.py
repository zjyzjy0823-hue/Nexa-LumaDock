"""Naive ``occurred_at`` means wall time in the app timezone, never UTC.

SQLite stores UTC and clients without an offset send local wall time. Reading
``2026-11-30 23:00:00`` as UTC shifts the instant eight hours forward for
Shanghai, so the entry lands in December instead of November.
"""

from dataclasses import replace

import pytest

from app.database import runtime_config
from app.services import ledger

SHANGHAI = "Asia/Shanghai"
ROOT = "/api/v1/ledger"


@pytest.fixture
def shanghai(monkeypatch):
    config = replace(runtime_config, app_timezone=SHANGHAI)
    monkeypatch.setattr(ledger, "runtime_config", config)
    return config


def post(client, headers, occurred_at, amount="10.00", description="naive time"):
    return client.post(
        f"{ROOT}/transactions",
        headers=headers,
        json={
            "type": "expense",
            "amount": amount,
            "description": description,
            "occurred_at": occurred_at,
        },
    )


def test_naive_value_is_read_in_the_app_timezone(client, users, shanghai):
    owner, _ = users
    response = post(client, owner, "2026-11-30 23:00:00")
    assert response.status_code == 201
    # 2026-11-30 23:00 +08:00 == 2026-11-30 15:00 UTC
    assert response.json()["occurredAt"] == "2026-11-30T15:00:00+00:00"


def test_naive_value_stays_in_its_local_month(client, users, shanghai):
    owner, _ = users
    response = post(client, owner, "2026-11-30 23:00:00", amount="11.30")
    assert response.status_code == 201

    november = client.get(f"{ROOT}/summary?month=2026-11", headers=owner).json()
    december = client.get(f"{ROOT}/summary?month=2026-12", headers=owner).json()
    assert november["expense"] == "11.30"
    assert december["expense"] == "0"


def test_naive_and_offset_aware_inputs_describe_the_same_instant(client, users, shanghai):
    owner, _ = users
    naive = post(client, owner, "2026-11-01 00:30:00").json()
    aware = post(client, owner, "2026-11-01T00:30:00+08:00").json()
    utc = post(client, owner, "2026-10-31T16:30:00Z").json()
    assert naive["occurredAt"] == aware["occurredAt"] == utc["occurredAt"]
    # 00:30 local on 1 November is still November, not the previous month.
    assert naive["occurredAt"] == "2026-10-31T16:30:00+00:00"


def test_utc_marker_is_never_reinterpreted(client, users, shanghai):
    owner, _ = users
    response = post(client, owner, "2026-11-30T23:00:00Z")
    assert response.json()["occurredAt"] == "2026-11-30T23:00:00+00:00"


def test_patch_normalizes_a_naive_value(client, users, shanghai):
    owner, _ = users
    created = post(client, owner, "2026-11-15T10:00:00Z").json()
    patched = client.patch(
        f"{ROOT}/transactions/{created['id']}",
        headers=owner,
        json={"occurred_at": "2026-11-30 23:00:00"},
    )
    assert patched.status_code == 200
    assert patched.json()["occurredAt"] == "2026-11-30T15:00:00+00:00"

    november = client.get(f"{ROOT}/summary?month=2026-11", headers=owner).json()
    december = client.get(f"{ROOT}/summary?month=2026-12", headers=owner).json()
    assert november["expense"] == "10.00"
    assert december["expense"] == "0"


def test_other_timezone_shifts_the_interpretation(client, users, monkeypatch):
    config = replace(runtime_config, app_timezone="America/New_York")
    monkeypatch.setattr(ledger, "runtime_config", config)
    owner, _ = users
    response = post(client, owner, "2026-11-30 23:00:00")
    # 23:00 EST == 04:00 UTC on 1 December
    assert response.json()["occurredAt"] == "2026-12-01T04:00:00+00:00"
