"""Exact-target original release context for independent acceptance-effect reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fdai.core.executor.post_release_closure import (
    PostReleaseClosureOutcome,
    PostReleaseClosureRecord,
    PostReleaseReconciliationEvidence,
    ReconciliationEvidenceKind,
    ReconciliationOutcome,
)
from fdai.core.executor.post_release_closure_plan import (
    PostReleaseClosurePlan,
    build_reconciled_post_release_closure,
)
from fdai.core.executor.post_release_closure_store import (
    PostReleaseClosureStore,
    PostReleaseClosureStoreReceipt,
)
from fdai.core.executor.safeguard_lifecycle_models import ProductionSafeguardStore
from fdai.core.executor.safeguards import full_action_digest, resource_lock_key
from fdai.runtime.isolated_executor_receipt_journal import BoundCommandCorrelation
from fdai.shared.contracts.models import ExecutorEffectReceipt, Mode
from fdai.shared.providers.executor_receipt_journal import receipt_matches_command
from fdai.shared.providers.resource_lock import ResourceLockReleaseState
from fdai.shared.providers.state_store import StateStore
from pydantic import TypeAdapter

from fdai_aks_commerce.acceptance import (
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    evaluate_order_acceptance,
)
from fdai_aks_commerce.acceptance_action import ACCEPTANCE_SIGNAL
from fdai_aks_commerce.acceptance_material import StoredAcceptanceDispatchMaterials
from fdai_aks_commerce.acceptance_receipts import (
    RECEIPT_PREFIX,
    StoredOrderAcceptanceReceiptVerifier,
)
from fdai_aks_commerce.acceptance_store import StoredOrderAcceptanceSource
from fdai_aks_commerce.effect import AcceptanceEffectExpectation, verify_order_acceptance_effect

_PLAN = TypeAdapter(PostReleaseClosurePlan)
CLOSURE_PREFIX = "aks-commerce:acceptance-closure:v1:"


@dataclass(frozen=True, slots=True)
class AcceptanceClosureResult:
    """Exact independently verified closure evidence for downstream lifecycle owners."""

    record_digest: str
    evidence_ref: str
    observed_at: datetime


ResolveVerifiedIncident = Callable[..., Awaitable[str]]


@dataclass(frozen=True, slots=True)
class AcceptanceClosureStore:
    """Preserve original closure semantics while retaining one configured target's exact plan."""

    delegate: PostReleaseClosureStore
    source: StateStore
    intent: OrderAcceptanceIntent

    @property
    def production_eligible(self) -> bool:
        """Forward only eligibility already proven by the underlying atomic store."""
        return (
            isinstance(self.delegate, ProductionSafeguardStore)
            and self.delegate.production_eligible is True
        )

    async def write(self, plan: PostReleaseClosurePlan) -> PostReleaseClosureStoreReceipt:
        """Retain owned initial context without changing its decision or manufacturing evidence."""
        lock_key = plan.release_receipt.acquisition_receipt.lock_key
        if (
            lock_key == resource_lock_key(self.intent.resource_ref)
            and plan.record.phase.value == "initial"
        ):
            material = await StoredAcceptanceDispatchMaterials(self.source).read(
                str(plan.pre_release_record.bundle.action_id)
            )
            if material is not None:
                action = material.action()
                if (
                    action.target_resource_ref != self.intent.resource_ref
                    or full_action_digest(action)
                    != plan.release_receipt.acquisition_receipt.action_digest
                    or action.params.get("target_uid") != self.intent.deployment_uid
                    or action.params.get("replica_count") != self.intent.minimum_replicas
                    or action.mode is not Mode.ENFORCE
                ):
                    raise ValueError("acceptance release context does not match original Action")
                key = CLOSURE_PREFIX + plan.record.identity.closure_key
                value = {
                    "plan_json": _PLAN.dump_json(plan).decode(),
                    "action_json": material.action_json,
                }
                created = await self.source.write_state_with_audit_if_absent(
                    key,
                    value,
                    {
                        "actor": "Thor",
                        "action_kind": "aks_commerce.release_context.retained",
                        "closure_key": plan.record.identity.closure_key,
                        "action_id": str(action.action_id),
                        "mode": action.mode.value,
                        "execution_authority": False,
                    },
                )
                if not created and await self.source.read_state(key) != value:
                    raise ValueError("acceptance original release context was rebound")
        return await self.delegate.write(plan)

    async def read(self, closure_key: str) -> PostReleaseClosureRecord | None:
        """Read the authoritative state; retained context alone never resolves quarantine."""
        return await self.delegate.read(closure_key)

    async def read_receipt(self, closure_key: str) -> PostReleaseClosureStoreReceipt | None:
        """Preserve the existing store's exact receipt semantics."""
        return await self.delegate.read_receipt(closure_key)


