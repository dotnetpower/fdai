"""Correlation context helpers for Pantheon EventBus delivery."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from fdai.shared.telemetry import with_correlation


@contextmanager
def event_correlation_scope(payload: Mapping[str, object]) -> Iterator[None]:
    """Bind a non-empty wire correlation only for the current delivery."""
    correlation_id = str(payload.get("correlation_id") or "").strip()
    if not correlation_id:
        yield
        return
    with with_correlation(correlation_id):
        yield


__all__ = ["event_correlation_scope"]
