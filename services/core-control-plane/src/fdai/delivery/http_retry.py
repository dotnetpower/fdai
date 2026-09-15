"""Parse provider retry hints without performing retries or granting read authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import isfinite


def retry_after_seconds(raw: str | None) -> float | None:
    """Keep the existing finite numeric Retry-After parsing contract."""
    if raw is None:
        return None
    try:
        delay = float(raw)
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
                raise ValueError(
                    "provider Retry-After MUST be a delay or timezone-aware HTTP date"
                ) from None
        deadline = max(now, deadline)
        latest = deadline if latest is None else max(latest, deadline)
    return latest
