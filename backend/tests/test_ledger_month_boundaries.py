"""Ledger month buckets must follow the app timezone, not the stored UTC wall clock.

``occurred_at`` is persisted as UTC and SQLite returns it naive, so a plain
``strftime("%Y-%m")`` puts the first and last eight hours of a Shanghai month
into the neighbouring month.
"""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from sqlalchemy import select

from app.database import get_db, runtime_config
from app.models import LedgerTransaction, User
from app.services import ledger
from app.services.ownership import owner_workspace
from app.utils.time import month_key

SHANGHAI = "Asia/Shanghai"
ROOT = "/api/v1/ledger"


@pytest.fixture
def shanghai(monkeypatch):
    """Pin the app timezone so assertions never depend on the host environment."""
    config = replace(runtime_config, app_timezone=SHANGHAI)
    monkeypatch.setattr(ledger, "runtime_config", config)
    return config


def create_transaction(client, headers, occurred_at, amount="10.00"):
    response = client.post(
        f"{ROOT}/transactions",
        headers=headers,
        json={
            "type": "expense",
            "amount": amount,
            "description": f"boundary {occurred_at}",
            "occurred_at": occurred_at,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_month_key_converts_instants_into_the_app_month():
    shanghai = ZoneInfo(SHANGHAI)
    # 2026-11-01 00:30 +08:00 == 2026-10-31 16:30 UTC
    assert month_key(datetime(2026, 11, 1, 0, 30, tzinfo=shanghai), SHANGHAI) == "2026-11"
    assert month_key(datetime(2026, 10, 31, 16, 30, tzinfo=timezone.utc), SHANGHAI) == "2026-11"
    # 2026-10-31 23:30 +08:00 == 2026-10-31 15:30 UTC
    assert month_key(datetime(2026, 10, 31, 23, 30, tzinfo=shanghai), SHANGHAI) == "2026-10"
    assert month_key(datetime(2026, 10, 31, 15, 30, tzinfo=timezone.utc), SHANGHAI) == "2026-10"
    # Naive values come from SQLite: they are UTC, never local wall time.
    assert month_key(datetime(2026, 10, 31, 16, 30), SHANGHAI) == "2026-11"
    assert month_key(datetime(2026, 10, 31, 15, 30), SHANGHAI) == "2026-10"
    assert month_key(None, SHANGHAI) is None
    with pytest.raises(ZoneInfoNotFoundError):
        month_key(datetime(2026, 10, 31, 16, 30), "Not/AZone")


def test_summary_counts_first_minute_of_month_in_the_new_month(client, users, shanghai):
    owner, _ = users
    create_transaction(client, owner, "2026-11-01T00:30:00+08:00", "10.00")

    november = client.get(f"{ROOT}/summary?month=2026-11", headers=owner).json()
    assert november["month"] == "2026-11"
    assert november["expense"] == "10.00"
    assert november["monthlyTrend"] == [{"month": "2026-11", "expense": "10.00"}]

    october = client.get(f"{ROOT}/summary?month=2026-10", headers=owner).json()
    assert october["expense"] == "0"
    assert october["monthlyTrend"] == [{"month": "2026-11", "expense": "10.00"}]


def test_summary_keeps_last_minute_of_month_in_the_old_month(client, users, shanghai):
    owner, _ = users
    create_transaction(client, owner, "2026-10-31T23:30:00+08:00", "20.00")

    october = client.get(f"{ROOT}/summary?month=2026-10", headers=owner).json()
    assert october["month"] == "2026-10"
    assert october["expense"] == "20.00"
    assert october["monthlyTrend"] == [{"month": "2026-10", "expense": "20.00"}]

    november = client.get(f"{ROOT}/summary?month=2026-11", headers=owner).json()
    assert november["expense"] == "0"


def test_list_transactions_month_filter_uses_app_timezone_boundaries(client, users, shanghai):
    owner, _ = users
    november_id = create_transaction(client, owner, "2026-11-01T00:30:00+08:00")
    october_id = create_transaction(client, owner, "2026-10-31T23:30:00+08:00")

    november = client.get(f"{ROOT}/transactions?month=2026-11", headers=owner).json()
    assert [item["id"] for item in november] == [november_id]

    october = client.get(f"{ROOT}/transactions?month=2026-10", headers=owner).json()
    assert [item["id"] for item in october] == [october_id]

    assert len(client.get(f"{ROOT}/transactions", headers=owner).json()) == 2


def test_summary_default_month_follows_the_app_timezone_clock(
    client, users, shanghai, monkeypatch
):
    frozen = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)  # 2026-11-01 07:30 in Shanghai

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr(ledger, "datetime", FrozenDateTime)
    owner, _ = users
    create_transaction(client, owner, "2026-11-01T05:00:00+08:00", "11.00")
    create_transaction(client, owner, "2026-10-31T23:30:00+08:00", "13.00")

    default = client.get(f"{ROOT}/summary", headers=owner).json()
    assert default["month"] == "2026-11"
    assert default["expense"] == "11.00"
    assert default["monthlyTrend"] == [
        {"month": "2026-10", "expense": "13.00"},
        {"month": "2026-11", "expense": "11.00"},
    ]


def test_summary_reads_naive_sqlite_timestamps_as_utc(client, users, shanghai):
    owner, _ = users
    # 2026-10-31 16:30 stored without an offset is 2026-11-01 00:30 in Shanghai.
    with next(client.app.dependency_overrides[get_db]()) as db:
        user = db.scalar(select(User).where(User.username == "owner_a"))
        item_id = str(uuid4())
        db.add(
            LedgerTransaction(
                id=item_id,
                user_id=user.id,
                workspace_id=owner_workspace(db, user),
                type="expense",
                amount=Decimal("7.00"),
                description="naive sqlite row",
                occurred_at=datetime(2026, 10, 31, 16, 30),
            )
        )
        db.commit()
        db.expire_all()
        stored = db.get(LedgerTransaction, item_id)
        assert stored is not None and stored.occurred_at == datetime(2026, 10, 31, 16, 30)

    november = client.get(f"{ROOT}/summary?month=2026-11", headers=owner).json()
    assert november["expense"] == "7.00"
    assert client.get(f"{ROOT}/summary?month=2026-10", headers=owner).json()["expense"] == "0"
    assert [item["id"] for item in client.get(
        f"{ROOT}/transactions?month=2026-11", headers=owner).json()] == [item_id]