@dataclass(frozen=True, slots=True)
class _SnapshotSource:
    evidence: OrderAcceptanceEvidence

    async def observe(self, intent: OrderAcceptanceIntent) -> OrderAcceptanceEvidence:
        return self.evidence


@dataclass(frozen=True, slots=True)
class AcceptanceClosureReconciler:
    """Independently verify an owned scale before reconciling its exact released quarantine.

    Invoke only from the observer-owned event path. This adapter never dispatches, approves or
    retries an Action. A resolved execution closure is not an Incident state transition.
    """

    closures: PostReleaseClosureStore
    store: StateStore
    intent: OrderAcceptanceIntent
    verifier: StoredOrderAcceptanceReceiptVerifier
    clock: Callable[[], datetime]

    async def reconcile(self, command_id: str) -> AcceptanceClosureResult:
        """Read original durable command/receipt and new signed evidence within a bounded budget."""
        if str(UUID(command_id)) != command_id:
            raise ValueError("acceptance effect requires a canonical command id")
        async with asyncio.timeout(10):
            return await self._reconcile(command_id)

    async def _reconcile(self, command_id: str) -> AcceptanceClosureResult:
        prefix = "runtime:isolated-executor:"
        raw_command = await self.store.read_state(prefix + "command:" + command_id)
        raw_receipt = await self.store.read_state(prefix + "terminal-receipt:" + command_id)
        if (
            raw_command is None
            or raw_receipt is None
            or await self.store.read_state(prefix + "not-published:" + command_id) is not None
        ):
            raise ValueError("acceptance original published command and receipt are unavailable")
        correlation = BoundCommandCorrelation.model_validate(raw_command)
        command = correlation.command
        receipt = ExecutorEffectReceipt.model_validate(raw_receipt)
        material = await StoredAcceptanceDispatchMaterials(self.store).read(str(command.action_id))
        if material is None or not material.evidence_refs:
            raise ValueError(
                "acceptance original Action and observation references are unavailable"
            )
        action = material.action()
        if (
            str(command.command_id) != command_id
            or command.action_payload != action.model_dump(mode="json", exclude_none=True)
            or action.target_resource_ref != self.intent.resource_ref
            or action.mode is not Mode.ENFORCE
            or not receipt_matches_command(command, receipt, partition_key=command.partition_key)
            or receipt.status.value not in {"dispatched", "already_applied"}
            or receipt.effect_applied is not True
            or not receipt.provider_receipt_ref
            or not command.issued_at <= receipt.received_at <= receipt.completed_at <= self.clock()
            or receipt.received_at > command.deadline_at
        ):
            raise ValueError("acceptance provider receipt does not bind the original Action")
        raw = await self.store.read_state(CLOSURE_PREFIX + correlation.closure_key)
        if (
            raw is None
            or set(raw) != {"plan_json", "action_json"}
            or raw.get("action_json") != material.action_json
            or not isinstance(raw.get("plan_json"), str)
        ):
            raise ValueError("acceptance original release context is unavailable or changed")
        original = _PLAN.validate_json(raw["plan_json"], strict=True)
        current = await self.closures.read(correlation.closure_key)
        if (
            current is None
            or current.identity != original.record.identity
            or original.record.identity.closure_key != correlation.closure_key
            or original.record.identity.target_digest != correlation.target_digest
            or original.record.identity.target_fence_generation
            != correlation.target_fence_generation
            or original.record.identity.evidence_identity_digest
            != correlation.evidence_identity_digest
            or original.pre_release_record.bundle.action_id != action.action_id
            or original.pre_release_record.bundle.bundle_digest
            != command.safeguard_proof_bundle_digest
            or original.release_receipt.state is not ResourceLockReleaseState.RELEASED
            or original.release_receipt.acquisition_receipt.action_digest
            != full_action_digest(action)
            or original.release_receipt.acquisition_receipt.lock_key
            != resource_lock_key(self.intent.resource_ref)
        ):
            raise ValueError("acceptance released closure identity or generation does not match")
        if current.outcome is PostReleaseClosureOutcome.RESOLVED:
            prior = current.reconciliation_evidence
            if (
                prior is None
                or prior.kind is not ReconciliationEvidenceKind.INDEPENDENT_EFFECT
                or prior.outcome is not ReconciliationOutcome.EFFECT_VERIFIED
            ):
                raise ValueError("acceptance closure lacks its original independent effect proof")
            retained_effect = await self.store.read_state(
                CLOSURE_PREFIX + "observation:" + prior.evidence_digest
            )
            if (
                retained_effect is None
                or retained_effect.get("command_id") != command_id
                or retained_effect.get("closure_key") != correlation.closure_key
                or retained_effect.get("effect_ref") != prior.evidence_digest
                or retained_effect.get("observer_identity") != prior.source_id
            ):
                raise ValueError(
                    "acceptance resolved closure lost its original independent observation"
                )
            digest = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(retained_effect, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
            )
            if (
                digest != prior.append_receipt_digest
                or current.release_receipt_digest != original.record.release_receipt_digest
            ):
                raise ValueError("acceptance resolved closure evidence was substituted")
            return AcceptanceClosureResult(
                record_digest=current.record_digest,
                evidence_ref=prior.evidence_digest,
                observed_at=prior.observed_at,
            )
        observation = await StoredOrderAcceptanceSource(self.store).observe(self.intent)
        if observation is None:
            raise ValueError("acceptance independent post-release observation is unavailable")
        expectation = AcceptanceEffectExpectation(
            action_run_ref=material.correlation_id,
            provider_receipt_ref=receipt.provider_receipt_ref,
            target_ref=action.target_resource_ref,
            deployment_uid=str(action.params.get("target_uid") or ""),
            replica_count=action.params["replica_count"],
            applied_at=max(receipt.completed_at, original.record.closed_at),
            before_evidence_refs=material.evidence_refs,
        )
        verified = await verify_order_acceptance_effect(
            expectation=expectation,
            intent=self.intent,
            source=_SnapshotSource(observation),
            verifier=self.verifier,
            clock=self.clock,
        )
        if verified.status != "verified" or verified.evidence_ref is None:
            raise ValueError("acceptance independent post-release effect is not verified")
        attestation = await self.store.read_state(RECEIPT_PREFIX + observation.verification_ref)
        assessment = evaluate_order_acceptance(
            self.intent, observation, now=self.clock(), window_seconds=self.intent.max_age_seconds
        )
        if attestation is None or not await self.verifier.verify_record(
            attestation,
            verification_ref=observation.verification_ref,
            evidence_digest=assessment.evidence_digest,
        ):
            raise ValueError("acceptance effect attestation changed before reconciliation")
        recorded_at = self.clock()
        evidence_key = CLOSURE_PREFIX + "observation:" + verified.evidence_ref
        envelope = {
            "command_id": command_id,
            "closure_key": correlation.closure_key,
            "effect_ref": verified.evidence_ref,
            "observation_digest": assessment.evidence_digest,
            "observer_identity": attestation["source_identity"],
            "observed_at": observation.observed_at.isoformat(),
            "recorded_at": recorded_at.isoformat(),
        }
        created = await self.store.write_state_with_audit_if_absent(
            evidence_key,
            envelope,
            {
                "actor": "Heimdall",
                "action_kind": "aks_commerce.independent_effect.retained",
                "effect_ref": verified.evidence_ref,
                "execution_authority": False,
            },
        )
        retained = await self.store.read_state(evidence_key)
        if retained is None or any(
            retained.get(key) != value for key, value in envelope.items() if key != "recorded_at"
        ):
            raise ValueError("acceptance independent observation persistence mismatch")
        if not created:
            recorded_at = datetime.fromisoformat(str(retained["recorded_at"]))
        if not original.record.closed_at < observation.observed_at <= recorded_at <= self.clock():
            raise ValueError(
                "acceptance independent observation is not a durable post-release read"
            )
        if current != original.record:
            raise ValueError("acceptance original quarantine predecessor changed")
        evidence = PostReleaseReconciliationEvidence.create(
            kind=ReconciliationEvidenceKind.INDEPENDENT_EFFECT,
            outcome=ReconciliationOutcome.EFFECT_VERIFIED,
            target_digest=current.identity.target_digest,
            target_fence_generation=current.identity.target_fence_generation,
            evidence_identity_digest=current.identity.evidence_identity_digest,
            source_id=str(attestation["source_identity"]),
            source_version="1.0.0",
            trust_anchor_id="aks-commerce:pinned-acceptance-receipt",
            evidence_digest=verified.evidence_ref,
            observed_at=observation.observed_at,
            persisted_at=recorded_at,
            append_receipt_digest="sha256:"
            + hashlib.sha256(
                json.dumps(retained, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        plan = build_reconciled_post_release_closure(
            prior_closure=current,
            pre_release_record=original.pre_release_record,
            reservation_record=original.reservation_record,
            quarantined_fence=original.fence_record,
            release_receipt=original.release_receipt,
            evidence=evidence,
            reconciled_at=self.clock(),
        )
        after = evaluate_order_acceptance(
            self.intent, observation, now=self.clock(), window_seconds=self.intent.max_age_seconds
        )
        if after.status != "accepting" or not await self.verifier.verify_record(
            attestation,
            verification_ref=observation.verification_ref,
            evidence_digest=after.evidence_digest,
        ):
            raise ValueError("acceptance independent evidence expired before closure write")
        receipt_result = await self.closures.write(plan)
        if (
            receipt_result.record != plan.record
            or receipt_result.record.outcome is not PostReleaseClosureOutcome.RESOLVED
        ):
            raise ValueError("acceptance atomic closure did not confirm the exact reconciliation")
        return AcceptanceClosureResult(
            record_digest=receipt_result.record.record_digest,
            evidence_ref=verified.evidence_ref,
            observed_at=observation.observed_at,
        )


@dataclass(frozen=True, slots=True)
class AcceptanceEffectObserver:
    """Heimdall-owned hook using original journal records, never event effect claims."""

    reconciler: AcceptanceClosureReconciler
    resolve_verified_incident: ResolveVerifiedIncident | None = None

    async def handle(self, payload: Mapping[str, Any]) -> bool | Mapping[str, Any]:
        """Reconcile an exact non-shadow attempt, leaving missing evidence retryable and held."""
        if payload.get("resource_id") != self.reconciler.intent.resource_ref:
            return False
        if payload.get("action_type") != "ops.scale-out" or payload.get("shadow_mode") is True:
            return False
        if payload.get("state") not in {"execution_unknown", "succeeded"}:
            return False
        if payload.get("producer_principal") != "Thor" or payload.get("shadow_mode") is not False:
            raise ValueError("acceptance effect trigger requires Thor's non-shadow ActionRun")
        action_id = payload.get("action_id")
        if not isinstance(action_id, str):
            raise ValueError("acceptance effect trigger requires the original Action id")
        material = await StoredAcceptanceDispatchMaterials(self.reconciler.store).read(action_id)
        if (
            material is None
            or payload.get("action_type") != "ops.scale-out"
            or payload.get("correlation_id") != material.correlation_id
            or payload.get("action_idempotency_key") != material.action_run_idempotency_key
            or payload.get("params") != material.action().params
        ):
            raise ValueError("acceptance effect trigger changed original ActionRun identity")
        link = await self.reconciler.store.read_state(
            "aks-commerce:acceptance-command:v1:" + action_id
        )
        if link is None or not isinstance(link.get("command_id"), str):
            raise RuntimeError("acceptance original command linkage is not yet available")
        result = await self.reconciler.reconcile(link["command_id"])
        return {
            "schema_version": "1.0.0",
            "event_type": "action.execution.effect_verified.v1",
            "producer_principal": "Heimdall",
            "correlation_id": material.correlation_id,
            "idempotency_key": "sha256:"
            + hashlib.sha256(f"{action_id}\0{result.record_digest}".encode()).hexdigest(),
            "resource_id": self.reconciler.intent.resource_ref,
            "action_id": action_id,
            "action_type": "ops.scale-out",
            "action_idempotency_key": material.action_run_idempotency_key,
            "params": material.action().params,
            "effect_verification_ref": result.evidence_ref,
            "execution_closure_ref": result.record_digest,
            "observed_at": result.observed_at.isoformat(),
            "execution_authority": False,
        }

    async def resolve_incident(self, payload: Mapping[str, Any]) -> bool:
        """Resolve the exact bound Incident only from the retained verified closure event."""
        if payload.get("event_type") != "action.execution.effect_verified.v1":
            return False
        if (
            payload.get("producer_principal") != "Heimdall"
            or payload.get("schema_version") != "1.0.0"
            or payload.get("action_type") != "ops.scale-out"
            or payload.get("execution_authority") is not False
        ):
            raise ValueError("acceptance Incident resolution requires Heimdall evidence")
        action_id = payload.get("action_id")
        if not isinstance(action_id, str):
            raise ValueError("acceptance Incident resolution requires an Action id")
        material = await StoredAcceptanceDispatchMaterials(self.reconciler.store).read(action_id)
        link = await self.reconciler.store.read_state(
            "aks-commerce:acceptance-command:v1:" + action_id
        )
        closure_key = link.get("closure_key") if link is not None else None
        closure = (
            await self.reconciler.closures.read(str(closure_key))
            if isinstance(closure_key, str)
            else None
        )
        evidence = closure.reconciliation_evidence if closure is not None else None
        observed_at = datetime.fromisoformat(str(payload.get("observed_at") or ""))
        if (
            material is None
            or closure is None
            or closure.outcome is not PostReleaseClosureOutcome.RESOLVED
            or evidence is None
            or payload.get("correlation_id") != material.correlation_id
            or payload.get("action_idempotency_key") != material.action_run_idempotency_key
            or payload.get("resource_id") != self.reconciler.intent.resource_ref
            or payload.get("params") != material.action().params
            or payload.get("effect_verification_ref") != evidence.evidence_digest
            or payload.get("execution_closure_ref") != closure.record_digest
            or observed_at != evidence.observed_at
        ):
            raise ValueError("acceptance Incident resolution evidence changed")
        if self.resolve_verified_incident is None:
            raise RuntimeError("acceptance Incident episode resolver is unavailable")
        await self.resolve_verified_incident(
            action_idempotency_key=material.action_run_idempotency_key,
            correlation_id=material.correlation_id,
            resource_id=self.reconciler.intent.resource_ref,
            event_type=ACCEPTANCE_SIGNAL,
            verified_at=observed_at,
        )
        return True
