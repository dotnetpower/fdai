"""Pure intersection resolver for execution-authorization policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fdai.rule_catalog.schema.scope import ResourceContext, ScopeRef

from .models import (
    AccessObservationStatus,
    AuthorizationDecision,
    AuthorizationEnforcement,
    AuthorizationObservation,
    AuthorizationPolicyAssignment,
    AuthorizationPosture,
    AuthorizationRequirement,
    AuthorizationStatus,
    ResolvedAuthorizationConstraints,
)

ALGORITHM_VERSION = "execution-authorization-v1"


def resolve_execution_authorization(
    *,
    action_type_id: str,
    resource: ResourceContext,
    requirement: AuthorizationRequirement,
    assignments: tuple[AuthorizationPolicyAssignment, ...],
    observations: tuple[AuthorizationObservation, ...],
    identity_ref: str,
    policy_bundle_digest: str,
    inventory_generation: str,
    evaluated_at: datetime,
) -> AuthorizationDecision:
    """Resolve one requirement without provider I/O or implicit authority."""

    if evaluated_at.tzinfo is None:
        raise ValueError("authorization evaluation time MUST be timezone-aware")
    if any(
        not value.strip() for value in (identity_ref, policy_bundle_digest, inventory_generation)
    ):
        raise ValueError("authorization evaluation references MUST be non-empty")
    if not requirement.applies_to(
        action_type_id=action_type_id,
        resource_type=resource.resource_type,
    ):
        return _decision(
            status=AuthorizationStatus.UNKNOWN,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            reasons=("requirement_not_applicable",),
        )

    matching = matching_authorization_assignments(
        assignments=assignments,
        requirement=requirement,
        resource=resource,
    )
    if not matching:
        reasons = _unconfigured_reasons(
            assignments=assignments,
            requirement=requirement,
            resource=resource,
        )
        return _decision(
            status=AuthorizationStatus.UNCONFIGURED,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            reasons=reasons,
        )
    assignment_ids = tuple(item.assignment_id for item in matching)
    if len(set(assignment_ids)) != len(assignment_ids):
        return _decision(
            status=AuthorizationStatus.POLICY_CONFLICT,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            reasons=("duplicate_assignment_id",),
        )
    expected_policy_digest = authorization_policy_bundle_digest(matching)
    if policy_bundle_digest != expected_policy_digest:
        return _decision(
            status=AuthorizationStatus.POLICY_CONFLICT,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            reasons=("policy_bundle_digest_mismatch",),
        )

    constraints = _intersect_constraints(matching)
    if constraints is None:
        return _decision(
            status=AuthorizationStatus.POLICY_CONFLICT,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            reasons=("empty_grant_mode_intersection",),
        )
    if any(
        int(ScopeRef.parse(scope_ref).level) < int(constraints.max_scope)
        for scope_ref in requirement.scope_refs
    ):
        return _decision(
            status=AuthorizationStatus.POLICY_CONFLICT,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            reasons=("requirement_scope_exceeds_policy_maximum",),
            constraints=constraints,
        )
    if any(item.posture is AuthorizationPosture.PROHIBIT for item in matching):
        return _decision(
            status=AuthorizationStatus.PROHIBITED,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            reasons=("prohibit_assignment_matched",),
            constraints=constraints,
        )
    if any(item.posture is AuthorizationPosture.DELEGATE_MANUAL for item in matching):
        return _decision(
            status=AuthorizationStatus.DELEGATED,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            reasons=("manual_delegation_required",),
            constraints=constraints,
        )

    current, observation_conflict = _matching_observations(
        requirement=requirement,
        observations=observations,
        identity_ref=identity_ref,
        evaluated_at=evaluated_at,
    )
    observation_ids = tuple(item.observation_id for item in current)
    observation_evidence_digests = tuple(sorted({item.evidence_digest for item in current}))
    if observation_conflict:
        return _decision(
            status=AuthorizationStatus.UNKNOWN,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            observation_ids=observation_ids,
            observation_evidence_digests=observation_evidence_digests,
            reasons=("conflicting_effective_access_evidence",),
            constraints=constraints,
        )
    if any(item.status is AccessObservationStatus.UNKNOWN for item in current):
        return _decision(
            status=AuthorizationStatus.UNKNOWN,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            observation_ids=observation_ids,
            observation_evidence_digests=observation_evidence_digests,
            reasons=("effective_access_evidence_unknown",),
            constraints=constraints,
        )
    allowed_scopes = {
        item.scope_ref for item in current if item.status is AccessObservationStatus.ALLOWED
    }
    if set(requirement.scope_refs) <= allowed_scopes:
        return _decision(
            status=AuthorizationStatus.AUTHORIZED,
            action_type_id=action_type_id,
            requirement=requirement,
            identity_ref=identity_ref,
            policy_bundle_digest=policy_bundle_digest,
            inventory_generation=inventory_generation,
            assignment_ids=assignment_ids,
            observation_ids=observation_ids,
            observation_evidence_digests=observation_evidence_digests,
            reasons=("effective_access_verified",),
            constraints=constraints,
        )

    requestable = all(
        item.posture in {AuthorizationPosture.REQUEST_JIT, AuthorizationPosture.STANDING}
        for item in matching
    )
    status = AuthorizationStatus.GRANT_REQUIRED if requestable else AuthorizationStatus.UNKNOWN
    reason = "bounded_grant_required" if requestable else "effective_access_not_verified"
    return _decision(
        status=status,
        action_type_id=action_type_id,
        requirement=requirement,
        identity_ref=identity_ref,
        policy_bundle_digest=policy_bundle_digest,
        inventory_generation=inventory_generation,
        assignment_ids=assignment_ids,
        observation_ids=observation_ids,
        observation_evidence_digests=observation_evidence_digests,
        reasons=(reason,),
        constraints=constraints,
    )


def _intersect_constraints(
    assignments: tuple[AuthorizationPolicyAssignment, ...],
) -> ResolvedAuthorizationConstraints | None:
    grant_modes = set(assignments[0].constraints.allowed_grant_modes)
    for assignment in assignments[1:]:
        grant_modes.intersection_update(assignment.constraints.allowed_grant_modes)
    if not grant_modes:
        return None
    return ResolvedAuthorizationConstraints(
        allowed_grant_modes=frozenset(grant_modes),
        max_scope=max(item.constraints.max_scope for item in assignments),
        max_duration_seconds=min(item.constraints.max_duration_seconds for item in assignments),
        quorum=max(item.constraints.quorum for item in assignments),
        approver_roles=frozenset().union(
            *(item.constraints.approver_roles for item in assignments)
        ),
        required_evidence=frozenset().union(
            *(item.constraints.required_evidence for item in assignments)
        ),
        require_effective_probe=any(
            item.constraints.require_effective_probe for item in assignments
        ),
        exemptible=all(item.constraints.exemptible for item in assignments),
    )


def matching_authorization_assignments(
    *,
    assignments: tuple[AuthorizationPolicyAssignment, ...],
    requirement: AuthorizationRequirement,
    resource: ResourceContext,
) -> tuple[AuthorizationPolicyAssignment, ...]:
    """Return enforced matching assignments in canonical id order."""

    return tuple(
        sorted(
            (
                assignment
                for assignment in assignments
                if assignment.enforcement is AuthorizationEnforcement.ENFORCE
                and assignment.applies_to(
                    capability_id=requirement.capability_id,
                    execution_profile=requirement.execution_profile,
                    resource=resource,
                )
            ),
            key=lambda item: item.assignment_id,
        )
    )


def authorization_policy_bundle_digest(
    assignments: tuple[AuthorizationPolicyAssignment, ...],
) -> str:
    payload = [
        {
            "assignment_id": item.assignment_id,
            "version": item.version,
            "posture": item.posture.value,
            "enforcement": item.enforcement.value,
            "capabilities": sorted(item.capabilities),
            "execution_profiles": sorted(item.execution_profiles),
            "constraints": {
                "allowed_grant_modes": sorted(
                    mode.value for mode in item.constraints.allowed_grant_modes
                ),
                "max_scope": item.constraints.max_scope.name.lower(),
                "max_duration_seconds": item.constraints.max_duration_seconds,
                "quorum": item.constraints.quorum,
                "approver_roles": sorted(item.constraints.approver_roles),
                "required_evidence": sorted(item.constraints.required_evidence),
                "require_effective_probe": item.constraints.require_effective_probe,
                "exemptible": item.constraints.exemptible,
            },
        }
        for item in assignments
    ]
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _policy_bundle_digest(
    assignments: tuple[AuthorizationPolicyAssignment, ...],
) -> str:
    """Compatibility alias for existing callers; use the public helper."""

    return authorization_policy_bundle_digest(assignments)


def _unconfigured_reasons(
    *,
    assignments: tuple[AuthorizationPolicyAssignment, ...],
    requirement: AuthorizationRequirement,
    resource: ResourceContext,
) -> tuple[str, ...]:
    if not assignments:
        return ("no_assignments_in_catalog",)
    binding_matches = tuple(
        assignment
        for assignment in assignments
        if requirement.capability_id in assignment.capabilities
        and requirement.execution_profile in assignment.execution_profiles
    )
    if not binding_matches:
        return ("no_assignment_for_capability_profile",)
    scope_matches = tuple(
        assignment for assignment in binding_matches if assignment.scope.covers(resource)
    )
    if not scope_matches:
        return ("no_assignment_matches_scope",)
    return ("all_matching_assignments_shadow",)


def _matching_observations(
    *,
    requirement: AuthorizationRequirement,
    observations: tuple[AuthorizationObservation, ...],
    identity_ref: str,
    evaluated_at: datetime,
) -> tuple[tuple[AuthorizationObservation, ...], bool]:
    selected: dict[str, AuthorizationObservation] = {}
    conflict = False
    for item in observations:
        if not (
            item.identity_ref == identity_ref
            and item.capability_id == requirement.capability_id
            and item.mapping_digest == requirement.mapping_digest
            and item.scope_ref in requirement.scope_refs
            and item.observed_at <= evaluated_at < item.expires_at
        ):
            continue
        previous = selected.get(item.scope_ref)
        if previous is None:
            selected[item.scope_ref] = item
            continue
        if previous == item:
            continue
        if previous.status is not item.status:
            conflict = True
        if (item.observed_at, item.observation_id) > (
            previous.observed_at,
            previous.observation_id,
        ):
            selected[item.scope_ref] = item
    return tuple(sorted(selected.values(), key=lambda item: item.observation_id)), conflict


def _decision(
    *,
    status: AuthorizationStatus,
    action_type_id: str,
    requirement: AuthorizationRequirement,
    identity_ref: str,
    policy_bundle_digest: str,
    inventory_generation: str,
    reasons: tuple[str, ...],
    assignment_ids: tuple[str, ...] = (),
    observation_ids: tuple[str, ...] = (),
    observation_evidence_digests: tuple[str, ...] = (),
    constraints: ResolvedAuthorizationConstraints | None = None,
) -> AuthorizationDecision:
    digest_payload = {
        "status": status.value,
        "action_type_id": action_type_id,
        "capability_id": requirement.capability_id,
        "requirement_id": requirement.requirement_id,
        "mapping_digest": requirement.mapping_digest,
        "execution_profile": requirement.execution_profile,
        "identity_ref": identity_ref,
        "scope_refs": requirement.scope_refs,
        "assignment_ids": assignment_ids,
        "observation_ids": observation_ids,
        "observation_evidence_digests": observation_evidence_digests,
        "reasons": reasons,
        "policy_bundle_digest": policy_bundle_digest,
        "inventory_generation": inventory_generation,
        "algorithm_version": ALGORITHM_VERSION,
        "constraints": _constraints_payload(constraints),
    }
    canonical = json.dumps(
        digest_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return AuthorizationDecision(
        status=status,
        action_type_id=action_type_id,
        capability_id=requirement.capability_id,
        requirement_id=requirement.requirement_id,
        execution_profile=requirement.execution_profile,
        identity_ref=identity_ref,
        scope_refs=requirement.scope_refs,
        assignment_ids=assignment_ids,
        observation_ids=observation_ids,
        observation_evidence_digests=observation_evidence_digests,
        reasons=reasons,
        policy_bundle_digest=policy_bundle_digest,
        inventory_generation=inventory_generation,
        algorithm_version=ALGORITHM_VERSION,
        decision_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        constraints=constraints,
    )


def _constraints_payload(
    constraints: ResolvedAuthorizationConstraints | None,
) -> dict[str, object] | None:
    if constraints is None:
        return None
    return {
        "allowed_grant_modes": sorted(item.value for item in constraints.allowed_grant_modes),
        "max_scope": constraints.max_scope.name.lower(),
        "max_duration_seconds": constraints.max_duration_seconds,
        "quorum": constraints.quorum,
        "approver_roles": sorted(constraints.approver_roles),
        "required_evidence": sorted(constraints.required_evidence),
        "require_effective_probe": constraints.require_effective_probe,
        "exemptible": constraints.exemptible,
    }


__all__ = ["ALGORITHM_VERSION", "resolve_execution_authorization"]
