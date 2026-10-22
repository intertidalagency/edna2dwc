from datetime import datetime
def require_iso_datetime(value: str, flag: str) -> None:
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise UsageError(f"{flag} must be an ISO 8601 datetime; got {value!r}") from error


