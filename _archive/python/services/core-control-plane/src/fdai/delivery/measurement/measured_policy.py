"""Durable authority-free runner for model-swap and latency evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.measurement.latency_budget import (
    LatencyBudget,
    LatencyBudgetMonitor,
    LatencyObservation,
    LatencyOutcome,
    Tier,
)
from fdai.core.measurement.model_tracking import (
    ModelObservation,
    ModelSwapPolicy,
    SwapOutcome,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore

_INPUT_PREFIX = "measurement:phase4:evidence:"
_PROCESSED_PREFIX = "measurement:phase4:processed:"
_PAGE_SIZE = 256
_MAX_BATCHES = 4_096
_REQUIRED_TIERS = frozenset(Tier)
_DEFAULT_LATENCY_BUDGETS: dict[Tier, float] = {
    Tier.T0: 100.0,
    Tier.T1: 1_000.0,
    Tier.T2: 15_000.0,
}


@dataclass(frozen=True, slots=True)
class LatencyEvidence:
    tier: Tier
    reported_budget_p95_ms: float
    observation: LatencyObservation


@dataclass(frozen=True, slots=True)
class MeasuredPolicyBatch:
    batch_id: str
    observed_at: datetime
    complete: bool
    incumbent: ModelObservation | None
    challenger: ModelObservation | None
    latency: tuple[LatencyEvidence, ...]
    rollback_of: str | None = None

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("batch_id MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at MUST be timezone-aware")
        if self.rollback_of is not None and not self.rollback_of.strip():
            raise ValueError("rollback_of MUST be non-empty when provided")
        tiers = tuple(item.tier for item in self.latency)
        if len(tiers) != len(set(tiers)):
            raise ValueError("latency evidence MUST contain at most one row per tier")


@dataclass(frozen=True, slots=True)
class MalformedMeasuredPolicyBatch:
    evidence_id: str
    reason: str


class MeasuredPolicyBatchSource(Protocol):
    def batches(
        self,
    ) -> AsyncIterator[MeasuredPolicyBatch | MalformedMeasuredPolicyBatch]: ...


@dataclass(frozen=True, slots=True)
class MeasuredPolicyRunReport:
    processed_count: int
    rejected_count: int
    duplicate_count: int
    rollback_count: int


class StateStoreMeasuredPolicyBatchSource:
    """Read bounded durable model and latency evidence batches."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def batches(
        self,
    ) -> AsyncIterator[MeasuredPolicyBatch | MalformedMeasuredPolicyBatch]:
        return self._batches()

    async def _batches(
        self,
    ) -> AsyncIterator[MeasuredPolicyBatch | MalformedMeasuredPolicyBatch]:
        values: list[Mapping[str, object]] = []
        offset = 0
        total = 0
        while offset == 0 or offset < total:
            page, total = await self._store.read_state_page(
                _INPUT_PREFIX,
                limit=_PAGE_SIZE,
                offset=offset,
            )
            if total > _MAX_BATCHES:
                raise ValueError("measured policy input exceeds its bounded backlog")
            values.extend(page)
            offset += len(page)
            if not page:
                break
        for value in reversed(values):
            try:
                yield _parse_batch(value)
            except (TypeError, ValueError) as exc:
                yield MalformedMeasuredPolicyBatch(
                    evidence_id=_evidence_id(value),
                    reason=f"invalid_evidence:{type(exc).__name__}",
                )


