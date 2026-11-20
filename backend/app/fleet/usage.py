"""Store numeric Fleet telemetry and aggregate it without retaining chat payloads."""

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import FleetUsageSample, utcnow
from ..utils.time import aware_utc


COUNTS = {"cached": "cached", "other_input": "otherInput", "output": "output", "other": "other", "total": "tokens"}


def _count(value: object) -> int:
    return value if type(value) is int and 0 <= value <= (1 << 53) - 1 else 0


def _identifier(value: object) -> str:
    return value if isinstance(value, str) and 0 < len(value) <= 512 else ""


def _key(*parts: str) -> str:
    return sha256(json.dumps(parts, separators=(",", ":")).encode("ascii")).hexdigest()


def record_frame(db: Session, workspace_id: str, node_id: str, frame: dict) -> None:
    sample = frame.get("usage") if frame.get("type") == "Completed" else frame
    if not isinstance(sample, dict) or sample.get("source") != "exact":
        return
    session_id = _identifier(frame.get("sessionId"))
    run_id = _identifier(frame.get("runId")) or _identifier(frame.get("requestId"))
    if not session_id or not run_id:
        return

    cumulative = sample.get("scope") == "cumulative"
    input_tokens = _count(sample.get("lastInputTokens" if cumulative else "inputTokens"))
    cached = _count(sample.get("lastCachedInputTokens" if cumulative else "cachedInputTokens"))
    output = _count(sample.get("lastOutputTokens" if cumulative else "outputTokens"))
    other_input = max(0, input_tokens - cached)
    breakdown = cached + other_input + output
    total = max(breakdown, _count(sample.get("lastTotalTokens" if cumulative else "totalTokens")))
    if not total:
        return

    # Identity comes from the authenticated socket; the frame cannot select a workspace or node.
    turn_key = _key(workspace_id, node_id, _identifier(frame.get("provider")), session_id, run_id)
    part = "" if cumulative else _identifier(sample.get("messageId"))
    values = {
        "id": _key(turn_key, part), "workspace_id": workspace_id, "turn_key": turn_key,
        "whole_turn": not part, "recorded_at": utcnow(), "sequence": _count(frame.get("seq")),
        "cached": cached, "other_input": other_input, "output": output, "other": total - breakdown, "total": total,
    }
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = insert(FleetUsageSample).values(**values)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[FleetUsageSample.id],
        set_={key: stmt.excluded[key] for key in ("sequence", *COUNTS)},
        where=stmt.excluded.sequence >= FleetUsageSample.sequence,
    ))
    db.commit()


def daily_totals(db: Session, workspace_id: str, start: date, end: date, zone: ZoneInfo) -> list[dict]:
    start_at = datetime.combine(start, time.min, zone).astimezone(timezone.utc)
    end_at = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    sample = FleetUsageSample
    candidates = select(sample.turn_key).where(
        sample.workspace_id == workspace_id, sample.recorded_at >= start_at, sample.recorded_at < end_at,
    ).distinct().subquery()
    totals = []
    for column, label in COUNTS.items():
        value = getattr(sample, column)
        totals.append(func.coalesce(func.max(case((sample.whole_turn, value))), func.sum(value)).label(label))
    per_turn = (
        select(func.min(sample.recorded_at).label("recorded_at"), *totals)
        .join(candidates, candidates.c.turn_key == sample.turn_key)
        .where(sample.workspace_id == workspace_id)
        .group_by(sample.turn_key)
        .execution_options(yield_per=500)
    )
    by_date: dict[str, dict] = {}
    for row in db.execute(per_turn).mappings():
        day = aware_utc(row["recorded_at"]).astimezone(zone).date()
        if not start <= day <= end:
            continue
        key = day.isoformat()
        total = by_date.setdefault(key, {"date": key, "requests": 0, **dict.fromkeys(COUNTS.values(), 0)})
        total["requests"] += 1
        for field in COUNTS.values():
            total[field] += int(row[field])
    return [by_date[key] for key in sorted(by_date)]
