"""Bounded deterministic findings using the existing FDAI Event wire contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from eval.gpu_monitoring.models import Analysis, GpuSample, Policy
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.contracts.validation import ContractValidator

_DEFAULT_POLICY = Policy()


class FindingPublisher(Protocol):
    """The publish-only subset of FDAI EventBus, without execution authority."""

    async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> object: ...


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def analyze(
    samples: Sequence[GpuSample], *, now: datetime, policy: Policy = _DEFAULT_POLICY
) -> Analysis:
    """Analyze exactly one logical GPU/source window; incomplete evidence is explicit."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now MUST include a timezone")
    if len(samples) > policy.max_samples:
        raise ValueError("sample count exceeds the policy bound")
    if not samples:
        return Analysis("insufficient_evidence", "no_samples", ())
    identity = samples[0].identity
    by_time: dict[datetime, GpuSample] = {}
    for sample in samples:
        # Revalidate even model_copy-produced objects at this untrusted replay boundary.
        sample = GpuSample.model_validate(sample.model_dump())
        if sample.identity != identity:
            raise ValueError("a window MUST contain exactly one GPU/source identity")
        if sample.observed_at > now:
            raise ValueError("observed_at MUST NOT be in the future")
        previous = by_time.get(sample.observed_at)
        if previous is not None and previous != sample:
            raise ValueError("conflicting observations at the same timestamp")
        by_time[sample.observed_at] = sample
    ordered = tuple(by_time[time] for time in sorted(by_time))
    latest = ordered[-1]
    if (now - latest.observed_at).total_seconds() > policy.max_age_seconds:
        return Analysis("insufficient_evidence", "stale_samples", ordered)
    start = latest.observed_at - timedelta(seconds=policy.window_seconds)
    window = tuple(item for item in ordered if item.observed_at >= start)
    coverage_reason = _coverage_reason(window, policy)
    evidence_digest = _digest([item.model_dump(mode="json") for item in window])
    policy_digest = _digest(asdict(policy))
    candidates = _detect(window, policy, sustained=coverage_reason is None)
    if not candidates and coverage_reason is not None:
        return Analysis(
            "insufficient_evidence", coverage_reason, window, (), evidence_digest, policy_digest
        )
    events = tuple(
        _event(window, signal, kind, severity, now, evidence_digest, policy_digest)
        for signal, kind, severity in candidates
    )
    return Analysis(
        "finding" if events else "healthy",
        coverage_reason or ("threshold_findings" if events else "monitored_thresholds_clear"),
        window,
        events,
        evidence_digest,
        policy_digest,
    )


def _coverage_reason(samples: tuple[GpuSample, ...], policy: Policy) -> str | None:
    window = samples
    if (window[-1].observed_at - window[0].observed_at).total_seconds() < policy.window_seconds:
        return "short_window"
    if any(
        (right.observed_at - left.observed_at).total_seconds() > policy.max_gap_seconds
        for left, right in zip(window, window[1:], strict=False)
    ):
        return "sampling_gap"
    required = ("utilization_pct", "memory_used_mib", "memory_total_mib", "temperature_c")
    if any(getattr(item, field) is None for item in window for field in required):
        return "missing_baseline_metrics"
    return None


def _detect(
    samples: tuple[GpuSample, ...], policy: Policy, *, sustained: bool
) -> list[tuple[str, str, str]]:
    latest = samples[-1]
    previous = samples[-2] if len(samples) >= 2 else latest
    candidates: list[tuple[str, str, str]] = []
    if latest.xid_code and previous.xid_code is not None and latest.xid_code != previous.xid_code:
        candidates.append(("gpu_xid_event", "new_xid_code", "high"))
    for field, signal, kind in (
        ("ecc_uncorrectable_total", "gpu_ecc_uncorrectable", "new_ecc_error"),
        ("cuda_oom_total", "gpu_vram_oom", "observed_cuda_oom"),
    ):
        current_count, old_count = getattr(latest, field), getattr(previous, field)
        if current_count is not None and old_count is not None and current_count > old_count:
            candidates.append((signal, kind, "high"))
    if latest.thermal_throttled:
        candidates.append(("gpu_temp_throttle", "observed_thermal_throttle", "high"))
    elif latest.temperature_c is not None and latest.temperature_c >= policy.temperature_c:
        candidates.append(("alert_trigger", "high_temperature", "medium"))
    if (
        latest.memory_used_mib is not None
        and latest.memory_total_mib is not None
        and latest.memory_used_mib / latest.memory_total_mib * 100 >= policy.memory_pressure_pct
    ):
        candidates.append(("alert_trigger", "memory_pressure", "medium"))
    if sustained and all(
        item.utilization_pct is not None and item.utilization_pct >= policy.saturation_pct
        for item in samples
    ):
        queues = [item.queue_depth for item in samples]
        if all(value is not None for value in queues):
            first, last = queues[0], queues[-1]
            if first is not None and last is not None and last > first:
                candidates.append(("gpu_util_saturated", "sustained_saturation_backlog", "medium"))
        else:
            candidates.append(("alert_trigger", "saturation_missing_queue_evidence", "low"))
    if sustained and all(
        item.utilization_pct is not None
        and item.utilization_pct <= policy.idle_utilization_pct
        and item.allocated is True
        for item in samples
    ):
        candidates.append(("gpu_util_zero_wasted", "allocated_idle_window", "low"))
    return candidates


def _event(
    samples: tuple[GpuSample, ...],
    signal: str,
    kind: str,
    severity: str,
    now: datetime,
    evidence_digest: str,
    policy_digest: str,
) -> Event:
    latest = samples[-1]
    key = _digest([latest.identity, kind, evidence_digest, policy_digest])
    return Event(
        schema_version="1.0.0",
        event_id=uuid5(NAMESPACE_URL, f"fdai-gpu-replay:{key}"),
        idempotency_key=f"gpu-replay:{key}",
        correlation_id=f"{latest.resource_ref}:{latest.gpu_id}",
        source=latest.source,
        event_type="anomaly_detected",
        resource_ref=latest.resource_ref,
        payload={
            "signal": signal,
            "finding_kind": kind,
            "severity": severity,
            "gpu_id": latest.gpu_id,
            "gpu_model": latest.model,
            "evidence_origin": "synthetic_replay",
            "evidence_digest": evidence_digest,
            "policy_digest": policy_digest,
            "sample_count": len(samples),
            "window_start": samples[0].observed_at.astimezone(UTC).isoformat(),
            "window_end": latest.observed_at.astimezone(UTC).isoformat(),
        },
        detected_at=latest.observed_at.astimezone(UTC),
        ingested_at=now.astimezone(UTC),
        incident_correlation=IncidentCorrelation.CORRELATE,
        mode=Mode.SHADOW,
    )


async def publish_findings(
    result: Analysis, *, bus: FindingPublisher, topic: str, validator: ContractValidator
) -> int:
    """Validate the entire batch before publishing; broker failures propagate.

    Replay-stable keys support consumer deduplication. No local state claims
    durable exactly-once delivery or effect verification.
    """
    if not topic.strip():
        raise ValueError("finding topic MUST be non-empty")
    payloads = [event.model_dump(mode="json") for event in result.events]
    for payload in payloads:
        validator.validate("event", payload)
    for event, payload in zip(result.events, payloads, strict=True):
        await bus.publish(topic, event.resource_ref or event.idempotency_key, payload)
    return len(payloads)
