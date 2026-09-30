"""Mimir - Rule Steward (Wave 2 behavior).

Mimir tracks rule shadow / enforce promotion. Wave 2 exposes a minimal
in-memory promotion tracker; the concrete rule catalog loader stays in
:mod:`fdai.rule_catalog`. Mimir's job here is the promotion state
machine and the RuleCandidate intake.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    capped_list,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.mimir_catalog_recovery import (
    CatalogReviewCapacityError,
    MimirCatalogReviewMixin,
)
from fdai.agents._framework.mimir_context import MimirContextMixin
from fdai.agents._framework.pantheon import _MIMIR
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogReviewPublisher,
    ShadowDwellDecision,
    ShadowDwellEvidence,
    ShadowDwellEvidenceError,
    ShadowDwellThresholds,
    evaluate_shadow_dwell,
)
from fdai.core.rule_semantic_generation import (
    RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
    RuleGenerationActivationBinder,
    RuleGenerationBuildHandler,
)
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RULE_GENERATION_BUILD_REQUEST_TOPIC,
    RULE_GENERATION_BUILD_RESULT_TOPIC,
    RuleGenerationActivationCommandEvent,
    RuleGenerationActivationResultEvent,
    RuleGenerationBuildRequestEvent,
    RuleGenerationValidationResultEvent,
)
from fdai.shared.providers.state_store import StateStore

#: Cap on retained rejected-candidate records. Quarantine holds candidates the
#: CandidateGuard REJECTED - i.e. attacker-controlled volume under a
#: candidate-poisoning attempt. An unbounded list would be a memory-exhaustion
#: DoS vector: a poisoning flood grows it without limit. The durable audit
#: trail is Saga's chain; this in-memory list is a bounded diagnostic ring.
_MAX_QUARANTINE = 5_000
_MAX_PENDING_CANDIDATES = 5_000
_MAX_CATALOG_REVIEW_PACKAGES = 5_000
_MAX_ISSUE_FINGERPRINTS = 50_000
_GOVERNANCE_RECOVERY_PAGE = 128
_RULE_GENERATION_RECEIPT_RETAIN = 5_000
_MAX_PROMOTION_PERSIST_QUEUE = 1_024
_MAX_PROMOTION_PERSIST_ATTEMPTS = 8
_OPERATIONAL_RULE_PREFIX = "learned.operational."
_RULE_GENERATION_RECEIPT_PREFIX = "mimir:rule-generation-activation-result:"
_RULE_GENERATION_VALIDATION_PREFIX = "mimir:rule-generation-validation-result:"
_RULE_GENERATION_COMMAND_PREFIX = "mimir:rule-generation-activation-command:"
_GOVERNANCE_PREFIX = "pantheon/mimir/governance"
_RULE_STATE_PREFIX = f"{_GOVERNANCE_PREFIX}/rules"
_ISSUE_FINGERPRINT_PREFIX = f"{_GOVERNANCE_PREFIX}/issue-fingerprints"
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class RulePromotion:
    rule_id: str
    state: str  # shadow | enforce | retired
    source: str  # handoff | override | manual | coherence
    updated_at: str | None


def _rule_state_key(rule_id: str) -> str:
    return f"{_RULE_STATE_PREFIX}/{rule_id}"


def _issue_fingerprint_key(fingerprint: str) -> str:
    return f"{_ISSUE_FINGERPRINT_PREFIX}/{fingerprint}"


class Mimir(MimirContextMixin, Agent, HandoverKnowledgeMixin, MimirCatalogReviewMixin):
    """Wave-2 Mimir: promotion state + candidate intake."""

    def __init__(
        self,
        *,
        catalog_candidate_compiler: CatalogCandidateCompiler | None = None,
        catalog_review_publisher: CatalogReviewPublisher | None = None,
        catalog_review_state_store: StateStore | None = None,
        governance_state_store: StateStore | None = None,
        shadow_dwell_thresholds: ShadowDwellThresholds | None = None,
        max_pending_candidates: int = _MAX_PENDING_CANDIDATES,
        max_review_packages: int = _MAX_CATALOG_REVIEW_PACKAGES,
        clock: Callable[[], datetime] | None = None,
        provider_timeout_seconds: float = _DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(spec=_MIMIR)
        if min(max_pending_candidates, max_review_packages) < 1:
            raise ValueError("Mimir review capacities MUST be positive")
        if provider_timeout_seconds <= 0:
            raise ValueError("Mimir provider timeout MUST be positive")
        self._promotions: dict[str, RulePromotion] = {}
        self._governance_state_store = governance_state_store
        self._promotion_persist_tasks: set[asyncio.Task[None]] = set()
        self._promotion_persist_pending: dict[str, RulePromotion] = {}
        self._promotion_persist_worker: asyncio.Task[None] | None = None
        self._shadow_dwell_thresholds = shadow_dwell_thresholds or ShadowDwellThresholds()
        self._init_catalog_review(
            compiler=catalog_candidate_compiler,
            publisher=catalog_review_publisher,
            state_store=catalog_review_state_store or governance_state_store,
            max_pending_candidates=max_pending_candidates,
            max_review_packages=max_review_packages,
            max_quarantine=_MAX_QUARANTINE,
        )
        self._review_lock = asyncio.Lock()
        self._review_locks: dict[str, asyncio.Lock] = {}
        self._rule_generation_build_handler: RuleGenerationBuildHandler | None = None
        self._rule_generation_activation_binder: RuleGenerationActivationBinder | None = None
        self._rule_generation_state_store: StateStore | None = None
        self._clock = clock or (lambda: datetime.now(UTC))
        self._provider_timeout_seconds = provider_timeout_seconds
        self._issue_fingerprints: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_ISSUE_FINGERPRINTS
        )
        self._operational_pending_targets: BoundedLruSet[str] = BoundedLruSet(
            max_pending_candidates
        )
        self._catalog_draft_rule_ids: BoundedLruSet[str] = BoundedLruSet(max_review_packages)

    def bind_rule_generation_build_handler(
        self,
        handler: RuleGenerationBuildHandler,
    ) -> None:
        """Bind the durable mechanical generation builder at composition time."""

        if self._rule_generation_build_handler is not None:
            raise RuntimeError("Mimir Rule generation build handler is already bound")
        self._rule_generation_build_handler = handler

    def bind_rule_generation_activation_binder(
        self,
        binder: RuleGenerationActivationBinder,
    ) -> None:
        """Bind exact catalog-pointer activation at composition time."""

        if self._rule_generation_activation_binder is not None:
            raise RuntimeError("Mimir Rule generation activation binder is already bound")
        self._rule_generation_activation_binder = binder

    def bind_rule_generation_state_store(self, store: StateStore) -> None:
        """Bind the durable accountability projection at composition time."""

        if self._rule_generation_state_store is not None:
            raise RuntimeError("Mimir Rule generation receipt store is already bound")
        self._rule_generation_state_store = store

    def bind_governance_state_store(self, store: StateStore) -> None:
        """Bind durable Mimir governance projections at composition time."""
        if self._governance_state_store is not None:
            raise RuntimeError("Mimir governance state store is already bound")
        self._governance_state_store = store
        self._catalog_governance_store.bind(store)

    async def recover_governance_state(self) -> int:
        """Restore durable rule, issue, investigation, and quarantine projections."""
        store = self._governance_state_store
        if store is None:
            return 0
        restored = 0
        restored += await self._recover_rule_rows(store)
        restored += await self._recover_issue_rows(store)
        restored += await self._catalog_governance_store.recover(
            investigation_candidates=self._investigation_candidates,
            quarantined_candidates=self._quarantined_candidates,
            max_pending_candidates=self._max_pending_candidates,
            max_quarantine=self._quarantined_candidates.maxlen or _MAX_QUARANTINE,
        )
        return restored

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._test_context_message(topic, payload, self.record_behavior):
            return
        if topic == "object.issue":
            await self._handle_issue(payload)
        elif topic == "object.rule-candidate":
            if await self._handover_message(topic, payload):
                return
            lock_key = str(payload.get("idempotency_key") or payload.get("correlation_id") or "")
            if not lock_key:
                lock_key = repr(sorted(payload))
            lock = self._review_locks.setdefault(lock_key, asyncio.Lock())
            try:
                async with lock:
                    await self._handle_rule_candidate(payload)
            finally:
                if not lock.locked() and self._review_locks.get(lock_key) is lock:
                    self._review_locks.pop(lock_key, None)
        elif topic == RULE_GENERATION_BUILD_REQUEST_TOPIC:
            await self._handle_rule_generation_build_request(payload)
        elif (
            topic == "object.retrieval-validation"
            and payload.get("event_type") == "rule.semantic_generation.validation.completed.v1"
        ):
            await self._record_rule_generation_validation_result(payload)
        elif topic == RULE_GENERATION_ACTIVATION_COMMAND_TOPIC:
            command = RuleGenerationActivationCommandEvent.model_validate(payload)
            binder = self._rule_generation_activation_binder
            if binder is None:
                raise RuntimeError("Mimir Rule generation activation binder is unavailable")
            await self._retain_rule_generation_activation_command(command)
            await binder.handle(command)
        elif topic == RULE_GENERATION_ACTIVATION_RESULT_TOPIC:
            await self._record_rule_generation_activation_result(payload)
        else:
            self.record_behavior("typed_message:ignored")

    async def _recover_rule_rows(self, store: StateStore) -> int:
        restored = 0
        offset = 0
        while restored < _MAX_ISSUE_FINGERPRINTS:
            rows, _total = await store.read_state_page(
                f"{_RULE_STATE_PREFIX}/",
                limit=min(_GOVERNANCE_RECOVERY_PAGE, _MAX_ISSUE_FINGERPRINTS - restored),
                offset=offset,
            )
            if not rows:
                return restored
            for row in rows:
                rule_id = str(row.get("rule_id") or "")
                state = str(row.get("state") or "")
                source = str(row.get("source") or "")
                if not rule_id or state not in {"shadow", "enforce", "retired"} or not source:
                    raise ValueError("Mimir durable rule state is invalid")
                self._promotions[rule_id] = RulePromotion(
                    rule_id=rule_id,
                    state=state,
                    source=source,
                    updated_at=(
                        row.get("updated_at") if isinstance(row.get("updated_at"), str) else None
                    ),
                )
                restored += 1
            offset += len(rows)
        self.record_behavior("governance_recovery:rules_deferred")
        return restored

    async def _recover_issue_rows(self, store: StateStore) -> int:
        restored = 0
        offset = 0
        while restored < _MAX_ISSUE_FINGERPRINTS:
            rows, _total = await store.read_state_page(
                f"{_ISSUE_FINGERPRINT_PREFIX}/",
                limit=min(_GOVERNANCE_RECOVERY_PAGE, _MAX_ISSUE_FINGERPRINTS - restored),
                offset=offset,
            )
            if not rows:
                return restored
            for row in rows:
                fingerprint = str(row.get("fingerprint") or "")
                if not fingerprint:
                    raise ValueError("Mimir durable issue fingerprint is invalid")
                self._issue_fingerprints.set(
                    fingerprint,
                    {
                        "fingerprint": fingerprint,
                        "issue_number": row.get("issue_number"),
                        "created": row.get("created") is True,
                        "correlation_id": str(row.get("correlation_id") or ""),
                        "open": row.get("open") is not False,
                        "candidate_count": row.get("candidate_count"),
                    },
                )
                restored += 1
            offset += len(rows)
        self.record_behavior("governance_recovery:issues_deferred")
        return restored

    async def _handle_issue(self, payload: dict[str, Any]) -> None:
        """Retain Saga-owned issue fingerprints for candidate closure linkage."""
        if payload.get("producer_principal") != "Saga":
            self.record_behavior("issue_fingerprint:rejected")
            raise ValueError("Mimir issue fingerprints MUST be published by Saga")
        fingerprint = str(payload.get("fingerprint") or "").strip()
        issue_number = payload.get("issue_number")
        correlation_id = str(payload.get("correlation_id") or "").strip()
        if (
            not fingerprint
            or not correlation_id
            or not isinstance(issue_number, int)
            or isinstance(issue_number, bool)
            or issue_number < 1
        ):
            self.record_behavior("issue_fingerprint:rejected")
            raise ValueError("Mimir issue fingerprint payload is malformed")
        record = {
            "fingerprint": fingerprint,
            "issue_number": issue_number,
            "created": payload.get("created") is True,
            "correlation_id": correlation_id,
            "open": payload.get("open", True) is not False,
            "candidate_count": self._candidate_count_for_fingerprint(fingerprint),
        }
        self._issue_fingerprints.set(fingerprint, record)
        await self._persist_issue_fingerprint(record)
        self.record_behavior("issue_fingerprint:accepted")

    def _candidate_count_for_fingerprint(self, fingerprint: str) -> int:
        count = 0
        for candidate in self._pending_candidates:
            evidence = candidate.get("evidence")
            if isinstance(evidence, dict) and evidence.get("fingerprint") == fingerprint:
                count += 1
        return count

    async def request_rule_generation(self, request: RuleGenerationBuildRequestEvent) -> None:
        """Publish one exact no-authority generation build request as Mimir."""

        validated = RuleGenerationBuildRequestEvent.model_validate(request.model_dump())
        if self.bus is None:
            raise RuntimeError("Mimir Rule generation build transport is unavailable")
        await self.bus.publish(
            "Mimir",
            RULE_GENERATION_BUILD_REQUEST_TOPIC,
            validated.model_dump(mode="json"),
        )

    async def _handle_rule_generation_build_request(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Mimir":
            self.record_behavior("rule_generation_build_request:rejected_owner")
            raise ValueError("Rule generation build request MUST be published by Mimir")
        request = RuleGenerationBuildRequestEvent.model_validate(
            {
                field: payload[field]
                for field in RuleGenerationBuildRequestEvent.model_fields
                if field in payload
            }
        )
        handler = self._rule_generation_build_handler
        if handler is None:
            raise RuntimeError("Mimir Rule generation build handler is unavailable")
        result = await handler.handle(request)
        if self.bus is None:
            raise RuntimeError("Mimir Rule generation build transport is unavailable")
        result_payload = result.model_dump(mode="json")
        result_payload["correlation_id"] = request.correlation_id
        await self.bus.publish(
            "Mimir",
            RULE_GENERATION_BUILD_RESULT_TOPIC,
            result_payload,
        )
        self.record_behavior("rule_generation_build_result_published")

    async def _record_rule_generation_validation_result(
        self,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("producer_principal") != "Heimdall":
            self.record_behavior("rule_generation_validation:rejected_owner")
            raise ValueError("Rule generation validation MUST be published by Heimdall")
        result = RuleGenerationValidationResultEvent.model_validate(
            {
                field: payload[field]
                for field in RuleGenerationValidationResultEvent.model_fields
                if field in payload
            }
        )
        store = self._rule_generation_state_store
        if store is None:
            raise RuntimeError("Mimir Rule generation receipt store is unavailable")
        receipt_key = f"{_RULE_GENERATION_VALIDATION_PREFIX}{result.idempotency_key}"
        receipt = {
            "kind": "rule_semantic_generation_validation_result",
            "idempotency_key": result.idempotency_key,
            "result_digest": result.result_digest,
            "generation_id": result.build_result.generation.generation_id,
            "valid": result.valid,
            "validation_receipt_digest": result.validation_receipt_digest,
            "validated_at": result.validated_at.isoformat(),
            "projection_only": True,
            "grants_execution_authority": False,
        }
        created = await store.write_state_with_audit_if_absent(
            receipt_key,
            receipt,
            {
                **receipt,
                "principal": "Mimir",
                "topic": "object.retrieval-validation",
            },
        )
        if created:
            self.record_behavior("rule_generation_validation_result_recorded")
        else:
            existing = await store.read_state(receipt_key)
            if existing is None or existing.get("result_digest") != result.result_digest:
                raise ValueError("Rule generation validation result idempotency conflict")
            self.record_behavior("rule_generation_validation_result_duplicate")
        if result.valid:
            await self._publish_rule_generation_activation_command(result)
        await store.delete_states_beyond(
            _RULE_GENERATION_VALIDATION_PREFIX,
            retain_newest=_RULE_GENERATION_RECEIPT_RETAIN,
        )

    async def _publish_rule_generation_activation_command(
        self,
        result: RuleGenerationValidationResultEvent,
    ) -> None:
        store = self._rule_generation_state_store
        binder = self._rule_generation_activation_binder
        if store is None:
            raise RuntimeError("Mimir Rule generation receipt store is unavailable")
        if binder is None:
            raise RuntimeError("Mimir Rule generation activation binder is unavailable")
        command_key = f"{_RULE_GENERATION_COMMAND_PREFIX}{result.idempotency_key}"
        existing = await store.read_state(command_key)
        if existing is None:
            await binder.bind_validation_result(result)
            target = result.build_result.generation
            prior = await binder.active_generation_identity(target.corpus.value)
            commanded_at = max(self._clock(), result.validated_at)
            candidate = RuleGenerationActivationCommandEvent.create(
                validation_result=result,
                expected_active_generation=prior,
                commanded_at=commanded_at,
            )
            payload = candidate.model_dump(mode="json")
            created = await store.write_state_with_audit_if_absent(
                command_key,
                payload,
                {
                    "kind": "rule_semantic_generation_activation_command",
                    "principal": "Mimir",
                    "idempotency_key": candidate.idempotency_key,
                    "command_digest": candidate.command_digest,
                    "generation_id": target.generation_id,
                    "grants_execution_authority": False,
                },
            )
            if created:
                command = candidate
                self.record_behavior("rule_generation_activation_command_recorded")
            else:
                raced = await store.read_state(command_key)
                if raced is None:
                    raise RuntimeError("Mimir Rule generation activation command is unavailable")
                command = RuleGenerationActivationCommandEvent.model_validate(raced)
        else:
            command = RuleGenerationActivationCommandEvent.model_validate(existing)
        if command.validation_result.result_digest != result.result_digest:
            raise ValueError("Rule generation activation command idempotency conflict")
        try:
            async with asyncio.timeout(self._provider_timeout_seconds):
                await binder.publish_command(command)
        except TimeoutError:
            self.record_behavior("rule_generation_activation_command_timeout")
            raise
        self.record_behavior("rule_generation_activation_command_published")
        await store.delete_states_beyond(
            _RULE_GENERATION_COMMAND_PREFIX,
            retain_newest=_RULE_GENERATION_RECEIPT_RETAIN,
        )

    async def _retain_rule_generation_activation_command(
        self,
        command: RuleGenerationActivationCommandEvent,
    ) -> None:
        store = self._rule_generation_state_store
        if store is None:
            return
        command_key = (
            f"{_RULE_GENERATION_COMMAND_PREFIX}{command.validation_result.idempotency_key}"
        )
        existing = await store.read_state(command_key)
        if existing is not None:
            retained = RuleGenerationActivationCommandEvent.model_validate(existing)
            if retained.command_digest != command.command_digest:
                raise ValueError("Rule generation activation command idempotency conflict")
            return
        await store.write_state_with_audit_if_absent(
            command_key,
            command.model_dump(mode="json"),
            {
                "kind": "rule_semantic_generation_activation_command",
                "principal": "Mimir",
                "idempotency_key": command.idempotency_key,
                "command_digest": command.command_digest,
                "generation_id": (command.validation_result.build_result.generation.generation_id),
                "grants_execution_authority": False,
            },
        )
        await store.delete_states_beyond(
            _RULE_GENERATION_COMMAND_PREFIX,
            retain_newest=_RULE_GENERATION_RECEIPT_RETAIN,
        )

    async def _record_rule_generation_activation_result(self, payload: dict[str, Any]) -> None:
        producer = payload.get("producer_principal")
        if producer is not None and producer != "Mimir":
            self.record_behavior("rule_generation_activation_result_rejected_owner")
            raise ValueError("Rule generation activation result MUST be published by Mimir")
        result_payload = dict(payload)
        result_payload.pop("producer_principal", None)
        result = RuleGenerationActivationResultEvent.model_validate(result_payload)
        store = self._rule_generation_state_store
        if store is None:
            raise RuntimeError("Mimir Rule generation receipt store is unavailable")
        command_key = (
            f"{_RULE_GENERATION_COMMAND_PREFIX}{result.command.validation_result.idempotency_key}"
        )
        command_record = await store.read_state(command_key)
        if command_record is None:
            self.record_behavior("rule_generation_activation_result_rejected_unbound")
            raise ValueError("Rule generation activation result has no issued command")
        command = RuleGenerationActivationCommandEvent.model_validate(command_record)
        if command.command_digest != result.command.command_digest:
            self.record_behavior("rule_generation_activation_result_rejected_unbound")
            raise ValueError("Rule generation activation result command identity mismatch")
        receipt_key = f"{_RULE_GENERATION_RECEIPT_PREFIX}{result.idempotency_key}"
        receipt = {
            "kind": "rule_semantic_generation_activation_result",
            "idempotency_key": result.idempotency_key,
            "result_digest": result.result_digest,
            "status": result.status.value,
            "generation_id": (
                result.command.validation_result.build_result.generation.generation_id
            ),
            "completed_at": result.completed_at.isoformat(),
            "projection_only": True,
            "grants_execution_authority": False,
        }
        created = await store.write_state_with_audit_if_absent(
            receipt_key,
            receipt,
            {
                **receipt,
                "principal": "Mimir",
                "topic": RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
            },
        )
        if created:
            self.record_behavior("rule_generation_activation_result_recorded")
            await store.delete_states_beyond(
                _RULE_GENERATION_RECEIPT_PREFIX,
                retain_newest=_RULE_GENERATION_RECEIPT_RETAIN,
            )
            return
        existing = await store.read_state(receipt_key)
        if existing is None or existing.get("result_digest") != result.result_digest:
            raise ValueError("Rule generation activation result idempotency conflict")
        self.record_behavior("rule_generation_activation_result_duplicate")

    def _rebuild_candidate_indexes(self) -> None:
        self._operational_pending_targets = BoundedLruSet(self._max_pending_candidates)
        self._catalog_draft_rule_ids = BoundedLruSet(self._max_review_packages)
        for candidate in self._pending_candidates:
            if candidate.get("source_signal") == "operational_case_fingerprint_cohort":
                target = str(candidate.get("target_rule_id") or "")
                if target:
                    self._operational_pending_targets.add(target)
        for package in self._catalog_review_packages.values():
            rule_id = str(package.draft_rule.mapping["id"])
            if rule_id:
                self._catalog_draft_rule_ids.add(rule_id)

    def shadow_dwell_decision(self, candidate: dict[str, Any]) -> ShadowDwellDecision:
        """Re-derive the dwell verdict for one candidate from its own wire evidence.

        Mimir never reads another agent's memory to fill a gap: whatever the
        candidate failed to carry is missing evidence, and missing evidence is a
        gap, not a pass.
        """

        raw = candidate.get("shadow_dwell")
        if raw is None:
            return evaluate_shadow_dwell(None, self._shadow_dwell_thresholds)
        try:
            evidence = ShadowDwellEvidence.from_mapping(raw)
        except ShadowDwellEvidenceError as exc:
            return ShadowDwellDecision(
                eligible=False,
                gaps=(f"shadow_dwell_evidence_invalid:{exc.code}",),
            )
        target = str(candidate.get("target_rule_id") or "")
        if evidence.target != target:
            # Otherwise a candidate could borrow a well-behaved rule's record.
            return ShadowDwellDecision(eligible=False, gaps=("shadow_dwell_target_mismatch",))
        return evaluate_shadow_dwell(evidence, self._shadow_dwell_thresholds)

    def promotion_ready_candidates(self) -> tuple[dict[str, Any], ...]:
        """Pending candidates whose shadow dwell evidence clears every bar.

        This is the discovery loop's promotion-eligibility surface. Membership is
        earned by evidence; a candidate is absent until it proves the dwell, which
        is why it is computed here rather than stamped onto the candidate on
        intake. Eligibility is still not promotion - the catalog changes only
        through a merged catalog-as-code pull request.
        """

        return tuple(
            candidate
            for candidate in self._pending_candidates
            if self.shadow_dwell_decision(candidate).eligible
        )

    def promote(
        self,
        rule_id: str,
        *,
        source: str,
        reviewed_change_ref: str | None = None,
        updated_at: str | None = None,
    ) -> RulePromotion:
        if (
            rule_id.startswith(_OPERATIONAL_RULE_PREFIX)
            or rule_id in self._operational_pending_targets
            or rule_id in self._published_operational_targets
            or rule_id in self._catalog_draft_rule_ids
        ):
            raise ValueError(
                "operational candidates require a reviewed catalog PR; "
                "direct runtime promotion is not supported"
            )
        blocking_gaps = self._dwell_gaps_for(rule_id)
        if blocking_gaps:
            raise ValueError(
                f"rule {rule_id} has a pending discovery-loop candidate whose shadow "
                f"dwell evidence is insufficient: {', '.join(blocking_gaps)}"
            )
        if not reviewed_change_ref or not reviewed_change_ref.strip():
            self.record_behavior("promotion:reviewed_change_required")
            raise ValueError("rule promotion requires a reviewed catalog-as-code reference")
        promo = RulePromotion(
            rule_id=rule_id, state="enforce", source=source, updated_at=updated_at
        )
        self._promotions[rule_id] = promo
        self._persist_promotion(promo)
        self._pending_candidates = deque(
            (
                candidate
                for candidate in self._pending_candidates
                if candidate.get("target_rule_id") != rule_id
            ),
        )
        self._rebuild_candidate_indexes()
        return promo

    def _dwell_gaps_for(self, rule_id: str) -> tuple[str, ...]:
        """Unmet dwell bars across every pending candidate that targets ``rule_id``."""

        gaps: list[str] = []
        for candidate in self._pending_candidates:
            if str(candidate.get("target_rule_id") or "") != rule_id:
                continue
            decision = self.shadow_dwell_decision(candidate)
            gaps.extend(gap for gap in decision.gaps if gap not in gaps)
        return tuple(gaps)

    def revoke(self, rule_id: str, *, updated_at: str | None = None) -> RulePromotion:
        promo = RulePromotion(
            rule_id=rule_id, state="retired", source="manual", updated_at=updated_at
        )
        self._promotions[rule_id] = promo
        self._persist_promotion(promo)
        return promo

    def status(self, rule_id: str) -> RulePromotion | None:
        return self._promotions.get(rule_id)

    async def drain_governance_writes(self) -> None:
        """Wait for sync promotion/revocation persistence tasks before restart tests."""
        while self._promotion_persist_tasks:
            await asyncio.gather(*tuple(self._promotion_persist_tasks))
        worker = self._promotion_persist_worker
        if worker is not None:
            await worker

    def _persist_promotion(self, promotion: RulePromotion) -> None:
        store = self._governance_state_store
        if store is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._persist_promotion_record(promotion))
            return
        if (
            promotion.rule_id not in self._promotion_persist_pending
            and len(self._promotion_persist_pending) >= _MAX_PROMOTION_PERSIST_QUEUE
        ):
            self.record_behavior("promotion:persist_backpressure")
            raise RuntimeError("Mimir promotion persistence queue is full")
        self._promotion_persist_pending[promotion.rule_id] = promotion
        if self._promotion_persist_worker is None or self._promotion_persist_worker.done():
            self._promotion_persist_worker = loop.create_task(self._drain_promotion_persist_queue())
            self._promotion_persist_tasks.add(self._promotion_persist_worker)
            self._promotion_persist_worker.add_done_callback(self._promotion_persist_done)

    def _promotion_persist_done(self, task: asyncio.Task[None]) -> None:
        self._promotion_persist_tasks.discard(task)
        if self._promotion_persist_worker is task:
            self._promotion_persist_worker = None
        try:
            task.result()
        except Exception:
            self.record_behavior("promotion:persist_failed")

    async def _drain_promotion_persist_queue(self) -> None:
        while self._promotion_persist_pending:
            _rule_id, promotion = self._promotion_persist_pending.popitem()
            await self._persist_promotion_record(promotion)

    async def _persist_promotion_record(self, promotion: RulePromotion) -> None:
        store = self._governance_state_store
        if store is None:
            return
        key = _rule_state_key(promotion.rule_id)
        for attempt in range(_MAX_PROMOTION_PERSIST_ATTEMPTS):
            current = await store.read_state(key)
            revision = int(current.get("revision", 0)) if current is not None else 0
            record = {
                "kind": "mimir_rule_state",
                "revision": revision + 1,
                "rule_id": promotion.rule_id,
                "state": promotion.state,
                "source": promotion.source,
                "updated_at": promotion.updated_at,
                "terminal": promotion.state == "retired",
            }
            audit = {
                "kind": "mimir_rule_state_recorded",
                "principal": "Mimir",
                "rule_id": promotion.rule_id,
                "state": promotion.state,
                "revision": revision + 1,
                "grants_authority": False,
            }
            if current is None:
                if await store.write_state_with_audit_if_absent(key, record, audit):
                    return
            elif await store.compare_and_set_state_with_audit(
                key,
                record,
                expected_revision=revision,
                audit_entry=audit,
            ):
                return
            self.record_behavior("promotion:persist_cas_retry")
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        self.record_behavior("promotion:persist_cas_exhausted")
        raise RuntimeError("Mimir promotion persistence CAS did not converge")

    async def _persist_issue_fingerprint(self, record: dict[str, Any]) -> None:
        store = self._governance_state_store
        if store is None:
            return
        fingerprint = str(record["fingerprint"])
        key = _issue_fingerprint_key(fingerprint)
        current = await store.read_state(key)
        revision = int(current.get("revision", 0)) if current is not None else 0
        value = {
            "kind": "mimir_issue_fingerprint",
            "revision": revision + 1,
            **record,
        }
        audit = {
            "kind": "mimir_issue_fingerprint_recorded",
            "principal": "Mimir",
            "fingerprint": fingerprint,
            "issue_number": record["issue_number"],
            "revision": revision + 1,
            "grants_authority": False,
        }
        if current is None:
            await store.write_state_with_audit_if_absent(key, value, audit)
            return
        await store.compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=revision,
            audit_entry=audit,
        )

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Rule answers rest on tracked promotions and the candidate queue."""
        return bool(self._promotions or self._pending_candidates or self._quarantined_candidates)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_rules": capped_list(sorted(self._promotions)),
            "tracked_rules_count": len(self._promotions),
            "pending_candidates": len(self._pending_candidates),
            "promotion_ready_candidates": "bounded-summary-not-recomputed",
            "quarantined_candidates": len(self._quarantined_candidates),
            "catalog_review_packages": len(self._catalog_review_packages),
            "catalog_review_publication_receipts": len(self._published_reviews),
            "open_issue_fingerprints": len(self._issue_fingerprints),
            "policy_history_available": False,
            "rule_id": None,
            "state": None,
            "source": None,
            "updated_at": None,
        }
        if "policy_history" in semantic_intents(context):
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            return IntrospectionResult(
                answer=(
                    "No governed policy history is bound to this conversational projection. "
                    f"Evidence: {evidence_ref}."
                ),
                facts=facts,
            )
        rules = mentioned(question, self._promotions)
        if rules:
            promo = self._promotions[rules[0]]
            facts.update(
                {
                    "rule_id": promo.rule_id,
                    "state": promo.state,
                    "source": promo.source,
                    # When the state last changed, so an operator can tell a
                    # fresh promotion from a long-settled one.
                    "updated_at": promo.updated_at,
                }
            )
            evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
            facts["evidence_refs"] = [evidence_ref]
            answer = (
                f"Rule {promo.rule_id!r} is {promo.state} (source: {promo.source}). "
                f"Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        if context.get("locale") == "ko":
            answer = (
                "저는 거버넌스 계층의 rule steward인 Mimir입니다. Odin에게 보고합니다. Rule, "
                "Policy, RuleGenerationBuildRequest 및 RuleGenerationBuildResult를 소유합니다. "
                "모든 후보는 품질 gate, 회귀 검사와 shadow 근거를 통과해야 하며 운영 규칙은 검토된 "
                "catalog PR 없이는 승격할 수 없습니다. 작업을 판단하거나 승인하거나 실행하지 "
                "않습니다. 이 대화 포트는 읽기 전용이며 catalog 변경 요청은 운영자 권한으로 "
                "타입이 지정된 파이프라인에 다시 진입해야 합니다. 숨겨진 시스템 프롬프트는 "
                f"공개하지 않습니다. 이 런타임은 Rule {facts['tracked_rules_count']}개, 대기 후보 "
                f"{facts['pending_candidates']}개, 승격 준비 후보 "
                f"{facts['promotion_ready_candidates']}개, 격리 후보 "
                f"{facts['quarantined_candidates']}개를 추적합니다. 근거: {evidence_ref}."
            )
        else:
            answer = (
                "I am Mimir, the governance-layer rule steward. I report to Odin. I own Rule, "
                "Policy, RuleGenerationBuildRequest, and RuleGenerationBuildResult. Every "
                "candidate must pass the quality gate, regression checks, and shadow evidence; "
                "operational rules cannot promote without a reviewed catalog PR. I never judge, "
                "approve, or execute an action. This conversational port is read-only; catalog "
                "change requests re-enter the typed pipeline under the operator's authority. I do "
                "not reveal hidden system prompts. This runtime tracks "
                f"{facts['tracked_rules_count']} Rules, {facts['pending_candidates']} pending "
                f"candidates, {facts['promotion_ready_candidates']} promotion-ready candidates, "
                f"and {facts['quarantined_candidates']} quarantined candidates. "
                f"Evidence: {evidence_ref}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["CatalogReviewCapacityError", "Mimir", "RulePromotion"]
