"""Recurring bounded utilization sampling for Freyr."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.agents._framework.topics import stable_idempotency_key

MAX_RECURRING_SAMPLES = 64
MAX_SAMPLE_IDENTIFIER_CHARS = 512


@dataclass(frozen=True, slots=True)
class UtilizationSample:
    """One read-only utilization sample returned by a Freyr sampler port."""

    resource_id: str
    utilization: float
    observed_at: str = ""
    correlation_id: str = ""
    sample_key: str = ""


class CapacityUtilizationSampler(Protocol):
    """Read-only port for recurring Freyr utilization sampling."""

    async def read_utilization_samples(
        self,
        *,
        limit: int,
        observed_at: datetime,
    ) -> Sequence[UtilizationSample]: ...


async def run_recurring_sampling(
    *,
    sampler: CapacityUtilizationSampler | None,
    clock: Callable[[], datetime],
    ingest: Callable[..., Awaitable[None]],
    record_behavior: Callable[[str, int], None],
    limit: int = MAX_RECURRING_SAMPLES,
    timeout_seconds: float = 5.0,
) -> int:
    """Pull one bounded sampler batch and feed Freyr's existing ingestion path."""

    if sampler is None:
        record_behavior("capacity_sampling:unbound", 1)
        return 0
    if limit < 1:
        raise ValueError("recurring sample limit MUST be positive")
    if timeout_seconds <= 0:
        raise ValueError("recurring sample timeout MUST be positive")
    bounded_limit = min(limit, MAX_RECURRING_SAMPLES)
    sampled_at = clock()
    try:
        async with asyncio.timeout(timeout_seconds):
            raw_samples = await sampler.read_utilization_samples(
                limit=bounded_limit,
                observed_at=sampled_at,
            )
    except TimeoutError:
        record_behavior("capacity_sampling:timeout", 1)
        return 0
    accepted = 0
    for index, sample in enumerate(tuple(raw_samples)[:bounded_limit]):
        normalized = _normalize_sample(sample, default_observed_at=sampled_at, index=index)
        if normalized is None:
            record_behavior("capacity_sampling:invalid", 1)
            continue
        await ingest(
            resource_id=normalized.resource_id,
            utilization=normalized.utilization,
            correlation_id=normalized.correlation_id,
            observed_at=normalized.observed_at,
            sample_key=normalized.sample_key,
        )
        accepted += 1
    if accepted:
        record_behavior("capacity_sampling:sampled", accepted)
    else:
        record_behavior("capacity_sampling:empty", 1)
    return accepted


def _normalize_sample(
    sample: UtilizationSample,
    *,
    default_observed_at: datetime,
    index: int,
) -> UtilizationSample | None:
    resource_id = _bounded_string(sample.resource_id)
    if resource_id is None:
        return None
    utilization = sample.utilization
    if isinstance(utilization, bool) or not math.isfinite(utilization) or not 0 <= utilization <= 1:
        return None
    observed_at = (
        _bounded_string(sample.observed_at, required=False) or default_observed_at.isoformat()
    )
    correlation_id = _bounded_string(
        sample.correlation_id, required=False
    ) or stable_idempotency_key(
        "freyr-recurring-sample-correlation",
        resource_id,
        observed_at,
    )
    sample_key = _bounded_string(sample.sample_key, required=False) or stable_idempotency_key(
        "freyr-recurring-sample",
        resource_id,
        utilization,
        observed_at,
        correlation_id,
        index,
    )
    return UtilizationSample(
        resource_id=resource_id,
        utilization=float(utilization),
        observed_at=observed_at,
        correlation_id=correlation_id,
        sample_key=sample_key,
    )


def _bounded_string(value: object, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_SAMPLE_IDENTIFIER_CHARS
        or any((ord(char) < 32 and char not in "\t") or ord(char) == 127 for char in normalized)
    ):
        return None
    return normalized


__all__ = [
    "MAX_RECURRING_SAMPLES",
    "CapacityUtilizationSampler",
    "UtilizationSample",
    "run_recurring_sampling",
]
