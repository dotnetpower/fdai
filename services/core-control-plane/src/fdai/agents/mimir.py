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
from fdai.agents._framework.candidate_guard import CandidateGuard
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.pantheon import _MIMIR
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogCompilationError,
    CatalogReviewOutcome,
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
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
_OPERATIONAL_RULE_PREFIX = "learned.operational."
_RULE_GENERATION_RECEIPT_PREFIX = "mimir:rule-generation-activation-result:"
_RULE_GENERATION_VALIDATION_PREFIX = "mimir:rule-generation-validation-result:"
_RULE_GENERATION_COMMAND_PREFIX = "mimir:rule-generation-activation-command:"


@dataclass(frozen=True, slots=True)
class RulePromotion:
    rule_id: str
    state: str  # shadow | enforce | retired
    source: str  # handoff | override | manual | coherence
    updated_at: str | None


class CatalogReviewCapacityError(RuntimeError):
    """Review work is saturated; transport must retry or dead-letter."""


class Mimir(Agent):
    """Wave-2 Mimir: promotion state + candidate intake."""

    def __init__(
        self,
        *,
        catalog_candidate_compiler: CatalogCandidateCompiler | None = None,
        catalog_review_publisher: CatalogReviewPublisher | None = None,
        shadow_dwell_thresholds: ShadowDwellThresholds | None = None,
        max_pending_candidates: int = _MAX_PENDING_CANDIDATES,
        max_review_packages: int = _MAX_CATALOG_REVIEW_PACKAGES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(spec=_MIMIR)
        if min(max_pending_candidates, max_review_packages) < 1:
            raise ValueError("Mimir review capacities MUST be positive")
        self._promotions: dict[str, RulePromotion] = {}
        self._pending_candidates: deque[dict[str, Any]] = deque()
        self._quarantined_candidates: deque[dict[str, Any]] = deque(maxlen=_MAX_QUARANTINE)
        self._guard = CandidateGuard()
        self._shadow_dwell_thresholds = shadow_dwell_thresholds or ShadowDwellThresholds()
        self._catalog_candidate_compiler = catalog_candidate_compiler
        self._catalog_review_publisher = catalog_review_publisher
        self._max_pending_candidates = max_pending_candidates
        self._max_review_packages = max_review_packages
        self._review_lock = asyncio.Lock()
        self._catalog_review_packages: dict[str, CatalogReviewPackage] = {}
        self._package_by_idempotency: dict[str, str] = {}
        self._published_reviews: BoundedLruDict[
            str,
            tuple[str, str, CatalogReviewPublicationReceipt],
        ] = BoundedLruDict(max_review_packages)
        self._published_operational_targets: BoundedLruSet[str] = BoundedLruSet(max_review_packages)
        self._investigation_candidates: BoundedLruDict[str, str] = BoundedLruDict(
            max_pending_candidates
        )
        self._rule_generation_build_handler: RuleGenerationBuildHandler | None = None
        self._rule_generation_activation_binder: RuleGenerationActivationBinder | None = None
        self._rule_generation_state_store: StateStore | None = None
        self._clock = clock or (lambda: datetime.now(UTC))

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

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.rule-candidate":
            async with self._review_lock:
                await self._handle_rule_candidate(payload)
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
            await binder.handle(command)
        elif topic == RULE_GENERATION_ACTIVATION_RESULT_TOPIC:
            await self._record_rule_generation_activation_result(payload)

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
        await self.bus.publish(
            "Mimir",
            RULE_GENERATION_BUILD_RESULT_TOPIC,
            result.model_dump(mode="json"),
        )
        self.record_behavior("rule_generation_build_result_published")

    async def _record_rule_generation_validation_result(
        self,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("producer_principal") != "Heimdall":
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
        await binder.publish_command(command)
        self.record_behavior("rule_generation_activation_command_published")

    async def _record_rule_generation_activation_result(self, payload: dict[str, Any]) -> None:
        result = RuleGenerationActivationResultEvent.model_validate(payload)
        store = self._rule_generation_state_store
        if store is None:
            raise RuntimeError("Mimir Rule generation receipt store is unavailable")
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
            return
        existing = await store.read_state(receipt_key)
        if existing is None or existing.get("result_digest") != result.result_digest:
            raise ValueError("Rule generation activation result idempotency conflict")
        self.record_behavior("rule_generation_activation_result_duplicate")

    async def _handle_rule_candidate(self, payload: dict[str, Any]) -> None:
        investigation_identity: tuple[str, str] | None = None
        if payload.get("source_signal") == "investigation_strategy_comparison_cohort":
            if payload.get("producer_principal") != "Norns":
                raise ValueError("investigation strategy candidate MUST be published by Norns")
            idempotency_key = str(payload.get("idempotency_key") or "")
            evidence = payload.get("evidence")
            candidate_digest = (
                str(evidence.get("candidate_digest") or "") if isinstance(evidence, dict) else ""
            )
            if not idempotency_key or not candidate_digest:
                raise ValueError("investigation strategy candidate identity is missing")
            existing = self._investigation_candidates.get(idempotency_key)
            if existing is not None:
                if existing != candidate_digest:
                    raise ValueError("investigation strategy candidate idempotency conflict")
                self.record_behavior("investigation_strategy_candidate_duplicate")
                return
            investigation_identity = (idempotency_key, candidate_digest)
        if payload.get("source_signal") == "operational_case_fingerprint_cohort":
            idempotency_key = self._idempotency_key(payload)
            if (
                idempotency_key in self._package_by_idempotency
                or idempotency_key in self._published_reviews
            ):
                await self._retry_operational_candidate(payload)
                return
        verdict = self._guard.inspect(payload)
        if verdict.accepted:
            await self._accept_candidate(payload)
            if investigation_identity is not None:
                self._investigation_candidates.set(*investigation_identity)
        else:
            self._quarantined_candidates.append(
                {**dict(payload), "quarantine_reason": verdict.reason}
            )
            await self._audit_outcome(
                payload,
                outcome="quarantined",
                reason=verdict.reason,
            )

    async def _accept_candidate(self, payload: dict[str, Any]) -> None:
        candidate = dict(payload)
        if candidate.get("source_signal") != "operational_case_fingerprint_cohort":
            self._ensure_pending_capacity()
            self._pending_candidates.append(candidate)
            return
        compiler = self._catalog_candidate_compiler
        if compiler is None:
            self._ensure_pending_capacity()
            self._pending_candidates.append(candidate)
            self.record_behavior("operational_catalog_compiler_unavailable")
            return
        try:
            package = compiler.compile(candidate)
        except CatalogCompilationError as exc:
            self._quarantined_candidates.append(
                {**candidate, "quarantine_reason": f"catalog_compile:{exc.code}"}
            )
            self.record_behavior("operational_catalog_compile_failed")
            await self._audit_outcome(
                candidate,
                outcome="quarantined",
                reason=f"catalog_compile:{exc.code}",
            )
            return
        if (
            package.content_digest not in self._catalog_review_packages
            and len(self._catalog_review_packages) >= self._max_review_packages
        ):
            raise CatalogReviewCapacityError("Mimir catalog review package capacity exhausted")
        self._ensure_pending_capacity()
        self._pending_candidates.append(candidate)
        self._catalog_review_packages[package.content_digest] = package
        self._package_by_idempotency[self._idempotency_key(candidate)] = package.content_digest
        await self._publish_package(candidate, package)
        self.record_behavior("operational_catalog_review_ready")

    async def _retry_operational_candidate(self, payload: dict[str, Any]) -> None:
        compiler = self._catalog_candidate_compiler
        if compiler is None:
            raise RuntimeError("retained operational package has no compiler")
        candidate = dict(payload)
        package = compiler.compile(candidate)
        idempotency_key = self._idempotency_key(candidate)
        published = self._published_reviews.get(idempotency_key)
        if published is not None:
            candidate_digest, package_digest, receipt = published
            if package.content_digest != package_digest:
                await self._audit_outcome(
                    candidate,
                    outcome="conflict",
                    reason="idempotency_payload_conflict",
                    candidate_digest=package.candidate.digest,
                    package_digest=package.content_digest,
                )
                raise ValueError("catalog review idempotency payload conflict")
            await self._audit_outcome(
                candidate,
                outcome="duplicate",
                reason="publication_already_recorded",
                candidate_digest=candidate_digest,
                package_digest=package_digest,
                review_ref=receipt.review_ref,
            )
            return
        retained_digest = self._package_by_idempotency[idempotency_key]
        if package.content_digest != retained_digest:
            await self._audit_outcome(
                candidate,
                outcome="conflict",
                reason="idempotency_payload_conflict",
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
            )
            raise ValueError("catalog review idempotency payload conflict")
        retained = self._catalog_review_packages[retained_digest]
        await self._publish_package(candidate, retained)

    async def _publish_package(
        self,
        candidate: dict[str, Any],
        package: CatalogReviewPackage,
    ) -> None:
        publisher = self._catalog_review_publisher
        if publisher is None:
            await self._audit_outcome(
                candidate,
                outcome="retained",
                reason="publisher_unavailable",
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
            )
            return
        try:
            receipt = await publisher.publish(package)
        except Exception as exc:
            await self._audit_outcome(
                candidate,
                outcome="publication_failed",
                reason=f"publisher_error:{type(exc).__name__}",
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
            )
            raise
        if (
            not isinstance(receipt, CatalogReviewPublicationReceipt)
            or receipt.package_digest != package.content_digest
        ):
            await self._audit_outcome(
                candidate,
                outcome="publication_failed",
                reason="receipt_digest_conflict",
                candidate_digest=package.candidate.digest,
                package_digest=package.content_digest,
            )
            raise ValueError("catalog review publication receipt digest conflict")
        await self._audit_outcome(
            candidate,
            outcome="published",
            reason=("existing_review" if receipt.already_existed else "new_review"),
            candidate_digest=package.candidate.digest,
            package_digest=package.content_digest,
            review_ref=receipt.review_ref,
        )
        self._complete_publication(candidate, package, receipt)

    def _complete_publication(
        self,
        candidate: dict[str, Any],
        package: CatalogReviewPackage,
        receipt: CatalogReviewPublicationReceipt,
    ) -> None:
        completed_keys = {
            idempotency_key
            for idempotency_key, package_digest in self._package_by_idempotency.items()
            if package_digest == package.content_digest
        }
        completed_keys.add(self._idempotency_key(candidate))
        for idempotency_key in completed_keys:
            self._published_reviews.set(
                idempotency_key,
                (package.candidate.digest, package.content_digest, receipt),
            )
        target_rule_id = str(candidate.get("target_rule_id") or "")
        if target_rule_id:
            self._published_operational_targets.add(target_rule_id)
        for idempotency_key in completed_keys:
            self._package_by_idempotency.pop(idempotency_key, None)
        self._catalog_review_packages.pop(package.content_digest, None)
        self._pending_candidates = deque(
            item
            for item in self._pending_candidates
            if item.get("idempotency_key") not in completed_keys
        )

    def _ensure_pending_capacity(self) -> None:
        if len(self._pending_candidates) >= self._max_pending_candidates:
            raise CatalogReviewCapacityError("Mimir pending candidate capacity exhausted")

    @staticmethod
    def _idempotency_key(payload: dict[str, Any]) -> str:
        value = payload.get("idempotency_key")
        if not isinstance(value, str) or not value:
            raise ValueError("catalog review candidate requires an idempotency_key")
        return value

    async def _audit_outcome(
        self,
        payload: dict[str, Any],
        *,
        outcome: str,
        reason: str,
        candidate_digest: str | None = None,
        package_digest: str | None = None,
        review_ref: str | None = None,
    ) -> None:
        correlation = payload.get("correlation_id")
        record = CatalogReviewOutcome(
            idempotency_key=self._idempotency_key(payload),
            correlation_id=(
                correlation if isinstance(correlation, str) and correlation else "unavailable"
            ),
            candidate_digest=candidate_digest,
            package_digest=package_digest,
            outcome=outcome,
            reason=reason,
            review_ref=review_ref,
        )
        if self.bus is None:
            raise RuntimeError("Mimir catalog review audit transport is unavailable")
        await self.bus.publish(
            "Mimir",
            "object.rule",
            {
                "kind": "catalog_review_outcome",
                "correlation_id": record.correlation_id,
                "idempotency_key": record.idempotency_key,
                "candidate_digest": record.candidate_digest,
                "package_digest": record.package_digest,
                "outcome": record.outcome,
                "reason": record.reason,
                "review_ref": record.review_ref,
                "mode": "shadow",
            },
        )

    def pending_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._pending_candidates)

    def quarantined_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._quarantined_candidates)

    def catalog_review_packages(self) -> tuple[CatalogReviewPackage, ...]:
        return tuple(self._catalog_review_packages.values())

    def catalog_review_publication_receipts(
        self,
    ) -> tuple[CatalogReviewPublicationReceipt, ...]:
        return tuple(item[2] for _, item in self._published_reviews.items())

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
        updated_at: str | None = None,
    ) -> RulePromotion:
        operational_targets = {
            str(candidate.get("target_rule_id"))
            for candidate in self._pending_candidates
            if candidate.get("source_signal") == "operational_case_fingerprint_cohort"
        }
        draft_rule_ids = {
            str(package.draft_rule.mapping["id"])
            for package in self._catalog_review_packages.values()
        }
        if (
            rule_id.startswith(_OPERATIONAL_RULE_PREFIX)
            or rule_id in operational_targets
            or rule_id in self._published_operational_targets
            or rule_id in draft_rule_ids
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
        promo = RulePromotion(
            rule_id=rule_id, state="enforce", source=source, updated_at=updated_at
        )
        self._promotions[rule_id] = promo
        self._pending_candidates = deque(
            (
                candidate
                for candidate in self._pending_candidates
                if candidate.get("target_rule_id") != rule_id
            ),
        )
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
        return promo

    def status(self, rule_id: str) -> RulePromotion | None:
        return self._promotions.get(rule_id)

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Rule answers rest on tracked promotions and the candidate queue."""
        return bool(self._promotions or self._pending_candidates or self._quarantined_candidates)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_rules": capped_list(sorted(self._promotions)),
            "tracked_rules_count": len(self._promotions),
            "pending_candidates": len(self._pending_candidates),
            "promotion_ready_candidates": len(self.promotion_ready_candidates()),
            "quarantined_candidates": len(self._quarantined_candidates),
            "catalog_review_packages": len(self._catalog_review_packages),
            "catalog_review_publication_receipts": len(self._published_reviews),
            "policy_history_available": False,
        }
        if "policy_history" in semantic_intents(context):
            return IntrospectionResult(
                answer="No governed policy history is bound to this conversational projection.",
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
            answer = f"Rule {promo.rule_id!r} is {promo.state} (source: {promo.source})."
            return IntrospectionResult(answer=answer, facts=facts)
        answer = (
            f"Tracking {len(self._promotions)} rule promotion(s); "
            f"{len(self._pending_candidates)} candidate(s) pending the quality gate."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["CatalogReviewCapacityError", "Mimir", "RulePromotion"]