class MeasuredPolicyRunner:
    """Evaluate paired evidence without changing model or execution bindings."""

    def __init__(
        self,
        *,
        source: MeasuredPolicyBatchSource,
        store: StateStore,
        model_policy: ModelSwapPolicy | None = None,
        latency_budgets: Mapping[Tier, float] | None = None,
        minimum_latency_samples: int = 20,
        stale_after_seconds: int = 86_400,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if minimum_latency_samples < 1 or stale_after_seconds < 1:
            raise ValueError("measurement runner bounds MUST be positive")
        self._source = source
        self._store = store
        self._model_policy = model_policy or ModelSwapPolicy()
        configured_budgets = dict(latency_budgets or _DEFAULT_LATENCY_BUDGETS)
        if set(configured_budgets) != _REQUIRED_TIERS:
            raise ValueError("latency_budgets MUST configure T0, T1, and T2")
        self._latency_budgets = configured_budgets
        self._minimum_latency_samples = minimum_latency_samples
        self._stale_after_seconds = stale_after_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run_once(self) -> MeasuredPolicyRunReport:
        processed = 0
        rejected = 0
        duplicates = 0
        rollbacks = 0
        async for batch in self._source.batches():
            if isinstance(batch, MalformedMeasuredPolicyBatch):
                applied = await self._store.write_state_with_audit_if_absent(
                    f"{_PROCESSED_PREFIX}malformed:{batch.evidence_id}",
                    {
                        "evidence_id": batch.evidence_id,
                        "status": "malformed",
                        "binding_changed": False,
                    },
                    {
                        "actor": "fdai.delivery.measurement.measured_policy",
                        "action_kind": "measurement.phase4.policy",
                        "idempotency_key": (f"measurement:phase4:malformed:{batch.evidence_id}"),
                        "mode": Mode.SHADOW.value,
                        "status": "malformed",
                        "reasons": [batch.reason],
                        "promotion_authority": False,
                        "execution_authority": False,
                        "recorded_at": self._clock().isoformat(),
                    },
                )
                if applied:
                    processed += 1
                    rejected += 1
                else:
                    duplicates += 1
                continue
            entry, status = self._evaluate(batch)
            applied = await self._store.write_state_with_audit_if_absent(
                f"{_PROCESSED_PREFIX}{batch.batch_id}",
                {
                    "batch_id": batch.batch_id,
                    "status": status,
                    "observed_at": batch.observed_at.isoformat(),
                    "binding_changed": False,
                },
                entry,
            )
            if not applied:
                duplicates += 1
                continue
            processed += 1
            if status in {"partial", "stale", "future"}:
                rejected += 1
            if status == "rollback_recorded":
                rollbacks += 1
        return MeasuredPolicyRunReport(
            processed_count=processed,
            rejected_count=rejected,
            duplicate_count=duplicates,
            rollback_count=rollbacks,
        )

    def _evaluate(self, batch: MeasuredPolicyBatch) -> tuple[dict[str, object], str]:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("measurement runner clock MUST be timezone-aware")
        status = "evaluated"
        reasons: list[str] = []
        if batch.observed_at > now:
            status = "future"
            reasons.append("evidence_after_runner_clock")
        elif (now - batch.observed_at).total_seconds() > self._stale_after_seconds:
            status = "stale"
            reasons.append("evidence_stale")
        elif batch.rollback_of is not None:
            status = "rollback_recorded"
            reasons.append("rollback_requires_prior_binding_review")
        elif (
            not batch.complete
            or batch.incumbent is None
            or batch.challenger is None
            or {item.tier for item in batch.latency} != _REQUIRED_TIERS
        ):
            status = "partial"
            reasons.append("evidence_batch_incomplete")

        model_result: dict[str, object] | None = None
        latency_results: list[dict[str, object]] = []
        if status == "evaluated":
            incumbent = batch.incumbent
            challenger = batch.challenger
            latency_results = self._latency_results(batch.latency)
            if incumbent is None or challenger is None:
                status = "partial"
                reasons.append("evidence_batch_incomplete")
            else:
                try:
                    model_decision = self._model_policy.evaluate(
                        incumbent=incumbent,
                        challenger=challenger,
                    )
                except ValueError:
                    status = "partial"
                    reasons.append("model_pair_invalid")
                else:
                    model_result = {
                        "incumbent_model_id": model_decision.incumbent_model_id,
                        "challenger_model_id": model_decision.challenger_model_id,
                        "outcome": model_decision.outcome.value,
                        "reasons": list(model_decision.reasons),
                        "promotion_review_required": (
                            model_decision.outcome is SwapOutcome.ADOPT_CHALLENGER
                        ),
                        "binding_changed": False,
                    }

        return (
            {
                "actor": "fdai.delivery.measurement.measured_policy",
                "action_kind": "measurement.phase4.policy",
                "idempotency_key": f"measurement:phase4:{batch.batch_id}",
                "mode": Mode.SHADOW.value,
                "batch_id": batch.batch_id,
                "observed_at": batch.observed_at.isoformat(),
                "status": status,
                "reasons": reasons,
                "rollback_of": batch.rollback_of,
                "model_swap": model_result,
                "latency": latency_results,
                "promotion_authority": False,
                "execution_authority": False,
                "recorded_at": self._clock().isoformat(),
            },
            status,
        )

    def _latency_results(
        self,
        evidence: tuple[LatencyEvidence, ...],
    ) -> list[dict[str, object]]:
        budgets = {
            tier: LatencyBudget(
                tier=tier,
                p95_ceiling_ms=ceiling,
            )
            for tier, ceiling in self._latency_budgets.items()
        }
        monitor = LatencyBudgetMonitor(
            budgets=budgets,
            min_sample_size=self._minimum_latency_samples,
        )
        results: list[dict[str, object]] = []
        for item in sorted(evidence, key=lambda value: value.tier.value):
            decision = monitor.evaluate(item.observation)
            results.append(
                {
                    "tier": item.tier.value,
                    "budget_p95_ms": self._latency_budgets[item.tier],
                    "reported_budget_p95_ms": item.reported_budget_p95_ms,
                    "sample_size": item.observation.sample_size,
                    "p50_ms": item.observation.p50_ms,
                    "p95_ms": item.observation.p95_ms,
                    "p99_ms": item.observation.p99_ms,
                    "outcome": decision.outcome.value,
                    "reasons": list(decision.reasons),
                    "available": decision.outcome is not LatencyOutcome.UNAVAILABLE,
                }
            )
        return results


def _parse_batch(value: Mapping[str, object]) -> MeasuredPolicyBatch:
    if value.get("schema_version") != "1.0.0":
        raise ValueError("measured policy batch schema_version MUST be 1.0.0")
    raw_latency = value.get("latency")
    if not isinstance(raw_latency, list):
        raise ValueError("measured policy latency MUST be an array")
    rollback_of = value.get("rollback_of")
    if rollback_of is not None and not isinstance(rollback_of, str):
        raise ValueError("measured policy rollback_of MUST be a string")
    complete = value.get("complete")
    if not isinstance(complete, bool):
        raise ValueError("measured policy complete MUST be a boolean")
    return MeasuredPolicyBatch(
        batch_id=_text(value, "batch_id"),
        observed_at=_datetime(value, "observed_at"),
        complete=complete,
        incumbent=_model_observation(value.get("incumbent")),
        challenger=_model_observation(value.get("challenger")),
        latency=tuple(_latency_evidence(item) for item in raw_latency),
        rollback_of=rollback_of,
    )


def _model_observation(value: object) -> ModelObservation | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("model observation MUST be an object")
    return ModelObservation(
        model_id=_text(value, "model_id"),
        scenario_set_version=_text(value, "scenario_set_version"),
        quality_score=_float(value, "quality_score"),
        cost_per_verified_answer=_float(value, "cost_per_verified_answer"),
        verifier_abstain_rate=_float(value, "verifier_abstain_rate"),
        mixed_model_disagreement_rate=_float(
            value,
            "mixed_model_disagreement_rate",
        ),
    )


def _latency_evidence(value: object) -> LatencyEvidence:
    if not isinstance(value, Mapping):
        raise ValueError("latency evidence MUST be an object")
    tier = Tier(_text(value, "tier"))
    sample_size = value.get("sample_size")
    if isinstance(sample_size, bool) or not isinstance(sample_size, int):
        raise ValueError("latency sample_size MUST be an integer")
    unavailable_reason = value.get("unavailable_reason")
    if unavailable_reason is not None and not isinstance(unavailable_reason, str):
        raise ValueError("latency unavailable_reason MUST be a string")
    return LatencyEvidence(
        tier=tier,
        reported_budget_p95_ms=_float(value, "budget_p95_ms"),
        observation=LatencyObservation(
            tier=tier,
            sample_size=sample_size,
            p50_ms=_optional_float(value, "p50_ms"),
            p95_ms=_optional_float(value, "p95_ms"),
            p99_ms=_optional_float(value, "p99_ms"),
            unavailable_reason=unavailable_reason,
        ),
    )


def _text(value: Mapping[str, object], name: str) -> str:
    raw = value.get(name)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"measured policy {name} MUST be non-empty")
    return raw


def _datetime(value: Mapping[str, object], name: str) -> datetime:
    raw = _text(value, name)
    try:
        resolved = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"measured policy {name} MUST be RFC 3339") from exc
    if resolved.tzinfo is None:
        raise ValueError(f"measured policy {name} MUST be timezone-aware")
    return resolved


def _float(value: Mapping[str, object], name: str) -> float:
    raw = value.get(name)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"measured policy {name} MUST be numeric")
    return float(raw)


def _optional_float(value: Mapping[str, object], name: str) -> float | None:
    return None if value.get(name) is None else _float(value, name)


def _evidence_id(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "LatencyEvidence",
    "MalformedMeasuredPolicyBatch",
    "MeasuredPolicyBatch",
    "MeasuredPolicyBatchSource",
    "MeasuredPolicyRunReport",
    "MeasuredPolicyRunner",
    "StateStoreMeasuredPolicyBatchSource",
]
