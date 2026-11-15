from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    normalized = aware_utc(value)
    return normalized.isoformat() if normalized is not None else None


def assume_zone(value: datetime | None, area: str) -> datetime | None:
    """Read a naive datetime as wall time in ``area`` and return it in UTC.

    Clients that send ``2026-11-30 23:00:00`` mean local wall time, so naive
    values must never be read as UTC (that shifts the instant by the zone
    offset and pushes entries into the neighbouring day or month).
    Offset-aware values are converted as-is.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(area))
    return value.astimezone(timezone.utc)


def month_key(value: datetime | None, area: str) -> str | None:
    """Calendar month ("YYYY-MM") of ``value`` as seen in the ``area`` timezone.

    Persisted timestamps are UTC and SQLite drops the offset, so naive values
    are read as UTC before converting. An unknown ``area`` raises
    ``ZoneInfoNotFoundError``.
    """
    normalized = aware_utc(value)
    if normalized is None:
        return None
    return normalized.astimezone(ZoneInfo(area)).strftime("%Y-%m")
