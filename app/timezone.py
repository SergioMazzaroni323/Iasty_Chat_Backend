from datetime import datetime, timezone

STORAGE_TIMEZONE = timezone.utc


def utc_now() -> datetime:
    return datetime.now(STORAGE_TIMEZONE)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=STORAGE_TIMEZONE)
    return dt.astimezone(STORAGE_TIMEZONE)


def to_utc_iso(dt: datetime) -> str:
    return ensure_utc(dt).isoformat().replace("+00:00", "Z")
