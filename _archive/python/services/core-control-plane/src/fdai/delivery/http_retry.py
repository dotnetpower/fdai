"""Parse provider retry hints without performing retries or granting read authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import isfinite


class InvalidRetryAfterError(ValueError):
    """Retain any known cooldown while reporting malformed companion hints."""

    def __init__(self, *, retry_not_before: datetime | None) -> None:
        super().__init__("provider Retry-After MUST be a delay or timezone-aware HTTP date")
        self.retry_not_before = retry_not_before


def retry_after_seconds(raw: str | None) -> float | None:
    """Keep the existing finite numeric Retry-After parsing contract."""
    if raw is None:
        return None
    text = raw.strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 3:
            try:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
            except ValueError:
                return None
            if hours >= 0 and 0 <= minutes < 60 and isfinite(seconds) and 0 <= seconds < 60:
                total = hours * 3600 + minutes * 60 + seconds
                return total if isfinite(total) and total >= 0 else None
        return None
    try:
        delay = float(text)
    except ValueError:
        return None
    return delay if isfinite(delay) and delay >= 0 else None


def retry_not_before(
    headers: Mapping[str, str],
    *,
    now: datetime,
    extra_headers: Sequence[str] = (),
) -> datetime | None:
    """Return the latest advertised retry instant, never an earlier clamped delay."""
    if now.tzinfo is None:
        raise ValueError("retry observation time MUST include a timezone")
    now = now.astimezone(UTC)
    normalized = {name.lower(): value for name, value in headers.items()}
    latest: datetime | None = None
    invalid = False
    ceiling = datetime.max.replace(tzinfo=UTC)
    for name in ("retry-after", *extra_headers):
        raw = normalized.get(name.lower())
        if raw is None:
            continue
        delay = retry_after_seconds(raw)
        if raw.strip().isdigit() and len(raw.strip()) > 18:
            deadline = ceiling
        elif delay is not None:
            try:
                deadline = now + timedelta(seconds=delay)
            except OverflowError:
                deadline = ceiling
        else:
            try:
                parsed = parsedate_to_datetime(raw)
                if parsed.tzinfo is None:
                    raise ValueError("missing timezone")
                deadline = parsed.astimezone(UTC)
            except (TypeError, ValueError, OverflowError):
                invalid = True
                continue
        deadline = max(now, deadline)
        latest = deadline if latest is None else max(latest, deadline)
    if invalid:
        raise InvalidRetryAfterError(retry_not_before=latest)
    return latest
