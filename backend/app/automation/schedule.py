"""UTC due points, explicit IANA zone; DST gaps skip, folds fire once (fold=0)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from ..utils.time import aware_utc
from .schemas import Schedule


def next_due(config: dict, after: datetime, *, inclusive=False) -> datetime | None:
    value = Schedule.model_validate(config)
    after = aware_utc(after)
    if value.type in ("once", "interval"):
        anchor = aware_utc(value.at)
        if value.type == "once":
            return anchor if anchor > after or (inclusive and anchor == after) else None
        elapsed = (after - anchor).total_seconds()
        steps = max(0, int(elapsed // value.seconds) + 1)
        if inclusive and elapsed >= 0 and elapsed % value.seconds == 0:
            steps -= 1
        return anchor + timedelta(seconds=steps * value.seconds)
    zone = ZoneInfo(value.timezone)
    date = after.astimezone(zone).date()
    hour, minute = map(int, value.time.split(":"))
    for day in range(15):
        candidate_date = date + timedelta(days=day)
        if value.type == "weekly" and candidate_date.weekday() not in value.weekdays:
            continue
        wall = datetime(candidate_date.year, candidate_date.month, candidate_date.day, hour, minute)
        point = wall.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
        if point.astimezone(zone).replace(tzinfo=None) != wall:
            continue  # nonexistent wall time
        if point > after or (inclusive and point == after):
            return point
    raise ValueError("No schedule point")


def latest_due(config: dict, due: datetime, now: datetime) -> datetime:
    value = Schedule.model_validate(config)
    due, now = aware_utc(due), aware_utc(now)
    if value.type == "once":
        return due
    if value.type == "interval":
        return due + timedelta(seconds=int((now - due).total_seconds() // value.seconds) * value.seconds)
    # Bounded lookup regardless of downtime length.
    cursor = now - timedelta(days=8)
    latest = due
    while (point := next_due(config, cursor)) is not None and point <= now:
        latest, cursor = point, point
    return latest
