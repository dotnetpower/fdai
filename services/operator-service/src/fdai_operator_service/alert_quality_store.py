"""Immutable, principal-scoped materialization of owned alert-quality results.

Responsibility: persist and replay exact reports and inert plans in Operator state_kv.
Boundary: only a trusted result-bus materializer calls the persistence methods. HTTP
callers cannot supply observations. There are no Core imports or provider calls.
Authority and state: append-only private records grant no decision or execution rights.
Dependencies: the injected store implements the existing Operator read/create/find methods.
Deployment: this is an Operator-local projection, not a new service or evidence producer.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fdai_service_contracts.alert_noise import NoiseAssessment, digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.executor_models import ContractBase

from fdai_operator_service.alert_quality_index import (
    _Index,
    _index_key,
    _next_index,
    _verify_successor,
)
from fdai_operator_service.alert_quality_records import _DIGEST as _DIGEST
from fdai_operator_service.alert_quality_records import _REF as _REF
from fdai_operator_service.alert_quality_records import (
    ALERT_QUALITY_PREFIX,
    MAX_ALERT_QUALITY_BYTES,
    MAX_ALERT_QUALITY_PLANS,
    AlertQualityConflictError,
    AlertQualitySnapshot,
    AlertQualitySource,
    AlertQualityStaleError,
    AlertQualityStateStore,
    AlertQualityUnavailableError,
    _artifact_key,
    _AssessmentRecord,
    _canonical,
    _contains_identity,
    _decode,
    _PlanRecord,
    alert_quality_binding_digest,
    alert_quality_requester_ref,
    validate_alert_quality_principal,
    validate_alert_quality_scope,
    verify_alert_quality_snapshot,
)

__all__ = [
    "ALERT_QUALITY_PREFIX",
    "MAX_ALERT_QUALITY_BYTES",
    "MAX_ALERT_QUALITY_PLANS",
    "AlertQualityConflictError",
    "AlertQualitySnapshot",
    "AlertQualitySource",
    "AlertQualityStaleError",
    "AlertQualityStateStore",
    "AlertQualityUnavailableError",
    "StateKvAlertQualityStore",
    "alert_quality_binding_digest",
    "alert_quality_requester_ref",
    "validate_alert_quality_principal",
    "validate_alert_quality_scope",
    "verify_alert_quality_snapshot",
]

_MAX_ADVANCES = 8


class StateKvAlertQualityStore:
    """Append immutable records and CAS-linked indexes using Operator store primitives.

    An index slot is created exactly once. Competing writers reread the winning slot
    before advancing; older cutoffs never replace newer evidence, and equal cutoffs
    with different reports conflict. Failed index publication can leave only inert,
    content-checked artifacts, which an exact retry can reuse. There is no mutable
    latest pointer, process lock, SQL construction, or write_state fallback.
    """

    def __init__(
        self,
        store: AlertQualityStateStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._clock = clock

    async def read(self, *, principal_id: str, scope_ref: str) -> AlertQualitySnapshot | None:
        """Read one exact index generation; absence is not an empty assessment."""
        binding = alert_quality_binding_digest(principal_id, scope_ref)
        index = await self._head(binding)
        if index is None:
            return None
        assessment = await self._indexed_assessment(principal_id, scope_ref, index)
        plans: list[AlertChangePlan] = []
        for plan_digest in index.plan_digests:
            plan = await self.replay_plan(
                principal_id=principal_id, scope_ref=scope_ref, plan_digest=plan_digest
            )
            if plan is None:
                raise AlertQualityUnavailableError("alert quality plan is unavailable")
            plans.append(plan)
        if await self._head(binding) != index:
            raise AlertQualityUnavailableError("alert quality projection changed during read")
        return verify_alert_quality_snapshot(
            AlertQualitySnapshot(binding_digest=binding, assessment=assessment, plans=tuple(plans)),
            principal_id=principal_id,
            scope_ref=scope_ref,
        )

    async def replay_assessment(
        self, *, principal_id: str, scope_ref: str, evidence_digest: str
    ) -> NoiseAssessment | None:
        """Replay retained exact evidence, including superseded or expired history."""
        binding = alert_quality_binding_digest(principal_id, scope_ref)
        raw = await self._store.read_state(_artifact_key(binding, "report", evidence_digest))
        if raw is None:
            return None
        record = _decode(_AssessmentRecord, raw)
        if digest_record(record.assessment) != record.assessment_digest:
            raise AlertQualityUnavailableError("alert quality report digest is invalid")
        snapshot = verify_alert_quality_snapshot(
            AlertQualitySnapshot(
                binding_digest=record.binding_digest, assessment=record.assessment
            ),
            principal_id=principal_id,
            scope_ref=scope_ref,
        )
        if snapshot.assessment.evidence_digest != evidence_digest:
            raise AlertQualityUnavailableError("alert quality report identity is invalid")
        return snapshot.assessment

    async def replay_plan(
        self, *, principal_id: str, scope_ref: str, plan_digest: str
    ) -> AlertChangePlan | None:
        """Replay an immutable plan only from its exact principal/scope namespace."""
        binding = alert_quality_binding_digest(principal_id, scope_ref)
        raw = await self._store.read_state(_artifact_key(binding, "plan", plan_digest))
        if raw is None:
            return None
        record = _decode(_PlanRecord, raw)
        if (
            record.binding_digest != binding
            or record.plan.scope_ref != scope_ref
            or record.plan.requester_ref != alert_quality_requester_ref(principal_id, scope_ref)
            or digest_record(record.plan) != plan_digest
            or _contains_identity(record.plan.model_dump(mode="json"), principal_id)
        ):
            raise AlertQualityUnavailableError("alert quality plan identity is invalid")
        return record.plan

    async def persist_assessment(
        self, *, principal_id: str, scope_ref: str, assessment: NoiseAssessment
    ) -> bool:
        """Materialize a trusted report; duplicates are no-ops, stale/conflicting results raise."""
        binding = alert_quality_binding_digest(principal_id, scope_ref)
        snapshot = verify_alert_quality_snapshot(
            AlertQualitySnapshot(binding_digest=binding, assessment=assessment),
            principal_id=principal_id,
            scope_ref=scope_ref,
        )
        assessment = snapshot.assessment
        for _ in range(_MAX_ADVANCES):
            head = await self._head(binding)
            if head is not None:
                if head.evidence_digest == assessment.evidence_digest:
                    existing = await self._indexed_assessment(principal_id, scope_ref, head)
                    if existing != assessment:
                        raise AlertQualityConflictError("alert quality report identity conflicts")
                    return False
                if assessment.observed_at < head.observed_at:
                    raise AlertQualityStaleError("alert quality report has been superseded")
                if assessment.observed_at == head.observed_at:
                    raise AlertQualityConflictError("alert quality report cutoff conflicts")
            _require_current(assessment.observed_at, assessment.valid_until, self._clock())
            await self._put_immutable(
                _artifact_key(binding, "report", assessment.evidence_digest),
                _AssessmentRecord(
                    binding_digest=binding,
                    assessment_digest=digest_record(assessment),
                    assessment=assessment,
                ),
            )
            index = _next_index(head, binding=binding, assessment=assessment, plan_digests=())
            if await self._store.create_state(
                _index_key(binding, index.revision), index.model_dump(mode="json")
            ):
                return True
        raise AlertQualityUnavailableError("alert quality projection is busy")

    async def persist_plan(
        self, *, principal_id: str, scope_ref: str, plan: AlertChangePlan
    ) -> bool:
        """Materialize an inert producer plan bound to the currently retained report.

        Runtime must already authenticate the producer, correlate the original
        request, and resolve its principal. This method never accepts approval or
        dispatch receipts and cannot make an ineligible plan executable.
        """
        binding = alert_quality_binding_digest(principal_id, scope_ref)
        record = _decode(
            _PlanRecord, _PlanRecord(binding_digest=binding, plan=plan).model_dump(mode="json")
        )
        plan = record.plan
        plan_digest = digest_record(plan)
        for _ in range(_MAX_ADVANCES):
            head = await self._head(binding)
            if head is None or head.evidence_digest != plan.evidence_digest:
                raise AlertQualityStaleError("alert quality plan evidence is not current")
            assessment = await self._indexed_assessment(principal_id, scope_ref, head)
            verify_alert_quality_snapshot(
                AlertQualitySnapshot(binding_digest=binding, assessment=assessment, plans=(plan,)),
                principal_id=principal_id,
                scope_ref=scope_ref,
            )
            if plan_digest in head.plan_digests:
                existing = await self.replay_plan(
                    principal_id=principal_id, scope_ref=scope_ref, plan_digest=plan_digest
                )
                if existing != plan:
                    raise AlertQualityConflictError("alert quality plan identity conflicts")
                return False
            now = self._clock()
            _require_current(assessment.observed_at, assessment.valid_until, now)
            _require_current(plan.created_at, plan.expires_at, now)
            if len(head.plan_digests) >= MAX_ALERT_QUALITY_PLANS:
                raise AlertQualityUnavailableError("alert quality plan bound reached")
            await self._put_immutable(_artifact_key(binding, "plan", plan_digest), record)
            index = _next_index(
                head,
                binding=binding,
                assessment=assessment,
                plan_digests=tuple(sorted((*head.plan_digests, plan_digest))),
            )
            if await self._store.create_state(
                _index_key(binding, index.revision), index.model_dump(mode="json")
            ):
                return True
        raise AlertQualityUnavailableError("alert quality projection is busy")

    async def _indexed_assessment(
        self, principal_id: str, scope_ref: str, index: _Index
    ) -> NoiseAssessment:
        assessment = await self.replay_assessment(
            principal_id=principal_id, scope_ref=scope_ref, evidence_digest=index.evidence_digest
        )
        if (
            assessment is None
            or digest_record(assessment) != index.assessment_digest
            or assessment.observed_at != index.observed_at
        ):
            raise AlertQualityUnavailableError("alert quality report index is invalid")
        return assessment

    async def _put_immutable(self, key: str, record: ContractBase) -> None:
        value = record.model_dump(mode="json")
        encoded = _canonical(value)
        if not await self._store.create_state(key, value):
            existing = await self._store.read_state(key)
            if existing is None or _canonical(existing) != encoded:
                raise AlertQualityConflictError("alert quality immutable record conflicts")

    async def _head(self, binding: str) -> _Index | None:
        """Use the store's newest hint, then verify and follow immutable successor slots."""
        raw = await self._store.find_state(
            prefix=f"{ALERT_QUALITY_PREFIX}{binding[7:]}:index:",
            field="kind",
            value="operator.alert-quality.index",
        )
        if raw is None:
            if await self._store.read_state(_index_key(binding, 1)) is not None:
                raise AlertQualityUnavailableError("alert quality index is malformed")
            return None
        index = _decode(_Index, raw)
        exact = await self._store.read_state(_index_key(binding, index.revision))
        if index.binding_digest != binding or exact is None or _canonical(exact) != _canonical(raw):
            raise AlertQualityUnavailableError("alert quality index binding is invalid")
        if index.revision > 1:
            previous_raw = await self._store.read_state(_index_key(binding, index.revision - 1))
            if previous_raw is None:
                raise AlertQualityUnavailableError("alert quality index predecessor is missing")
            _verify_successor(_decode(_Index, previous_raw), index)
        for _ in range(_MAX_ADVANCES):
            successor_raw = await self._store.read_state(_index_key(binding, index.revision + 1))
            if successor_raw is None:
                return index
            successor = _decode(_Index, successor_raw)
            _verify_successor(index, successor)
            index = successor
        raise AlertQualityUnavailableError("alert quality projection is busy")


def _require_current(start: datetime, end: datetime, now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise AlertQualityUnavailableError("alert quality clock is unavailable")
    if not start <= now < end:
        raise AlertQualityStaleError("alert quality evidence is not current")
