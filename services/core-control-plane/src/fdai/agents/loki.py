"""Loki - Chaos (Wave 5 behavior).

Loki schedules chaos experiments with a bounded blast_radius and
NEVER auto-executes. Every proposed experiment routes through Forseti
and Var as an HIL action; Loki merely emits the proposal.

Blast-radius accounting is deterministic: no matter how many
proposals come in per unit time, the cumulative in-flight target count
is capped by :pyattr:`blast_radius_cap`.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.loki_reservations import LokiReservationJournal
from fdai.agents._framework.loki_resilience import (
    RESILIENCE_SCORE_EVENT,
    resilience_score_candidate,
)
from fdai.agents._framework.pantheon import _LOKI
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.specialist_ingress import (
    CHAOS_ACTION_TYPES,
    CHAOS_SCHEDULE_EVENT,
    parse_chaos_schedule,
)
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.shared.providers.state_store import StateStore

#: Cap on the retained proposal log. Loki appends one entry per proposal for
#: the process lifetime; the log is only read for recent-accepted diagnostics,
#: so a bounded ring is sufficient and stops an unbounded leak on a
#: long-running chaos scheduler.
_MAX_PROPOSALS = 1_000
_MAX_HELD_PROPOSALS = 256
_MAX_RESILIENCE_SCORES = 512
_SAFE_CLOSURE_STATES = frozenset({"succeeded", "rejected", "deny_dropped", "rolled_back"})
_CHAOS_EVIDENCE_FIELDS = (
    "causal_hypothesis_ref",
    "refutation_query_ref",
    "impact_envelope_id",
    "recovery_plan_id",
    "dry_run_receipt",
)
_DEFAULT_RESERVATION_TTL = timedelta(minutes=30)
_CHAOS_OUTBOX_PREFIX = "pantheon/loki/chaos-outbox/"
_HELD_PREFIX = "pantheon/loki/held-proposals/"
_RESILIENCE_PREFIX = "pantheon/loki/resilience-scores/"
_MAX_CHAOS_TARGETS = 32
_MAX_CHAOS_IDENTIFIER_CHARS = 512


@dataclass
class ChaosProposal:
    experiment_id: str
    action_type: str
    targets: tuple[str, ...]
    accepted: bool
    reason: str
    requested_target_count: int = 0
    targets_truncated: bool = False
    causal_hypothesis_ref: str = ""
    impact_envelope_id: str = ""
    recovery_plan_id: str = ""


@dataclass(frozen=True, slots=True)
class _Reservation:
    action_type: str
    targets: tuple[str, ...]
    reserved_at: datetime


class Loki(Agent):
    """Wave-5 Loki: chaos scheduler with blast-radius cap."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        blast_radius_cap: int = 3,
        state_store: StateStore | None = None,
        clock: Callable[[], datetime] | None = None,
        reservation_ttl: timedelta = _DEFAULT_RESERVATION_TTL,
    ) -> None:
        super().__init__(spec=_LOKI)
        if reservation_ttl <= timedelta(0):
            raise ValueError("reservation_ttl MUST be positive")
        self.bus = bus
        self._cap = blast_radius_cap
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(tz=UTC))
        self._reservation_ttl = reservation_ttl
        self._in_flight_targets: set[str] = set()
        self._reservations: dict[str, _Reservation] = {}
        self._publishing_experiments: set[str] = set()
        self._reservation_journal = (
            LokiReservationJournal(state_store, blast_radius_cap=blast_radius_cap)
            if state_store is not None
            else None
        )
        self._state_store = state_store
        self.proposals: deque[ChaosProposal] = deque(maxlen=_MAX_PROPOSALS)
        self._held_proposals: deque[ChaosProposal] = deque(maxlen=_MAX_HELD_PROPOSALS)
        self._resilience_scores: dict[str, tuple[float, str]] = {}
        self._reservation_lock = asyncio.Lock()
        self._publication_locks: dict[str, asyncio.Lock] = {}

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.action-run":
            await self._release_from_action_run(payload)
            return
        if topic != "object.event":
            self.record_behavior("typed_message:ignored")
            return
        event_type = str(payload.get("event_type") or "")
        owner_behavior = (
            "chaos_schedule:invalid_producer"
            if event_type == CHAOS_SCHEDULE_EVENT
            else "resilience_score:invalid"
        )
        if require_topic_owner(self, topic, payload, behavior=owner_behavior):
            return
        if payload.get("event_type") == RESILIENCE_SCORE_EVENT:
            candidate = resilience_score_candidate(payload)
            if candidate is None:
                self.record_behavior("resilience_score:invalid")
                return
            if not await self._remember_resilience_score(candidate):
                return
            if await self._publish_proposal("object.resilience-score", candidate):
                self.record_behavior("resilience_score:published")
            return
        if payload.get("event_type") != CHAOS_SCHEDULE_EVENT:
            self.record_behavior("chaos_schedule:ignored_event")
            return
        signal = parse_chaos_schedule(payload)
        if signal is None:
            self.record_behavior("chaos_schedule:invalid")
            return
        self.record_behavior("chaos_schedule:accepted")
        await self.propose_experiment(
            experiment_id=signal.experiment_id,
            action_type=signal.action_type,
            targets=signal.targets,
            correlation_id=signal.correlation_id,
        )

    async def rehydrate(self) -> int:
        """Restore durable target reservations and advisory projections before consumers start."""
        restored = 0
        if self._reservation_journal is not None:
            self._in_flight_targets = set(await self._reservation_journal.snapshot())
            restored += len(self._in_flight_targets)
        if self._state_store is None:
            return restored
        for record in await self._state_store.read_states(_HELD_PREFIX, limit=_MAX_HELD_PROPOSALS):
            proposal = _proposal_from_record(record)
            if proposal is not None:
                self._held_proposals.append(proposal)
                restored += 1
        for record in await self._state_store.read_states(
            _RESILIENCE_PREFIX,
            limit=_MAX_RESILIENCE_SCORES,
        ):
            resource_id = str(record.get("resource_id") or "")
            score = record.get("score")
            observed_at = str(record.get("observed_at") or "")
            if resource_id and isinstance(score, int | float) and observed_at:
                self._resilience_scores[resource_id] = (float(score), observed_at)
                restored += 1
        return restored

    async def _release_from_action_run(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Thor":
            self.record_behavior("chaos_reservation:invalid_closure_producer")
            return
        if payload.get("state") not in _SAFE_CLOSURE_STATES:
            self.record_behavior("chaos_reservation:ignored_nonterminal_closure")
            return
        params = payload.get("params")
        if not isinstance(params, dict):
            self.record_behavior("chaos_reservation:malformed_closure")
            return
        experiment_id = str(params.get("experiment_id") or "")
        action_type = str(payload.get("action_type") or "")
        raw_targets = params.get("targets")
        targets = (
            tuple(target for target in raw_targets if isinstance(target, str) and target)
            if isinstance(raw_targets, list)
            else ()
        )
        if not experiment_id or not action_type or not targets:
            self.record_behavior("chaos_reservation:malformed_closure")
            return
        try:
            released = await self._release_reservation(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=targets,
            )
        except ValueError:
            self.record_behavior("chaos_reservation:closure_mismatch")
            return
        if released:
            self.record_behavior("chaos_reservation:released")
        else:
            self.record_behavior("chaos_reservation:missing_closure")

    # ---- experiment scheduling ----------------------------------------

    async def propose_experiment(
        self,
        *,
        experiment_id: str,
        action_type: str,
        targets: tuple[str, ...],
        correlation_id: str = "",
        causal_hypothesis_ref: str = "",
        refutation_query_ref: str = "",
        impact_envelope_id: str = "",
        recovery_plan_id: str = "",
        dry_run_receipt: str = "",
    ) -> ChaosProposal:
        requested_target_count = len(targets)
        if action_type not in CHAOS_ACTION_TYPES:
            proposal = ChaosProposal(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=(),
                accepted=False,
                reason="invalid_action_type",
                requested_target_count=requested_target_count,
            )
            self.proposals.append(proposal)
            self.record_behavior("chaos_proposal:invalid_action_type")
            return proposal
        bounded_targets = _bounded_targets(targets)
        if bounded_targets is None:
            proposal = ChaosProposal(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=(),
                accepted=False,
                reason="invalid_targets",
                requested_target_count=requested_target_count,
            )
            self.proposals.append(proposal)
            self.record_behavior("chaos_proposal:invalid_targets")
            return proposal
        targets = bounded_targets
        evidence = {
            "causal_hypothesis_ref": causal_hypothesis_ref,
            "refutation_query_ref": refutation_query_ref,
            "impact_envelope_id": impact_envelope_id,
            "recovery_plan_id": recovery_plan_id,
            "dry_run_receipt": dry_run_receipt,
        }
        if any(not str(evidence[field]).strip() for field in _CHAOS_EVIDENCE_FIELDS):
            proposal = ChaosProposal(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=(),
                accepted=False,
                reason="incomplete_evidence",
                requested_target_count=requested_target_count,
            )
            self._held_proposals.append(proposal)
            await self._persist_held_proposal(proposal)
            self.record_behavior("chaos_proposal:held_incomplete")
            return proposal
        async with self._reservation_lock:
            # Enforce cap BEFORE emitting anything so a proposal storm does
            # not exceed the declared radius.
            if self._reservation_journal is not None:
                reservation = await self._reservation_journal.reserve(
                    experiment_id=experiment_id,
                    action_type=action_type,
                    targets=targets,
                    reserved_at=self._now().isoformat(),
                )
                self._in_flight_targets = set(reservation.occupied)
                selected = reservation.targets
                if reservation.duplicate:
                    self.record_behavior("chaos_reservation:replayed")
            else:
                available = self._cap - len(self._in_flight_targets)
                selected = tuple(t for t in targets if t not in self._in_flight_targets)[:available]
            targets_truncated = len(selected) < requested_target_count
            if targets_truncated and selected:
                self.record_behavior("chaos_reservation:targets_truncated")
            if not selected:
                proposal = ChaosProposal(
                    experiment_id=experiment_id,
                    action_type=action_type,
                    targets=(),
                    accepted=False,
                    reason=(
                        "blast_radius_full"
                        if len(self._in_flight_targets) >= self._cap
                        else "no_new_targets"
                    ),
                    requested_target_count=requested_target_count,
                    targets_truncated=targets_truncated,
                )
                self.proposals.append(proposal)
                self.record_behavior(f"chaos_proposal:{proposal.reason}")
                return proposal
            self._in_flight_targets.update(selected)
            self._reservations[experiment_id] = _Reservation(
                action_type=action_type,
                targets=selected,
                reserved_at=self._now(),
            )
        proposal = ChaosProposal(
            experiment_id=experiment_id,
            action_type=action_type,
            targets=selected,
            accepted=True,
            reason="within_radius",
            requested_target_count=requested_target_count,
            targets_truncated=targets_truncated,
            causal_hypothesis_ref=causal_hypothesis_ref,
            impact_envelope_id=impact_envelope_id,
            recovery_plan_id=recovery_plan_id,
        )
        payload = {
            "producer_principal": "Loki",
            "correlation_id": correlation_id or experiment_id,
            "idempotency_key": stable_idempotency_key(
                "chaos-experiment",
                correlation_id or experiment_id,
                experiment_id,
                action_type,
                selected,
                evidence,
            ),
            "experiment_id": experiment_id,
            "action_type": action_type,
            "targets": list(selected),
            "requested_target_count": requested_target_count,
            "targets_truncated": targets_truncated,
            "blast_radius_used": len(selected),
            "causal_hypothesis_ref": causal_hypothesis_ref,
            "refutation_query_ref": refutation_query_ref,
            "impact_envelope_id": impact_envelope_id,
            "recovery_plan_id": recovery_plan_id,
            "dry_run_receipt": dry_run_receipt,
            "human_approval_required": True,
        }
        self._publishing_experiments.add(experiment_id)
        published = False
        try:
            published = await self._publish_chaos_once(experiment_id, payload)
        except asyncio.CancelledError:
            await self._release_reservation(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=selected,
            )
            self.record_behavior("chaos_proposal:publication_cancelled")
            raise
        finally:
            self._publishing_experiments.discard(experiment_id)
        if not published:
            await self._release_reservation(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=selected,
            )
            self.proposals.append(
                ChaosProposal(
                    experiment_id=experiment_id,
                    action_type=action_type,
                    targets=(),
                    accepted=False,
                    reason="publication_unavailable",
                    requested_target_count=requested_target_count,
                    targets_truncated=targets_truncated,
                    causal_hypothesis_ref=causal_hypothesis_ref,
                    impact_envelope_id=impact_envelope_id,
                    recovery_plan_id=recovery_plan_id,
                )
            )
            self.record_behavior("chaos_proposal:publication_unavailable")
            return self.proposals[-1]
        self.proposals.append(proposal)
        return proposal

    async def _publish_chaos_once(self, experiment_id: str, payload: dict[str, Any]) -> bool:
        async with self._lock_for_publication(experiment_id):
            if self._state_store is None:
                return self.bus is None or await self._publish_proposal(
                    "object.chaos-experiment",
                    payload,
                )
            outbox_key = f"{_CHAOS_OUTBOX_PREFIX}{_digest(experiment_id)}"
            existing = await self._state_store.read_state(outbox_key)
            if existing is not None:
                if existing.get("state") == "published":
                    self.record_behavior("chaos_proposal:duplicate_published")
                    return True
                stored_payload = existing.get("payload")
                if not isinstance(stored_payload, dict):
                    raise ValueError("Loki chaos outbox payload is malformed")
                payload = dict(stored_payload)
            else:
                await self._state_store.write_state_if_absent(
                    outbox_key,
                    {
                        "schema_version": "1.0.0",
                        "revision": 1,
                        "state": "pending",
                        "experiment_id": experiment_id,
                        "idempotency_key": str(payload.get("idempotency_key") or ""),
                        "payload": dict(payload),
                    },
                )
            if self.bus is None:
                return True
            if not await self._publish_proposal("object.chaos-experiment", payload):
                return False
            await self._state_store.write_state(
                outbox_key,
                {
                    "schema_version": "1.0.0",
                    "revision": 2,
                    "state": "published",
                    "experiment_id": experiment_id,
                    "idempotency_key": str(payload.get("idempotency_key") or ""),
                    "payload": dict(payload),
                },
            )
            return True

    async def _persist_held_proposal(self, proposal: ChaosProposal) -> None:
        if self._state_store is None:
            return
        await self._state_store.write_state(
            f"{_HELD_PREFIX}{_digest(proposal.experiment_id)}",
            {
                "schema_version": "1.0.0",
                "revision": 1,
                "experiment_id": proposal.experiment_id,
                "action_type": proposal.action_type,
                "targets": list(proposal.targets),
                "accepted": proposal.accepted,
                "reason": proposal.reason,
                "requested_target_count": proposal.requested_target_count,
                "targets_truncated": proposal.targets_truncated,
                "causal_hypothesis_ref": proposal.causal_hypothesis_ref,
                "impact_envelope_id": proposal.impact_envelope_id,
                "recovery_plan_id": proposal.recovery_plan_id,
            },
        )

    def _release_targets(self, targets: tuple[str, ...]) -> None:
        """Release process-local slots only from validated terminal closure."""
        for t in targets:
            self._in_flight_targets.discard(t)

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Loki clock MUST return a timezone-aware datetime")
        return current

    async def _remember_resilience_score(self, candidate: dict[str, Any]) -> bool:
        resource_id = str(candidate["resource_id"])
        observed_at = str(candidate["observed_at"])
        existing = self._resilience_scores.get(resource_id)
        parsed_observed_at = _parse_time(observed_at)
        if existing is not None and parsed_observed_at < _parse_time(existing[1]):
            self.record_behavior("resilience_score:stale")
            return False
        next_scores = dict(self._resilience_scores)
        if len(next_scores) >= _MAX_RESILIENCE_SCORES and resource_id not in next_scores:
            next_scores.pop(next(iter(next_scores)))
        next_scores[resource_id] = (
            float(candidate["score"]),
            observed_at,
        )
        if self._state_store is not None:
            await self._state_store.write_state(
                f"{_RESILIENCE_PREFIX}{_digest(resource_id)}",
                {
                    "schema_version": "1.0.0",
                    "revision": 1,
                    "resource_id": resource_id,
                    "score": float(candidate["score"]),
                    "observed_at": parsed_observed_at.isoformat(),
                },
            )
        self._resilience_scores = next_scores
        return True

    async def _release_reservation(
        self,
        *,
        experiment_id: str,
        action_type: str,
        targets: tuple[str, ...],
    ) -> bool:
        if self._reservation_journal is not None:
            result = await self._reservation_journal.release(
                experiment_id=experiment_id,
                action_type=action_type,
                targets=targets,
            )
            if result is None:
                return False
            self._in_flight_targets = set(result.occupied)
            self._reservations.pop(experiment_id, None)
            return True
        existing = self._reservations.get(experiment_id)
        if existing is None:
            return False
        if existing.action_type != action_type or existing.targets != targets:
            raise ValueError("chaos completion does not match its reservation")
        self._release_targets(targets)
        del self._reservations[experiment_id]
        return True

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        cutoff = self._now() - self._reservation_ttl
        async with self._reservation_lock:
            if self._reservation_journal is not None:
                expired = await self._reservation_journal.expire_stale(cutoff=cutoff.isoformat())
                if expired.targets:
                    self._in_flight_targets = set(expired.occupied)
                    self.record_behavior("chaos_reservation:expired", len(expired.targets))
                return
            expired_experiments = [
                experiment_id
                for experiment_id, reservation in self._reservations.items()
                if reservation.reserved_at <= cutoff
                and experiment_id not in self._publishing_experiments
            ]
            if not expired_experiments:
                return
            expired_targets: list[str] = []
            for experiment_id in expired_experiments:
                reservation = self._reservations.pop(experiment_id)
                expired_targets.extend(reservation.targets)
            self._release_targets(tuple(expired_targets))
            self.record_behavior("chaos_reservation:expired", len(expired_targets))

    def health(self) -> dict[str, Any]:
        return {
            "agent": "Loki",
            "status": "ok",
            "ingress": {
                "chaos_schedule": "active",
                "resilience_score": "active",
                "reason": "event_subscriptions_bound_by_runtime",
            },
            "reservation": {
                "durability": "durable"
                if self._reservation_journal is not None
                else "process_local",
                "blast_radius_cap": self._cap,
                "in_flight_target_count": len(self._in_flight_targets),
            },
            "held_proposals": len(self._held_proposals),
            "behavior": self.behavior_snapshot(),
        }

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Chaos answers rest on proposals made; the cap alone is config."""
        return bool(self.proposals or self._resilience_scores)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        accepted = [p for p in self.proposals if p.accepted]
        facts = {
            **capability_facts(self.spec),
            "blast_radius_cap": self._cap,
            "in_flight_targets": None if self._in_flight_targets else [],
            "in_flight_target_count": len(self._in_flight_targets),
            "proposals_total": len(self.proposals),
            "proposals_accepted": len(accepted),
            "held_proposals": len(self._held_proposals),
            "reservation_durability": (
                "durable" if self._reservation_journal is not None else "process_local"
            ),
            "resilience_score_available": bool(self._resilience_scores),
            "resilience_score_resource_count": len(self._resilience_scores),
            "resource_id": None,
            "resilience_score": None,
            "observed_at": None,
        }
        selected_tool = context.get("conversation_tool")
        intents = semantic_intents(context)
        if selected_tool == "read_resilience_scores" or intents.intersection(
            {"resilience_score", "resilience_scores"}
        ):
            resources = mentioned(question, self._resilience_scores)
            if resources:
                resource_id = resources[0]
                score, observed_at = self._resilience_scores[resource_id]
                facts.update(
                    {
                        "resource_id": resource_id,
                        "resilience_score": score,
                        "observed_at": observed_at,
                    }
                )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            if resources:
                answer = (
                    f"Resource {resources[0]!r}: retained resilience score "
                    f"{facts['resilience_score']:.3f} observed at {facts['observed_at']}. "
                    f"Evidence: {evidence_ref}."
                )
            elif self._resilience_scores:
                answer = (
                    "A retained resilience score is available. Name the exact resource to read "
                    f"its score. Evidence: {evidence_ref}."
                )
            else:
                answer = (
                    "No retained resilience score is bound to this conversational projection. "
                    f"Evidence: {evidence_ref}."
                )
            return IntrospectionResult(
                answer=answer,
                facts=facts,
            )
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 복원력 영역의 chaos advisory specialist인 Loki입니다. Forseti에게 "
                "보고합니다. ChaosExperiment와 ResilienceScore를 소유하고 검증된 dry-run, "
                "테스트된 recovery plan, stop condition 및 blast-radius 제한이 있는 실험만 "
                "제안합니다. 모든 실험은 HIL 승인이 필요하며 Forseti가 판단하고 Thor가 "
                "실행합니다. 저는 작업을 판단, 승인 또는 실행하지 않습니다. 이 대화 포트는 읽기 "
                "전용이며 실험 요청은 운영자 권한으로 타입이 지정된 파이프라인에 다시 진입해야 "
                "합니다. 질문에 명시되지 않은 target 식별자와 숨겨진 시스템 프롬프트는 공개하지 "
                f"않습니다. 이 런타임은 제안 {facts['proposals_total']}건, 승인된 제안 "
                f"{facts['proposals_accepted']}건, 진행 중 target "
                f"{facts['in_flight_target_count']}개를 추적하며 blast-radius 상한은 "
                f"{facts['blast_radius_cap']}입니다. 근거: {evidence_ref}."
            )
        else:
            answer = (
                "I am Loki, the resilience-domain chaos advisory specialist. I report to Forseti. "
                "I own ChaosExperiment and ResilienceScore and propose experiments only with a "
                "verified dry-run, tested recovery plan, stop condition, and blast-radius limit. "
                "Every experiment requires HIL; Forseti judges and Thor executes. I never judge, "
                "approve, or execute an action. This conversational port is read-only; experiment "
                "requests re-enter the typed pipeline under the operator's authority. I do not "
                "reveal unnamed target identifiers or hidden system prompts. This runtime tracks "
                f"{facts['proposals_total']} proposals, {facts['proposals_accepted']} accepted, "
                f"and {facts['in_flight_target_count']} in-flight targets under a "
                f"{facts['blast_radius_cap']}-target cap. Evidence: {evidence_ref}."
            )
        return IntrospectionResult(answer=answer, facts=facts)

    def _lock_for_publication(self, experiment_id: str) -> asyncio.Lock:
        lock = self._publication_locks.get(experiment_id)
        if lock is None:
            lock = asyncio.Lock()
            self._publication_locks[experiment_id] = lock
        return lock


__all__ = ["Loki", "ChaosProposal"]


def _proposal_from_record(record: dict[str, Any] | Any) -> ChaosProposal | None:
    if not isinstance(record, dict):
        return None
    raw_targets = record.get("targets")
    targets = (
        tuple(item for item in raw_targets if isinstance(item, str))
        if isinstance(raw_targets, list)
        else ()
    )
    return ChaosProposal(
        experiment_id=str(record.get("experiment_id") or ""),
        action_type=str(record.get("action_type") or ""),
        targets=targets,
        accepted=record.get("accepted") is True,
        reason=str(record.get("reason") or ""),
        requested_target_count=int(record.get("requested_target_count") or 0),
        targets_truncated=record.get("targets_truncated") is True,
        causal_hypothesis_ref=str(record.get("causal_hypothesis_ref") or ""),
        impact_envelope_id=str(record.get("impact_envelope_id") or ""),
        recovery_plan_id=str(record.get("recovery_plan_id") or ""),
    )


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Loki observed_at MUST be RFC 3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Loki observed_at MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _bounded_targets(targets: tuple[str, ...]) -> tuple[str, ...] | None:
    if not 1 <= len(targets) <= _MAX_CHAOS_TARGETS:
        return None
    normalized: list[str] = []
    for target in targets:
        if not isinstance(target, str):
            return None
        stripped = target.strip()
        if (
            not stripped
            or len(stripped) > _MAX_CHAOS_IDENTIFIER_CHARS
            or any((ord(char) < 32 and char not in "\t") or ord(char) == 127 for char in stripped)
        ):
            return None
        normalized.append(stripped)
    if len(set(normalized)) != len(normalized):
        return None
    return tuple(normalized)
