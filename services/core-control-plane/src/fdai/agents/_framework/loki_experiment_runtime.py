"""Chaos experiment proposal and publication mixin for Loki."""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.loki_constants import (
    _CHAOS_EVIDENCE_FIELDS,
    _CHAOS_OUTBOX_PREFIX,
    _HELD_PREFIX,
    _MAX_CHAOS_IDENTIFIER_CHARS,
    _MAX_CHAOS_TARGETS,
    _MAX_HELD_PROPOSALS,
    _MAX_RESILIENCE_SCORES,
    _RESILIENCE_PREFIX,
    _SAFE_CLOSURE_STATES,
)
from fdai.agents._framework.loki_reservations import LokiReservationJournal
from fdai.agents._framework.loki_runtime_records import (
    ChaosProposal,
    _parse_time,
    _Reservation,
)
from fdai.agents._framework.loki_schedule_runtime import _proposal_from_record
from fdai.agents._framework.specialist_ingress import CHAOS_ACTION_TYPES
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.agents._framework.bus import PantheonBus


class LokiExperimentRuntimeMixin:
    """Propose bounded chaos experiments without execution authority."""

    _reservation_journal: LokiReservationJournal | None
    _state_store: StateStore | None
    _held_proposals: deque[ChaosProposal]
    proposals: deque[ChaosProposal]
    _reservation_lock: asyncio.Lock
    _cap: int
    _blast_radius_attempts: int
    _blast_radius_adherent_attempts: int
    _reservations: dict[str, _Reservation]
    _publishing_experiments: set[str]
    bus: PantheonBus | None
    _resilience_experiment_scores: dict[str, dict[str, float]]
    _publication_lock_refs: dict[str, int]
    _publication_locks: dict[str, asyncio.Lock]
    _resilience_scores: dict[str, tuple[float, str]]

    if TYPE_CHECKING:

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        def _now(self) -> datetime: ...

        async def _publish_proposal(self, topic: str, payload: dict[str, Any]) -> bool: ...

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
            self._blast_radius_attempts += 1
            if not targets_truncated and selected:
                self._blast_radius_adherent_attempts += 1
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
        async with self._publication_lock(experiment_id):
            if self._state_store is None:
                # Without a durable outbox, an unbound bus means the proposal never leaves Loki.
                if self.bus is None:
                    return False
                published: bool = await self._publish_proposal("object.chaos-experiment", payload)
                return published
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
                return False
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
        await self._state_store.delete_states_beyond(
            _HELD_PREFIX,
            retain_newest=_MAX_HELD_PROPOSALS,
        )

    def _release_targets(self, targets: tuple[str, ...]) -> None:
        """Release process-local slots only from validated terminal closure."""
        for t in targets:
            self._in_flight_targets.discard(t)

    async def _remember_resilience_score(self, candidate: dict[str, Any]) -> bool:
        resource_id = str(candidate["resource_id"])
        observed_at = str(candidate["observed_at"])
        existing = self._resilience_scores.get(resource_id)
        parsed_observed_at = _parse_time(observed_at)
        if existing is not None and parsed_observed_at < _parse_time(existing[1]):
            self.record_behavior("resilience_score:stale")
            return False
        experiment_id = str(candidate.get("experiment_id") or "")
        phase = str(candidate.get("observation_phase") or "")
        if experiment_id and phase in {"baseline", "post"}:
            self._resilience_experiment_scores.setdefault(experiment_id, {})[phase] = float(
                candidate["score"]
            )
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

    @asynccontextmanager
    async def _publication_lock(self, experiment_id: str) -> AsyncIterator[None]:
        lock = self._lock_for_publication(experiment_id)
        self._publication_lock_refs[experiment_id] = (
            self._publication_lock_refs.get(experiment_id, 0) + 1
        )
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            remaining = self._publication_lock_refs.get(experiment_id, 1) - 1
            if remaining > 0:
                self._publication_lock_refs[experiment_id] = remaining
            else:
                self._publication_lock_refs.pop(experiment_id, None)
                self._publication_locks.pop(experiment_id, None)

    def _lock_for_publication(self, experiment_id: str) -> asyncio.Lock:
        lock = self._publication_locks.get(experiment_id)
        if lock is None:
            lock = asyncio.Lock()
            self._publication_locks[experiment_id] = lock
        return lock


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
