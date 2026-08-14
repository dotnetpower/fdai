"""Authority-neutral coordination for independently observed mutation effects.

The coordinator validates exact semantic identity and returns an immutable receipt plus a
typed next-step event. It never publishes events, invokes an agent, executes recovery, or
updates the provider-observed ontology graph.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal, Protocol

from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyRelease,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

from .action_plans import validate_action_plan_semantics
from .kinetics import (
    MutationEffectKind,
    MutationPlan,
    ReconciliationReceipt,
    ReconciliationStatus,
)
from .planning import build_mutation_plan
from .projection import reconcile_expected_effects
from .reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
    EffectReconciliationRequest,
    ObservationVerificationReceipt,
    ObservedEffectRecord,
    ReconciliationNextStep,
    ReconciliationOutcome,
    ReconciliationRecommendation,
    reconciliation_content_digest,
)
from .reconciliation_errors import (
    ReconciliationAggregateLimitError,
    ReconciliationAttemptLimitError,
    ReconciliationConflictError,
    ReconciliationLedgerCorruptionError,
)
from .reconciliation_events import (
    ReconciliationOutboxDeliveryState,
    ReconciliationOutboxEvent,
    ReconciliationOutboxRecord,
)
from .reconciliation_state_store import (
    StateStoreReconciliationLedger,
    _outbox_is_claimable,
    _require_claimed_outbox,
    _validate_outbox_lease,
)


class ReconciliationLedger(Protocol):
    """Persistence seam for attempt evidence and atomic terminal outcome plus outbox."""

    async def record_attempt(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome: ...

    async def commit_terminal(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome: ...

    async def claim_outbox(
        self,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> ReconciliationOutboxEvent | None: ...

    async def complete_outbox(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        published_at: datetime,
    ) -> None: ...

    async def release_outbox(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        available_at: datetime,
    ) -> None: ...


class InMemoryReconciliationLedger:
    """Concurrency-safe reference ledger for local composition and focused tests."""

    _MAX_ATTEMPTS_PER_RECONCILIATION = 8

    def __init__(self) -> None:
        self._attempts: dict[str, ReconciliationOutcome] = {}
        self._terminal_outcomes: dict[str, ReconciliationOutcome] = {}
        self._outbox: dict[str, ReconciliationOutboxRecord] = {}
        self._lock = asyncio.Lock()

    @property
    def attempts(self) -> tuple[ReconciliationOutcome, ...]:
        return tuple(self._attempts.values())

    @property
    def terminal_outcomes(self) -> tuple[ReconciliationOutcome, ...]:
        return tuple(self._terminal_outcomes.values())

    @property
    def outbox(self) -> tuple[ReconciliationOutboxEvent, ...]:
        return tuple(record.event for record in self._outbox.values())

    @property
    def outbox_records(self) -> tuple[ReconciliationOutboxRecord, ...]:
        return tuple(self._outbox.values())

    async def record_attempt(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome:
        if outcome.terminal:
            raise ValueError("terminal reconciliation MUST use commit_terminal")
        async with self._lock:
            terminal = self._terminal_outcomes.get(outcome.reconciliation_id)
            if terminal is not None:
                return terminal
            existing = self._attempts.get(outcome.observation_attempt_id)
            if existing is None:
                attempt_count = sum(
                    attempt.reconciliation_id == outcome.reconciliation_id
                    for attempt in self._attempts.values()
                )
                if attempt_count >= self._MAX_ATTEMPTS_PER_RECONCILIATION - 1:
                    raise ReconciliationAttemptLimitError(
                        "reconciliation non-terminal observation attempt limit reached"
                    )
                self._attempts[outcome.observation_attempt_id] = outcome
                return outcome
            if existing.request_digest != outcome.request_digest:
                raise ReconciliationConflictError(
                    "reconciliation attempt identity reused with different request content"
                )
            return existing

    async def commit_terminal(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome:
        """Atomically persist one terminal attempt, outcome, and proposal-only outbox event."""

        if not outcome.terminal:
            raise ValueError("unscorable reconciliation is attempt evidence, not terminal closure")
        async with self._lock:
            existing = self._terminal_outcomes.get(outcome.reconciliation_id)
            if existing is not None:
                return existing
            existing_attempt = self._attempts.get(outcome.observation_attempt_id)
            if (
                existing_attempt is not None
                and existing_attempt.request_digest != outcome.request_digest
            ):
                raise ReconciliationConflictError(
                    "reconciliation attempt identity reused with different request content"
                )
            attempt_count = sum(
                attempt.reconciliation_id == outcome.reconciliation_id
                for attempt in self._attempts.values()
            )
            if existing_attempt is None and attempt_count >= self._MAX_ATTEMPTS_PER_RECONCILIATION:
                raise ReconciliationAttemptLimitError(
                    "reconciliation terminal observation attempt limit reached"
                )
            self._attempts[outcome.observation_attempt_id] = outcome
            self._terminal_outcomes[outcome.reconciliation_id] = outcome
            event = ReconciliationOutboxEvent.from_outcome(outcome)
            self._outbox[event.idempotency_key] = ReconciliationOutboxRecord(event=event)
            return outcome

    async def claim_outbox(
        self,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> ReconciliationOutboxEvent | None:
        """Claim one due event so concurrent drainers cannot publish it simultaneously."""

        _validate_outbox_lease(claimant_id=claimant_id, now=now, lease_until=lease_until)
        async with self._lock:
            for key in sorted(self._outbox):
                record = self._outbox[key]
                if not _outbox_is_claimable(record, now=now):
                    continue
                self._outbox[key] = ReconciliationOutboxRecord(
                    event=record.event,
                    state=ReconciliationOutboxDeliveryState.CLAIMED,
                    attempts=record.attempts + 1,
                    available_at=record.available_at,
                    claimant_id=claimant_id,
                    lease_until=lease_until,
                )
                return record.event
        return None

    async def complete_outbox(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        published_at: datetime,
    ) -> None:
        """Mark a claimed event published after the broker acknowledges it."""

        async with self._lock:
            record = _require_claimed_outbox(
                self._outbox,
                idempotency_key=idempotency_key,
                claimant_id=claimant_id,
            )
            if record.event.result.reconciliation_id != reconciliation_id:
                raise ReconciliationConflictError(
                    "reconciliation outbox event belongs to another aggregate"
                )
            if record.state is ReconciliationOutboxDeliveryState.PUBLISHED:
                return
            self._outbox[idempotency_key] = ReconciliationOutboxRecord(
                event=record.event,
                state=ReconciliationOutboxDeliveryState.PUBLISHED,
                attempts=record.attempts,
                available_at=record.available_at,
                published_at=published_at,
            )

    async def release_outbox(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        available_at: datetime,
    ) -> None:
        """Release a failed publication for deterministic retry with the same event identity."""

        async with self._lock:
            record = _require_claimed_outbox(
                self._outbox,
                idempotency_key=idempotency_key,
                claimant_id=claimant_id,
            )
            if record.event.result.reconciliation_id != reconciliation_id:
                raise ReconciliationConflictError(
                    "reconciliation outbox event belongs to another aggregate"
                )
            if record.state is ReconciliationOutboxDeliveryState.PUBLISHED:
                return
            self._outbox[idempotency_key] = ReconciliationOutboxRecord(
                event=record.event,
                attempts=record.attempts,
                available_at=available_at,
            )


class EffectReconciliationCoordinator:
    """Validate and close one effect observation without acquiring action authority."""

    def __init__(self, *, ledger: ReconciliationLedger) -> None:
        self._ledger = ledger

    async def coordinate(
        self,
        request: EffectReconciliationRequest,
        *,
        observation_context: AuthenticatedObservationContext,
        active_release: OntologyRelease,
    ) -> ReconciliationOutcome:
        """Return a duplicate-stable receipt and recommendation for a validated request."""

        validated = EffectReconciliationRequest.model_validate_json(request.model_dump_json())
        authenticated = AuthenticatedObservationContext.model_validate_json(
            observation_context.model_dump_json()
        )
        release = OntologyRelease.model_validate_json(active_release.model_dump_json())
        _validate_plan_integrity(validated.plan)
        _validate_exact_bindings(validated, release)
        _validate_authenticated_binding(validated, authenticated)
        unscorable_reason = _independent_observation_reason(authenticated)
        if unscorable_reason is not None:
            receipt = ReconciliationReceipt(
                plan_digest=validated.plan.digest,
                status=ReconciliationStatus.UNSCORABLE,
                observed_at=validated.evidence.observed_at,
                evidence_refs=validated.evidence.evidence_refs,
            )
        elif validated.evaluated_at > validated.deadline:
            receipt = ReconciliationReceipt(
                plan_digest=validated.plan.digest,
                status=ReconciliationStatus.TIMED_OUT,
                observed_at=validated.evidence.observed_at,
                evidence_refs=validated.evidence.evidence_refs,
            )
        else:
            unscorable_reason = _unscorable_reason(validated, release, authenticated)
            if unscorable_reason is not None:
                receipt = ReconciliationReceipt(
                    plan_digest=validated.plan.digest,
                    status=ReconciliationStatus.UNSCORABLE,
                    observed_at=validated.evidence.observed_at,
                    evidence_refs=validated.evidence.evidence_refs,
                )
            else:
                receipt = reconcile_expected_effects(
                    plan=validated.plan,
                    observed={
                        item.object_id: item.to_record() for item in validated.evidence.records
                    },
                    observed_at=validated.evidence.observed_at,
                    deadline=validated.deadline,
                    evidence_refs=validated.evidence.evidence_refs,
                )
        outcome = _build_outcome(
            validated,
            authenticated,
            receipt,
            unscorable_reason=unscorable_reason,
        )
        if outcome.terminal:
            return await self._ledger.commit_terminal(outcome)
        return await self._ledger.record_attempt(outcome)


def _validate_plan_integrity(plan: MutationPlan) -> None:
    targets = tuple(
        OntologyObjectRecord(
            id=target.object_id,
            object_type=target.type_ref.name,
            properties={},
            revision=target.revision,
            type_ref=target.type_ref,
        )
        for target in plan.targets
    )
    rebuilt = build_mutation_plan(
        action_type_ref=plan.action_type_ref,
        planner_ref=plan.planner_ref,
        targets=targets,
        effects=plan.effects,
        rollback_effects=plan.rollback_effects,
        expected_effects=plan.expected_effects,
        created_at=plan.created_at,
        max_affected_objects=plan.max_affected_objects or len(targets),
        schema_version=plan.schema_version,
        arguments_digest=plan.arguments_digest,
        argument_bindings=plan.argument_bindings,
        read_set_receipt_digests=plan.read_set_receipt_digests,
        criterion_receipt_digests=plan.criterion_receipt_digests,
        transaction_mode=plan.transaction_mode,
        lock_scope=plan.lock_scope,
        lock_keys=plan.lock_keys,
        irreversible=plan.irreversible,
        operational_plan_ref=plan.operational_plan_ref,
    )
    if rebuilt.digest != plan.digest or rebuilt.plan_id != plan.plan_id:
        raise ValueError("reconciliation plan digest does not match plan content")


def _validate_exact_bindings(
    request: EffectReconciliationRequest,
    release: OntologyRelease,
) -> None:
    evidence = request.evidence
    if evidence.plan_digest != request.plan.digest:
        raise ValueError("effect evidence plan digest does not match reconciliation plan")
    if evidence.ontology_release_ref != release.ref():
        raise ValueError("effect evidence ontology release is not active")
    if request.plan.action_type_ref.kind is not OntologyDeclarationKind.ACTION:
        raise ValueError("reconciliation plan action ref MUST identify an ActionType")
    try:
        active_action_ref = release.type_ref(
            OntologyDeclarationKind.ACTION,
            request.plan.action_type_ref.name,
        )
    except KeyError as exc:
        raise ValueError("reconciliation ActionType is absent from the active release") from exc
    if request.plan.action_type_ref != active_action_ref:
        raise ValueError("reconciliation plan ActionType ref is stale")
    if evidence.action_type_ref != active_action_ref:
        raise ValueError("effect evidence ActionType ref does not match the plan")


def _validate_authenticated_binding(
    request: EffectReconciliationRequest,
    context: AuthenticatedObservationContext,
) -> None:
    evidence = request.evidence
    receipt = context.verification_receipt
    if receipt.observation_id != evidence.observation_id:
        raise ValueError("observation verification receipt binds another observation")
    if receipt.observation_digest != evidence.content_digest():
        raise ValueError("observation verification receipt content digest does not match")
    if receipt.verified_at < evidence.recorded_at:
        raise ValueError("observation verification MUST NOT precede evidence recording")
    if receipt.verified_at > request.evaluated_at:
        raise ValueError("observation verification MUST NOT follow reconciliation evaluation")
    if (
        context.observer_identity != evidence.observer_identity
        or context.executor_identity != evidence.execution_identity
        or context.source_identity != evidence.source_identity
    ):
        raise ValueError("authenticated observation identities do not match the envelope")


def _independent_observation_reason(
    context: AuthenticatedObservationContext,
) -> str | None:
    """Return why authenticated evidence cannot independently close an effect."""

    if context.source_authority not in {
        EffectEvidenceAuthority.PROVIDER,
        EffectEvidenceAuthority.TELEMETRY,
    }:
        return "source_not_authoritative"
    normalized_identities = {
        context.observer_identity.strip().casefold(),
        context.executor_identity.strip().casefold(),
        context.source_identity.strip().casefold(),
    }
    if len(normalized_identities) != 3:
        return "observation_not_independent"
    normalized_credentials = {
        context.observer_credential_lineage.strip().casefold(),
        context.executor_credential_lineage.strip().casefold(),
        context.source_credential_lineage.strip().casefold(),
    }
    if len(normalized_credentials) != 3:
        return "observation_credential_not_independent"
    return None


def _unscorable_reason(
    request: EffectReconciliationRequest,
    release: OntologyRelease,
    context: AuthenticatedObservationContext,
) -> str | None:
    evidence = request.evidence
    if request.plan.schema_version != "2.0.0" or request.action_type is None:
        return "semantic_effect_coverage_unproven"
    try:
        validate_action_plan_semantics(
            action_type=request.action_type,
            release=release,
            plan=request.plan,
        )
    except (KeyError, ValueError):
        return "semantic_effect_coverage_unproven"
    if not evidence.complete:
        return "observation_incomplete"
    if evidence.synthetic:
        return "observation_synthetic"
    if evidence.conflicts:
        return "observation_conflicted"
    if evidence.fresh_until < request.evaluated_at:
        return "observation_stale"
    if any(
        effect.kind is not MutationEffectKind.EXPECTED_PROPERTY
        for effect in request.plan.expected_effects
    ):
        return "unsupported_expected_effect"
    target_by_id = {target.object_id: target for target in request.plan.targets}
    for record in evidence.records:
        target = target_by_id.get(record.object_id)
        if target is None:
            return "observation_outside_plan"
        try:
            active_ref = release.type_ref(record.type_ref.kind, record.type_ref.name)
        except KeyError:
            return "observation_type_not_active"
        if record.type_ref != active_ref or record.type_ref != target.type_ref:
            return "observation_type_mismatch"
        if record.revision < target.revision:
            return "observation_revision_stale"
    return None


def _build_outcome(
    request: EffectReconciliationRequest,
    observation_context: AuthenticatedObservationContext,
    receipt: ReconciliationReceipt,
    *,
    unscorable_reason: str | None,
) -> ReconciliationOutcome:
    receipt_digest = reconciliation_content_digest(receipt.model_dump(mode="json"))
    observation_context_digest = observation_context.content_digest()
    verification_receipt_digest = observation_context.verification_receipt.receipt_digest
    target_agent: Literal["vidar"] | None
    if receipt.status is ReconciliationStatus.MATCHED:
        next_step = ReconciliationNextStep.CLOSE_MATCHED
        reason_code = "effects_matched"
        target_agent = None
    elif receipt.status in {ReconciliationStatus.MISMATCHED, ReconciliationStatus.TIMED_OUT}:
        next_step = ReconciliationNextStep.REQUEST_VIDAR_RECOVERY
        reason_code = f"effects_{receipt.status.value}"
        target_agent = "vidar"
    else:
        next_step = ReconciliationNextStep.HOLD_UNSCORABLE
        reason_code = unscorable_reason or "effects_unscorable"
        target_agent = None
    recommendation = ReconciliationRecommendation.create(
        reconciliation_id=request.reconciliation_id,
        observation_attempt_id=request.observation_attempt_id,
        correlation_id=request.correlation_id,
        ontology_release_ref=request.evidence.ontology_release_ref,
        action_type_ref=request.plan.action_type_ref,
        plan_digest=request.plan.digest,
        observation_id=request.evidence.observation_id,
        request_digest=request.request_digest,
        receipt_digest=receipt_digest,
        observation_context_digest=observation_context_digest,
        verification_receipt_digest=verification_receipt_digest,
        next_step=next_step,
        reason_code=reason_code,
        target_agent=target_agent,
    )
    return ReconciliationOutcome(
        reconciliation_id=request.reconciliation_id,
        observation_attempt_id=request.observation_attempt_id,
        correlation_id=request.correlation_id,
        request_digest=request.request_digest,
        receipt_digest=receipt_digest,
        observation_context_digest=observation_context_digest,
        verification_receipt_digest=verification_receipt_digest,
        observation_context=observation_context,
        request=request,
        receipt=receipt,
        recommendation=recommendation,
        terminal=receipt.status is not ReconciliationStatus.UNSCORABLE,
    )


__all__ = [
    "AuthenticatedObservationContext",
    "EffectEvidenceAuthority",
    "EffectObservationEnvelope",
    "EffectReconciliationCoordinator",
    "EffectReconciliationRequest",
    "InMemoryReconciliationLedger",
    "ObservedEffectRecord",
    "ObservationVerificationReceipt",
    "ReconciliationAggregateLimitError",
    "ReconciliationAttemptLimitError",
    "ReconciliationConflictError",
    "ReconciliationLedger",
    "ReconciliationLedgerCorruptionError",
    "ReconciliationNextStep",
    "ReconciliationOutcome",
    "ReconciliationRecommendation",
    "StateStoreReconciliationLedger",
]
