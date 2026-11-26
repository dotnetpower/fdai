"""Retain actual membership release evidence and reconcile it only after independent observation.

The decorator never changes an initial closure decision. Reconciliation uses
the original exact plan, release receipt and predecessor identities through the
existing atomic closure store. A provider dispatch receipt cannot resolve it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.human_access_execution import (
    HumanAccessExecutionMaterial,
    human_access_record_digest,
)
from fdai_service_contracts.human_access_workflow import HumanAccessMembershipObservation
from pydantic import TypeAdapter

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
from fdai.shared.providers.resource_lock import ResourceLockReleaseState
from fdai.shared.providers.state_store import StateStore

_PLAN = TypeAdapter(PostReleaseClosurePlan)
_PREFIX = "human_assignment:execution-closure:"


@dataclass(frozen=True, slots=True)
class HumanAccessClosureStore:
    """Delegate original atomic closure and retain immutable exact human membership plan bytes."""

    delegate: PostReleaseClosureStore
    source: StateStore

    @property
    def production_eligible(self) -> bool:
        """Preserve, never manufacture, the underlying atomic store's production eligibility."""
        return (
            isinstance(self.delegate, ProductionSafeguardStore)
            and self.delegate.production_eligible is True
        )

    async def write(self, plan: PostReleaseClosurePlan) -> PostReleaseClosureStoreReceipt:
        """Retain the exact plan before writing; an absent closure remains unknown."""
        if plan.release_receipt.acquisition_receipt.lock_key.startswith(
            "fdai:resource:human-membership:"
        ):
            key = _PREFIX + plan.record.identity.closure_key
            value = {"plan_json": _PLAN.dump_json(plan).decode("utf-8")}
            if plan.record.phase.value == "initial":
                if (
                    not await self.source.write_state_with_audit_if_absent(
                        key,
                        value,
                        {
                            "actor": "Thor",
                            "action_kind": "human_access.release_context.retained",
                            "closure_key": plan.record.identity.closure_key,
                            "mode": "shadow",
                        },
                    )
                    and await self.source.read_state(key) != value
                ):
                    raise ValueError("human access original closure context was rebound")
        return await self.delegate.write(plan)

    async def read(self, closure_key: str) -> PostReleaseClosureRecord | None:
        """Read authoritative closure, never interpret retained context as success."""
        return await self.delegate.read(closure_key)

    async def read_receipt(self, closure_key: str) -> PostReleaseClosureStoreReceipt | None:
        """Preserve exact closure-store readback semantics."""
        return await self.delegate.read_receipt(closure_key)


@dataclass(frozen=True, slots=True)
class HumanAccessClosureReconciler:
    """Resolve one exact-generation quarantine from already validated independent evidence."""

    closures: PostReleaseClosureStore
    source: StateStore
    clock: Callable[[], datetime]
    observer_identity_ref: str

    async def close(
        self,
        *,
        closure_key: str,
        material: HumanAccessExecutionMaterial,
        observation: HumanAccessMembershipObservation,
        observation_ref: str,
    ) -> str:
        """Never invent release/finality proof; reject missing or substituted original context."""
        raw = await self.source.read_state(_PREFIX + closure_key)
        if raw is None or not isinstance(raw.get("plan_json"), str):
            raise ValueError("human access original release context is unavailable")
        original = _PLAN.validate_json(raw["plan_json"], strict=True)
        current = await self.closures.read(closure_key)
        if current is None:
            raise ValueError("human access authoritative post-release closure is missing")
        envelope = await self.source.read_state("human_assignment:" + observation_ref)
        observed_raw = envelope.get("observation") if envelope is not None else None
        if (
            observed_raw != observation.model_dump(mode="json")
            or observation.material_digest != material.digest
            or observation.action_digest != material.action_digest
            or original.pre_release_record.bundle.action_id != material.action().action_id
            or original.release_receipt.acquisition_receipt.lock_key
            != material.membership_plan().membership_lock_key
            or observation.target_digest != material.membership_plan().target_digest
            or observation.observer_identity_ref != self.observer_identity_ref
            or original.release_receipt.state is not ResourceLockReleaseState.RELEASED
        ):
            raise ValueError("human access independent closure evidence changed identity")
        if envelope is None or not isinstance(envelope.get("recorded_at"), str):
            raise ValueError("human access observation persistence readback is missing")
        persisted_at = datetime.fromisoformat(envelope["recorded_at"])
        at = self.clock()
        if not original.record.closed_at <= observation.observed_at <= persisted_at <= at:
            raise ValueError("human access observation is not a post-release durable read")
        digest = "sha256:" + human_access_record_digest(observed_raw)
        if current.outcome is PostReleaseClosureOutcome.RESOLVED:
            if (
                current.identity != original.record.identity
                or current.reconciliation_evidence is None
                or current.release_receipt_digest != original.record.release_receipt_digest
            ):
                raise ValueError(
                    "human access closure was resolved with different original lineage"
                )
            return current.record_digest
        if current != original.record:
            raise ValueError("human access original quarantine predecessor changed")
        if at >= observation.valid_until:
            raise ValueError("human access observation expired before reconciliation")
        evidence = PostReleaseReconciliationEvidence.create(
            kind=ReconciliationEvidenceKind.INDEPENDENT_EFFECT,
            outcome=ReconciliationOutcome.EFFECT_VERIFIED
            if (observation.state == "membership_present")
            is material.membership_plan().desired_membership
            else ReconciliationOutcome.EFFECT_MISMATCH,
            target_digest=current.identity.target_digest,
            target_fence_generation=current.identity.target_fence_generation,
            evidence_identity_digest=current.identity.evidence_identity_digest,
            source_id=observation.observer_identity_ref,
            source_version="1.0.0",
            trust_anchor_id="entra:independent-membership-read",
            evidence_digest=digest,
            observed_at=observation.observed_at,
            persisted_at=persisted_at,
            append_receipt_digest="sha256:"
            + human_access_record_digest({"key": observation_ref, "record": dict(envelope)}),
        )
        plan = build_reconciled_post_release_closure(
            prior_closure=current,
            pre_release_record=original.pre_release_record,
            reservation_record=original.reservation_record,
            quarantined_fence=original.fence_record,
            release_receipt=original.release_receipt,
            evidence=evidence,
            reconciled_at=at,
        )
        receipt = await self.closures.write(plan)
        if receipt.record.outcome is not PostReleaseClosureOutcome.RESOLVED:
            raise ValueError("human access post-release reconciliation did not verify")
        return receipt.record.record_digest


__all__ = ["HumanAccessClosureStore", "HumanAccessClosureReconciler"]
