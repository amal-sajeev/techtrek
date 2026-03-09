from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Return current date/time in IST as a naive datetime."""
    return datetime.now(IST).replace(tzinfo=None)
