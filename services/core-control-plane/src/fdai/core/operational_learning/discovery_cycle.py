"""Bounded, replayable scheduling for one autonomous rule-discovery cycle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.shared.providers.state_store import StateStore

from .discovery_contracts import (
    DiscoveryCandidate,
    DiscoveryCandidateDecision,
    DiscoveryCandidateIntegrator,
    DiscoveryCandidateState,
    DiscoveryCandidateVerifier,
    DiscoveryCrossCheckModel,
    DiscoveryCycleConfig,
    DiscoveryCycleMetrics,
    DiscoveryCycleReport,
    DiscoveryHypothesisModel,
    DiscoveryObservationBatch,
    DiscoverySignalKind,
    DiscoverySignalSource,
    DiscoveryVerificationReceipt,
    digest,
    require_aware,
)
from .discovery_persistence import (
    candidate_record,
    cycle_audit_record,
    cycle_report_from_record,
    decision_record,
    interval_bucket_start,
    signal_record,
)

_CYCLE_PREFIX = "operational-learning:discovery-cycle:"
_METRIC_PREFIX = "operational-learning:discovery-metrics:"


class DiscoveryCycleScheduler:
    """Run one due cycle and persist every stage without catalog authority."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        source: DiscoverySignalSource,
        primary_model: DiscoveryHypothesisModel,
        cross_check_models: tuple[DiscoveryCrossCheckModel, ...],
        verifier: DiscoveryCandidateVerifier,
        integrator: DiscoveryCandidateIntegrator,
        config: DiscoveryCycleConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = state_store
        self._source = source
        self._primary = primary_model
        self._reviewers = cross_check_models
        self._verifier = verifier
        self._integrator = integrator
        self._config = config or DiscoveryCycleConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        models: tuple[DiscoveryHypothesisModel | DiscoveryCrossCheckModel, ...] = (
            primary_model,
            *cross_check_models,
        )
        if len(models) < 2:
            raise ValueError("discovery cycle requires at least two model families")
        identities = {model.model_identity for model in models}
        families = {model.model_family for model in models}
        if any(not value for value in identities | families):
            raise ValueError("discovery model identities and families MUST be non-empty")
        if len(identities) != len(models):
            raise ValueError("discovery model identities MUST be distinct")
        if len(families) != len(models):
            raise ValueError("discovery model families MUST be distinct")

    async def run_due(self, *, scheduled_for: datetime) -> DiscoveryCycleReport:
        """Run or replay the stable interval bucket containing ``scheduled_for``."""

        require_aware(scheduled_for, "scheduled_for")
        bucket_start = interval_bucket_start(scheduled_for, self._config.interval_seconds)
        cycle_id = digest(
            {
                "schedule_id": self._config.schedule_id,
                "scheduled_for": bucket_start.isoformat(),
            }
        )
        key = f"{_CYCLE_PREFIX}{cycle_id}"
        current = self._new_record(cycle_id, bucket_start)
        created = await self._store.write_state_with_audit_if_absent(
            key,
            current,
            cycle_audit_record(current),
        )
        if not created:
            existing = await self._store.read_state(key)
            if existing is None:
                raise RuntimeError("discovery cycle claim disappeared")
            if existing.get("status") not in {"completed", "failed"}:
                raise RuntimeError("discovery cycle is already in progress")
            return cycle_report_from_record(existing, replayed=True)

        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                batch = await self._observe(bucket_start)
                current = await self._transition(
                    key,
                    current,
                    stage="observe",
                    signal_count=len(batch.signals),
                    signal_refs=tuple(signal_record(item) for item in batch.signals),
                )
                candidates = await self._hypothesize(batch)
                current = await self._transition(
                    key,
                    current,
                    stage="hypothesize",
                    candidate_count=len(candidates),
                    candidate_refs=tuple(candidate_record(item) for item in candidates),
                )
                decisions, verified = await self._verify_candidates(batch, candidates)
                current = await self._transition(
                    key,
                    current,
                    stage="verify",
                    decisions=decisions,
                    verified_count=len(verified),
                )
                integrated = await self._integrate_candidates(verified)
                final_decisions = tuple(
                    integrated.get(decision.candidate_digest, decision) for decision in decisions
                )
                metrics = _metrics(batch, candidates, verified_count=len(verified))
                current = await self._transition(
                    key,
                    current,
                    status="completed",
                    stage="integrate",
                    decisions=final_decisions,
                    metrics=metrics,
                )
                await self._publish_metrics(cycle_id, metrics)
                await self._retain_bounded_history()
                return cycle_report_from_record(current)
        except Exception as exc:
            await self._transition(
                key,
                current,
                status="failed",
                stage=str(current["stage"]),
                failure_kind=type(exc).__name__,
            )
            raise

    async def _observe(self, bucket_start: datetime) -> DiscoveryObservationBatch:
        window_end = bucket_start + timedelta(seconds=self._config.interval_seconds)
        batch = await self._source.observe(
            window_start=bucket_start,
            window_end=window_end,
            limit=self._config.max_signals,
        )
        if not batch.complete:
            raise RuntimeError("discovery observation window is incomplete")
        if batch.window_start != bucket_start or batch.window_end != window_end:
            raise ValueError("discovery observation window does not match the cycle bucket")
        if len(batch.signals) > self._config.max_signals:
            raise ValueError("discovery observation signal limit exceeded")
        return batch

    async def _hypothesize(
        self,
        batch: DiscoveryObservationBatch,
    ) -> tuple[DiscoveryCandidate, ...]:
        candidates = await self._primary.hypothesize(batch)
        if not isinstance(candidates, tuple):
            raise TypeError("discovery hypothesis model MUST return a tuple")
        if len(candidates) > self._config.max_candidates:
            raise ValueError("discovery candidate limit exceeded")
        signal_ids = {signal.signal_id for signal in batch.signals}
        if any(not set(item.source_signal_ids) <= signal_ids for item in candidates):
            raise ValueError("discovery candidate cites an unobserved signal")
        if len({item.digest for item in candidates}) != len(candidates):
            raise ValueError("discovery candidates MUST be unique")
        return candidates

    async def _verify_candidates(
        self,
        batch: DiscoveryObservationBatch,
        candidates: tuple[DiscoveryCandidate, ...],
    ) -> tuple[
        tuple[DiscoveryCandidateDecision, ...],
        tuple[tuple[DiscoveryCandidate, DiscoveryVerificationReceipt], ...],
    ]:
        decisions: list[DiscoveryCandidateDecision] = []
        verified: list[tuple[DiscoveryCandidate, DiscoveryVerificationReceipt]] = []
        for candidate in candidates:
            reviews = await asyncio.gather(
                *(reviewer.review(candidate, batch) for reviewer in self._reviewers)
            )
            if any(review.candidate_digest != candidate.digest for review in reviews):
                decisions.append(_held(candidate, "mixed_model_candidate_digest_mismatch"))
                continue
            if any(not review.approved for review in reviews):
                decisions.append(_held(candidate, "mixed_model_disagreement"))
                continue
            receipt = await self._verifier.verify(candidate, batch)
            if receipt.candidate_digest != candidate.digest:
                raise ValueError("discovery verifier receipt digest conflict")
            if not receipt.passed:
                decisions.append(
                    DiscoveryCandidateDecision(
                        candidate_digest=candidate.digest,
                        state=DiscoveryCandidateState.REJECTED,
                        reason=receipt.reason,
                    )
                )
                continue
            decisions.append(_held(candidate, "verified_awaiting_integration"))
            verified.append((candidate, receipt))
        return tuple(decisions), tuple(verified)

    async def _integrate_candidates(
        self,
        verified: tuple[tuple[DiscoveryCandidate, DiscoveryVerificationReceipt], ...],
    ) -> dict[str, DiscoveryCandidateDecision]:
        decisions: dict[str, DiscoveryCandidateDecision] = {}
        for candidate, verification in verified:
            receipt = await self._integrator.integrate(candidate, verification)
            if receipt.candidate_digest != candidate.digest:
                raise ValueError("discovery integration receipt digest conflict")
            decisions[candidate.digest] = DiscoveryCandidateDecision(
                candidate_digest=candidate.digest,
                state=DiscoveryCandidateState.INTEGRATED,
                reason=("existing_review" if receipt.already_existed else "new_review"),
                review_ref=receipt.review_ref,
            )
        return decisions

    async def _transition(
        self,
        key: str,
        current: Mapping[str, Any],
        *,
        stage: str,
        status: str | None = None,
        signal_count: int | None = None,
        signal_refs: tuple[dict[str, object], ...] | None = None,
        candidate_count: int | None = None,
        candidate_refs: tuple[dict[str, object], ...] | None = None,
        verified_count: int | None = None,
        decisions: tuple[DiscoveryCandidateDecision, ...] | None = None,
        metrics: DiscoveryCycleMetrics | None = None,
        failure_kind: str | None = None,
    ) -> dict[str, object]:
        revision = int(current["revision"])
        updated = dict(current)
        updated.update(
            {
                "revision": revision + 1,
                "status": status or current["status"],
                "stage": stage,
                "updated_at": self._now().isoformat(),
            }
        )
        optional = {
            "signal_count": signal_count,
            "candidate_count": candidate_count,
            "verified_count": verified_count,
            "failure_kind": failure_kind,
        }
        updated.update({name: value for name, value in optional.items() if value is not None})
        if signal_refs is not None:
            updated["signal_refs"] = list(signal_refs)
        if candidate_refs is not None:
            updated["candidate_refs"] = list(candidate_refs)
        if decisions is not None:
            updated["decisions"] = [decision_record(item) for item in decisions]
        if metrics is not None:
            updated["metrics"] = metrics.to_mapping()
        applied = await self._store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=revision,
            audit_entry=cycle_audit_record(updated),
        )
        if not applied:
            raise RuntimeError("discovery cycle revision conflict")
        return updated

    async def _publish_metrics(
        self,
        cycle_id: str,
        metrics: DiscoveryCycleMetrics,
    ) -> None:
        value = {
            "schema_version": "1.0.0",
            "kind": "rule_discovery_cycle_metrics",
            "cycle_id": cycle_id,
            "schedule_id": self._config.schedule_id,
            **metrics.to_mapping(),
            "grants_authority": False,
        }
        key = f"{_METRIC_PREFIX}{cycle_id}"
        created = await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {**value, "principal": "Norns", "action_kind": "rule_discovery.metrics"},
        )
        if not created and await self._store.read_state(key) != value:
            raise ValueError("discovery metrics idempotency conflict")

    async def _retain_bounded_history(self) -> None:
        await self._store.delete_states_beyond(
            _CYCLE_PREFIX,
            retain_newest=self._config.retain_cycles,
        )
        await self._store.delete_states_beyond(
            _METRIC_PREFIX,
            retain_newest=self._config.retain_cycles,
        )

    def _new_record(self, cycle_id: str, bucket_start: datetime) -> dict[str, object]:
        now = self._now().isoformat()
        return {
            "schema_version": "1.0.0",
            "kind": "rule_discovery_cycle",
            "cycle_id": cycle_id,
            "schedule_id": self._config.schedule_id,
            "scheduled_for": bucket_start.isoformat(),
            "status": "running",
            "stage": "scheduled",
            "revision": 1,
            "signal_count": 0,
            "signal_refs": [],
            "candidate_count": 0,
            "candidate_refs": [],
            "verified_count": 0,
            "decisions": [],
            "metrics": None,
            "failure_kind": None,
            "started_at": now,
            "updated_at": now,
            "model_bindings": [
                {
                    "role": "primary",
                    "model_identity": self._primary.model_identity,
                    "model_family": self._primary.model_family,
                },
                *[
                    {
                        "role": "cross_check",
                        "model_identity": reviewer.model_identity,
                        "model_family": reviewer.model_family,
                    }
                    for reviewer in self._reviewers
                ],
            ],
            "grants_authority": False,
        }

    def _now(self) -> datetime:
        value = self._clock()
        require_aware(value, "discovery cycle clock")
        return value.astimezone(UTC)


def _metrics(
    batch: DiscoveryObservationBatch,
    candidates: tuple[DiscoveryCandidate, ...],
    *,
    verified_count: int,
) -> DiscoveryCycleMetrics:
    count = len(candidates)
    override_ids = {
        signal.signal_id for signal in batch.signals if signal.kind is DiscoverySignalKind.OVERRIDE
    }
    override_count = sum(
        bool(set(candidate.source_signal_ids) & override_ids) for candidate in candidates
    )
    retirement_count = sum(candidate.proposal_kind == "retirement" for candidate in candidates)
    return DiscoveryCycleMetrics(
        candidates_per_cycle=count,
        gate_pass_rate=verified_count / count if count else 0.0,
        override_trigger_rate=override_count / count if count else 0.0,
        retirement_rate=retirement_count / count if count else 0.0,
    )


def _held(candidate: DiscoveryCandidate, reason: str) -> DiscoveryCandidateDecision:
    return DiscoveryCandidateDecision(
        candidate_digest=candidate.digest,
        state=DiscoveryCandidateState.HELD,
        reason=reason,
    )


__all__ = ["DiscoveryCycleScheduler"]
