"""Shared ISO date-range normalization for indexing and retrieval."""

from __future__ import annotations

from datetime import UTC, date, datetime, time


class DateRangeError(ValueError):
    """An ISO date filter or range is invalid."""


def normalize_date_filter(value: str | None, *, end_of_day: bool = False) -> str | None:
    """Normalize an ISO date/datetime to an explicit UTC timestamp."""

    if value is None:
        return None
    try:
        if "T" not in value and " " not in value:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(
                parsed_date,
                time.max if end_of_day else time.min,
                tzinfo=UTC,
            )
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            parsed = parsed.astimezone(UTC)
    except ValueError as exc:
        raise DateRangeError(f"Invalid ISO date or datetime: {value!r}") from exc
    return parsed.isoformat()


def normalize_date_range(
    since: str | None,
    until: str | None,
) -> tuple[str | None, str | None]:
    """Normalize an inclusive range and reject reversed bounds."""

    normalized_since = normalize_date_filter(since)
    normalized_until = normalize_date_filter(until, end_of_day=True)
    if normalized_since and normalized_until and normalized_since > normalized_until:
        raise DateRangeError("--since must not be later than --until")
    return normalized_since, normalized_until


def timestamp_in_range(
    value: str,
    *,
    since: str | None,
    until: str | None,
) -> bool:
    """Return whether one ISO timestamp falls inside normalized inclusive bounds."""

    timestamp = normalize_date_filter(value)
    if timestamp is None:
        return False
    return (since is None or timestamp >= since) and (until is None or timestamp <= until)
