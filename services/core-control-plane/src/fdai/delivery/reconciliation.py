"""Production adapters for exact artifact and independent observation reconciliation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Protocol

from fdai.core.ontology_platform.kinetics import MutationPlan
from fdai.core.ontology_platform.planning import build_mutation_plan, validate_plan_revisions
from fdai.core.ontology_platform.reconciliation_binding import ResolvedReconciliationArtifacts
from fdai.core.ontology_platform.reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
)
from fdai.core.ontology_platform.reconciliation_events import EffectReconciliationRequestEvent
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyRelease,
    OntologyTypeRef,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyObjectRecord


class ReconciliationTargetReader(Protocol):
    """Read the current exact revision of one ontology target."""

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None: ...


class ObservationContextAuthenticator(Protocol):
    """Authenticate a signed observation context against its credential source."""

    async def authenticate(
        self,
        *,
        evidence: EffectObservationEnvelope,
        claimed_context: AuthenticatedObservationContext,
    ) -> AuthenticatedObservationContext: ...


class LocalReconciliationArtifactResolver:
    """Restore exact local artifact bodies and reject stale target snapshots.

    Bodies are canonicalized to immutable JSON at construction. Resolution accepts only the
    active release, an ActionType whose body digest belongs to that release, an integrity-valid
    plan with the event's exact digest, and targets that still have the plan's pinned revisions.
    """

    def __init__(
        self,
        *,
        active_release: OntologyRelease,
        action_types: Sequence[OntologyActionType],
        plans: Sequence[MutationPlan],
        target_reader: ReconciliationTargetReader,
        timeout_seconds: float = 2.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("reconciliation artifact timeout MUST be positive")
        release = OntologyRelease.model_validate_json(active_release.model_dump_json())
        action_bodies: dict[str, str] = {}
        for supplied_action in action_types:
            action = OntologyActionType.model_validate_json(supplied_action.model_dump_json())
            action_ref = release.type_ref(OntologyDeclarationKind.ACTION, action.name)
            if action_ref.version != action.version:
                raise ValueError("reconciliation ActionType version is absent from active release")
            declaration = next(
                item
                for item in release.declarations
                if item.kind is OntologyDeclarationKind.ACTION and item.name == action.name
            )
            action_declaration = build_ontology_release(action_types=(action,)).declarations[0]
            if action_declaration.declaration_digest != declaration.declaration_digest:
                raise ValueError("reconciliation ActionType body does not match active release")
            key = _type_ref_key(action_ref)
            body = action.model_dump_json()
            if key in action_bodies and action_bodies[key] != body:
                raise ValueError("reconciliation ActionType ref has conflicting local bodies")
            action_bodies[key] = body

        plan_bodies: dict[str, str] = {}
        for supplied_plan in plans:
            plan = MutationPlan.model_validate_json(supplied_plan.model_dump_json())
            _validate_plan_integrity(plan)
            body = plan.model_dump_json()
            if plan.digest in plan_bodies and plan_bodies[plan.digest] != body:
                raise ValueError("reconciliation plan digest has conflicting local bodies")
            plan_bodies[plan.digest] = body

        self._release_body = release.model_dump_json()
        self._action_bodies: Mapping[str, str] = MappingProxyType(action_bodies)
        self._plan_bodies: Mapping[str, str] = MappingProxyType(plan_bodies)
        self._target_reader = target_reader
        self._timeout_seconds = timeout_seconds

    async def resolve(
        self,
        event: EffectReconciliationRequestEvent,
    ) -> ResolvedReconciliationArtifacts:
        """Resolve and verify one compact event within the artifact budget."""

        async with asyncio.timeout(self._timeout_seconds):
            release = OntologyRelease.model_validate_json(self._release_body)
            if event.ontology_release_ref != release.ref():
                raise ValueError("reconciliation event ontology release is stale")
            plan_body = self._plan_bodies.get(event.plan_digest)
            if plan_body is None:
                raise ValueError("reconciliation event plan digest is not available locally")
            action_body = self._action_bodies.get(_type_ref_key(event.action_type_ref))
            if action_body is None:
                raise ValueError("reconciliation event ActionType ref is not available locally")
            plan = MutationPlan.model_validate_json(plan_body)
            action_type = OntologyActionType.model_validate_json(action_body)
            current_records = await asyncio.gather(
                *(self._target_reader.get_object(target.object_id) for target in plan.targets)
            )
            current = {record.id: record for record in current_records if record is not None}
            validate_plan_revisions(plan, current)
            event.bind(plan=plan, action_type=action_type, active_release=release)
            return ResolvedReconciliationArtifacts(
                plan=plan,
                action_type=action_type,
                active_release=release,
            )


class IndependentObservationContextVerifier:
    """Authenticate and enforce observer, executor, and source separation of duty."""

    def __init__(
        self,
        *,
        authenticator: ObservationContextAuthenticator,
        timeout_seconds: float = 2.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("observation verification timeout MUST be positive")
        self._authenticator = authenticator
        self._timeout_seconds = timeout_seconds

    async def verify(
        self,
        *,
        evidence: EffectObservationEnvelope,
        claimed_context: AuthenticatedObservationContext,
    ) -> AuthenticatedObservationContext:
        """Return the exact authenticated context or reject untrusted lineage claims."""

        async with asyncio.timeout(self._timeout_seconds):
            authenticated = await self._authenticator.authenticate(
                evidence=evidence,
                claimed_context=claimed_context,
            )
        authenticated = AuthenticatedObservationContext.model_validate_json(
            authenticated.model_dump_json()
        )
        if authenticated != claimed_context:
            raise ValueError("authenticated observation context differs from claimed context")
        receipt = authenticated.verification_receipt
        if (
            receipt.observation_id != evidence.observation_id
            or receipt.observation_digest != evidence.content_digest()
        ):
            raise ValueError("observation verification receipt does not bind exact evidence")
        if authenticated.source_authority not in {
            EffectEvidenceAuthority.PROVIDER,
            EffectEvidenceAuthority.TELEMETRY,
        }:
            raise ValueError("observation source is not independently authoritative")
        if (
            authenticated.observer_identity != evidence.observer_identity
            or authenticated.executor_identity != evidence.execution_identity
            or authenticated.source_identity != evidence.source_identity
        ):
            raise ValueError("authenticated observation identities do not match evidence")
        _require_distinct(
            "observation identities",
            authenticated.observer_identity,
            authenticated.executor_identity,
            authenticated.source_identity,
            receipt.verifier_identity,
        )
        _require_distinct(
            "observation credential lineages",
            authenticated.observer_credential_lineage,
            authenticated.executor_credential_lineage,
            authenticated.source_credential_lineage,
            receipt.verifier_credential_lineage,
        )
        return authenticated


def _type_ref_key(reference: OntologyTypeRef) -> str:
    return reference.model_dump_json()


def _require_distinct(label: str, *values: str) -> None:
    normalized = {value.strip().casefold() for value in values}
    if len(normalized) != len(values):
        raise ValueError(f"{label} MUST be distinct")


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
    )
    if rebuilt.digest != plan.digest or rebuilt.plan_id != plan.plan_id:
        raise ValueError("reconciliation plan digest does not match local body")


__all__ = [
    "IndependentObservationContextVerifier",
    "LocalReconciliationArtifactResolver",
    "ObservationContextAuthenticator",
    "ReconciliationTargetReader",
]
