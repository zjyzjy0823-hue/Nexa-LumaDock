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
