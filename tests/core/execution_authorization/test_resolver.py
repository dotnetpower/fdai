"""Execution-authorization policy composition and customer-variance tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.execution_authorization import (
    AccessObservationStatus,
    AuthorizationConstraints,
    AuthorizationEnforcement,
    AuthorizationObservation,
    AuthorizationPolicyAssignment,
    AuthorizationPosture,
    AuthorizationRequirement,
    AuthorizationScopeLevel,
    AuthorizationStatus,
    GrantMode,
    resolve_execution_authorization,
)
from fdai.core.execution_authorization.resolver import _policy_bundle_digest
from fdai.rule_catalog.schema.scope import ResourceContext, Scope, ScopeLevel

NOW = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)


def _resource() -> ResourceContext:
    return ResourceContext(
        organization="example",
        account="account",
        resource_group="prod",
        resource_id="store-1",
        resource_type="object-storage",
        tags={"environment": "prod"},
    )


def _requirement() -> AuthorizationRequirement:
    return AuthorizationRequirement(
        requirement_id="requirement.object-write",
        capability_id="object.write",
        action_type_ids=frozenset({"ops.write-object"}),
        resource_types=frozenset({"object-storage"}),
        scope_refs=("scope://example/account/prod/store-1",),
        execution_profile="change-executor",
        mapping_digest="mapping-v1",
    )


def _constraints(
    *modes: GrantMode,
    max_scope: AuthorizationScopeLevel = AuthorizationScopeLevel.RESOURCE,
    duration: int = 1800,
    quorum: int = 1,
    roles: frozenset[str] = frozenset({"owner"}),
    evidence: frozenset[str] = frozenset({"effective_access"}),
    exemptible: bool = False,
) -> AuthorizationConstraints:
    return AuthorizationConstraints(
        allowed_grant_modes=frozenset(modes or (GrantMode.ACTION_BOUND,)),
        max_scope=max_scope,
        max_duration_seconds=duration,
        quorum=quorum,
        approver_roles=roles,
        required_evidence=evidence,
        exemptible=exemptible,
    )


def _assignment(
    posture: AuthorizationPosture,
    *,
    assignment_id: str = "assignment.default",
    constraints: AuthorizationConstraints | None = None,
    enforcement: AuthorizationEnforcement = AuthorizationEnforcement.ENFORCE,
) -> AuthorizationPolicyAssignment:
    return AuthorizationPolicyAssignment(
        assignment_id=assignment_id,
        capabilities=frozenset({"object.write"}),
        execution_profiles=frozenset({"change-executor"}),
        scope=Scope(level=ScopeLevel.RESOURCE_GROUP, id="prod"),
        posture=posture,
        constraints=constraints or _constraints(),
        enforcement=enforcement,
    )


def _observation(
    status: AccessObservationStatus = AccessObservationStatus.ALLOWED,
    *,
    observed_at: datetime | None = None,
    expires_at: datetime | None = None,
    identity_ref: str = "identity/change",
    mapping_digest: str = "mapping-v1",
) -> AuthorizationObservation:
    return AuthorizationObservation(
        observation_id="observation-1",
        identity_ref=identity_ref,
        capability_id="object.write",
        scope_ref="scope://example/account/prod/store-1",
        mapping_digest=mapping_digest,
        status=status,
        observed_at=observed_at or NOW - timedelta(minutes=1),
        expires_at=expires_at or NOW + timedelta(minutes=5),
        evidence_digest="evidence-v1",
    )


def _resolve(
    assignments: tuple[AuthorizationPolicyAssignment, ...],
    observations: tuple[AuthorizationObservation, ...] = (),
):
    matching = tuple(
        item
        for item in assignments
        if item.enforcement is AuthorizationEnforcement.ENFORCE
        and item.applies_to(
            capability_id="object.write",
            execution_profile="change-executor",
            resource=_resource(),
        )
    )
    return resolve_execution_authorization(
        action_type_id="ops.write-object",
        resource=_resource(),
        requirement=_requirement(),
        assignments=assignments,
        observations=observations,
        identity_ref="identity/change",
        policy_bundle_digest=(
            _policy_bundle_digest(tuple(sorted(matching, key=lambda item: item.assignment_id)))
            if matching
            else "bundle-empty"
        ),
        inventory_generation="inventory-v1",
        evaluated_at=NOW,
    )


def test_same_action_is_authorized_for_preprovisioned_customer() -> None:
    decision = _resolve(
        (_assignment(AuthorizationPosture.PREPROVISIONED_ONLY),),
        (_observation(),),
    )
    assert decision.status is AuthorizationStatus.AUTHORIZED
    assert decision.can_enter_risk_gate


def test_same_action_requests_jit_for_customer_without_access() -> None:
    decision = _resolve((_assignment(AuthorizationPosture.REQUEST_JIT),))
    assert decision.status is AuthorizationStatus.GRANT_REQUIRED
    assert not decision.can_enter_risk_gate


def test_same_action_is_prohibited_by_customer_policy() -> None:
    decision = _resolve((_assignment(AuthorizationPosture.PROHIBIT),), (_observation(),))
    assert decision.status is AuthorizationStatus.PROHIBITED


def test_prohibit_dominates_a_more_specific_allowing_assignment() -> None:
    allowing = replace(
        _assignment(AuthorizationPosture.STANDING, assignment_id="allow.resource"),
        scope=Scope(level=ScopeLevel.RESOURCE, id="store-1"),
    )
    decision = _resolve(
        (
            _assignment(AuthorizationPosture.PROHIBIT, assignment_id="deny.group"),
            allowing,
        ),
        (_observation(),),
    )
    assert decision.status is AuthorizationStatus.PROHIBITED


def test_constraints_intersect_to_narrowest_values() -> None:
    broad = _assignment(
        AuthorizationPosture.REQUEST_JIT,
        assignment_id="broad",
        constraints=_constraints(
            GrantMode.ACTION_BOUND,
            GrantMode.TIME_BOUND,
            max_scope=AuthorizationScopeLevel.RESOURCE_GROUP,
            duration=3600,
            quorum=1,
            roles=frozenset({"approver"}),
            evidence=frozenset({"policy"}),
            exemptible=True,
        ),
    )
    narrow = _assignment(
        AuthorizationPosture.REQUEST_JIT,
        assignment_id="narrow",
        constraints=_constraints(
            GrantMode.TIME_BOUND,
            max_scope=AuthorizationScopeLevel.RESOURCE,
            duration=900,
            quorum=2,
            roles=frozenset({"owner"}),
            evidence=frozenset({"effective_access"}),
        ),
    )
    decision = _resolve((broad, narrow))
    assert decision.status is AuthorizationStatus.GRANT_REQUIRED
    assert decision.constraints is not None
    assert decision.constraints.allowed_grant_modes == frozenset({GrantMode.TIME_BOUND})
    assert decision.constraints.max_scope is AuthorizationScopeLevel.RESOURCE
    assert decision.constraints.max_duration_seconds == 900
    assert decision.constraints.quorum == 2
    assert decision.constraints.approver_roles == frozenset({"approver", "owner"})
    assert decision.constraints.required_evidence == frozenset({"policy", "effective_access"})
    assert decision.constraints.exemptible is False


def test_empty_grant_mode_intersection_is_policy_conflict() -> None:
    first = _assignment(
        AuthorizationPosture.REQUEST_JIT,
        assignment_id="first",
        constraints=_constraints(GrantMode.ACTION_BOUND),
    )
    second = _assignment(
        AuthorizationPosture.REQUEST_JIT,
        assignment_id="second",
        constraints=_constraints(GrantMode.TIME_BOUND),
    )
    assert _resolve((first, second)).status is AuthorizationStatus.POLICY_CONFLICT


def test_duplicate_matching_assignment_id_is_policy_conflict() -> None:
    assignment = _assignment(AuthorizationPosture.REQUEST_JIT)
    decision = _resolve((assignment, assignment))
    assert decision.status is AuthorizationStatus.POLICY_CONFLICT
    assert decision.reasons == ("duplicate_assignment_id",)


def test_do_not_enforce_assignment_does_not_authorize() -> None:
    shadow = _assignment(
        AuthorizationPosture.STANDING,
        enforcement=AuthorizationEnforcement.DO_NOT_ENFORCE,
    )
    assert _resolve((shadow,), (_observation(),)).status is AuthorizationStatus.UNCONFIGURED


def test_shadow_constraints_do_not_participate_in_enforced_intersection() -> None:
    enforced = _assignment(
        AuthorizationPosture.REQUEST_JIT,
        assignment_id="enforced",
        constraints=_constraints(
            GrantMode.ACTION_BOUND,
            max_scope=AuthorizationScopeLevel.RESOURCE,
            duration=900,
        ),
    )
    shadow = _assignment(
        AuthorizationPosture.PROHIBIT,
        assignment_id="shadow",
        constraints=_constraints(
            GrantMode.TIME_BOUND,
            max_scope=AuthorizationScopeLevel.ORGANIZATION,
            duration=1,
        ),
        enforcement=AuthorizationEnforcement.DO_NOT_ENFORCE,
    )

    decision = _resolve((enforced, shadow))

    assert decision.status is AuthorizationStatus.GRANT_REQUIRED
    assert decision.assignment_ids == ("enforced",)
    assert decision.constraints is not None
    assert decision.constraints.allowed_grant_modes == frozenset({GrantMode.ACTION_BOUND})
    assert decision.constraints.max_duration_seconds == 900


def test_no_assignment_fails_closed_as_unconfigured() -> None:
    decision = _resolve(())
    assert decision.status is AuthorizationStatus.UNCONFIGURED
    assert decision.reasons == ("no_assignments_in_catalog",)


def test_unconfigured_reasons_distinguish_binding_scope_and_shadow() -> None:
    wrong_capability = replace(
        _assignment(AuthorizationPosture.REQUEST_JIT),
        capabilities=frozenset({"object.read"}),
    )
    wrong_scope = replace(
        _assignment(AuthorizationPosture.REQUEST_JIT),
        scope=Scope(level=ScopeLevel.RESOURCE_GROUP, id="other"),
    )
    shadow = _assignment(
        AuthorizationPosture.REQUEST_JIT,
        enforcement=AuthorizationEnforcement.DO_NOT_ENFORCE,
    )

    assert _resolve((wrong_capability,)).reasons == ("no_assignment_for_capability_profile",)
    assert _resolve((wrong_scope,)).reasons == ("no_assignment_matches_scope",)
    assert _resolve((shadow,)).reasons == ("all_matching_assignments_shadow",)


def test_expired_observation_does_not_authorize() -> None:
    expired = _observation(
        observed_at=NOW - timedelta(minutes=10),
        expires_at=NOW - timedelta(minutes=1),
    )
    decision = _resolve(
        (_assignment(AuthorizationPosture.PREPROVISIONED_ONLY),),
        (expired,),
    )
    assert decision.status is AuthorizationStatus.UNKNOWN


def test_wrong_identity_or_mapping_does_not_authorize() -> None:
    wrong_identity = _observation(identity_ref="identity/other")
    wrong_mapping = _observation(mapping_digest="mapping-v2")
    decision = _resolve(
        (_assignment(AuthorizationPosture.PREPROVISIONED_ONLY),),
        (wrong_identity, wrong_mapping),
    )
    assert decision.status is AuthorizationStatus.UNKNOWN


def test_conflicting_effective_access_evidence_never_authorizes() -> None:
    allowed = _observation()
    denied = replace(
        allowed,
        observation_id="observation-denied",
        status=AccessObservationStatus.DENIED,
    )
    decision = _resolve(
        (_assignment(AuthorizationPosture.PREPROVISIONED_ONLY),),
        (allowed, denied),
    )
    assert decision.status is AuthorizationStatus.UNKNOWN
    assert decision.reasons == ("conflicting_effective_access_evidence",)


def test_unknown_evidence_does_not_open_a_grant_request() -> None:
    decision = _resolve(
        (_assignment(AuthorizationPosture.REQUEST_JIT),),
        (_observation(AccessObservationStatus.UNKNOWN),),
    )
    assert decision.status is AuthorizationStatus.UNKNOWN


def test_duplicate_identical_observation_is_deduplicated() -> None:
    observation = _observation()
    decision = _resolve(
        (_assignment(AuthorizationPosture.PREPROVISIONED_ONLY),),
        (observation, observation),
    )
    assert decision.status is AuthorizationStatus.AUTHORIZED
    assert decision.observation_ids == ("observation-1",)


def test_requirement_scope_cannot_exceed_policy_maximum() -> None:
    assignment = _assignment(AuthorizationPosture.REQUEST_JIT)
    decision = resolve_execution_authorization(
        action_type_id="ops.write-object",
        resource=_resource(),
        requirement=replace(
            _requirement(),
            scope_refs=("scope://example/account/prod",),
        ),
        assignments=(assignment,),
        observations=(),
        identity_ref="identity/change",
        policy_bundle_digest=_policy_bundle_digest((assignment,)),
        inventory_generation="inventory-v1",
        evaluated_at=NOW,
    )
    assert decision.status is AuthorizationStatus.POLICY_CONFLICT


def test_any_broad_scope_in_multi_scope_requirement_causes_conflict() -> None:
    assignment = _assignment(AuthorizationPosture.REQUEST_JIT)
    decision = resolve_execution_authorization(
        action_type_id="ops.write-object",
        resource=_resource(),
        requirement=replace(
            _requirement(),
            scope_refs=(
                "scope://example/account",
                "scope://example/account/prod/store-1",
            ),
        ),
        assignments=(assignment,),
        observations=(),
        identity_ref="identity/change",
        policy_bundle_digest=_policy_bundle_digest((assignment,)),
        inventory_generation="inventory-v1",
        evaluated_at=NOW,
    )
    assert decision.status is AuthorizationStatus.POLICY_CONFLICT
    assert decision.reasons == ("requirement_scope_exceeds_policy_maximum",)


def test_mapping_digest_changes_replay_digest() -> None:
    first = _resolve((_assignment(AuthorizationPosture.REQUEST_JIT),))
    assignment = _assignment(AuthorizationPosture.REQUEST_JIT)
    second = resolve_execution_authorization(
        action_type_id="ops.write-object",
        resource=_resource(),
        requirement=replace(_requirement(), mapping_digest="mapping-v2"),
        assignments=(assignment,),
        observations=(),
        identity_ref="identity/change",
        policy_bundle_digest=_policy_bundle_digest((assignment,)),
        inventory_generation="inventory-v1",
        evaluated_at=NOW,
    )
    assert first.decision_digest != second.decision_digest


def test_policy_bundle_digest_must_match_assignments() -> None:
    assignment = _assignment(AuthorizationPosture.REQUEST_JIT)
    decision = resolve_execution_authorization(
        action_type_id="ops.write-object",
        resource=_resource(),
        requirement=_requirement(),
        assignments=(assignment,),
        observations=(),
        identity_ref="identity/change",
        policy_bundle_digest="caller-supplied-wrong-digest",
        inventory_generation="inventory-v1",
        evaluated_at=NOW,
    )
    assert decision.status is AuthorizationStatus.POLICY_CONFLICT
    assert decision.reasons == ("policy_bundle_digest_mismatch",)


def test_policy_bundle_digest_changes_with_assignment_constraints() -> None:
    first = _assignment(AuthorizationPosture.REQUEST_JIT)
    second = replace(first, constraints=_constraints(duration=600))

    assert _policy_bundle_digest((first,)) != _policy_bundle_digest((second,))


def test_manual_delegation_never_enters_risk_gate() -> None:
    decision = _resolve((_assignment(AuthorizationPosture.DELEGATE_MANUAL),))
    assert decision.status is AuthorizationStatus.DELEGATED
    assert not decision.can_enter_risk_gate


def test_decision_digest_is_replay_stable() -> None:
    first = _resolve((_assignment(AuthorizationPosture.REQUEST_JIT),))
    second = _resolve((_assignment(AuthorizationPosture.REQUEST_JIT),))
    assert first.decision_digest == second.decision_digest
    assert first.as_audit_dict() == second.as_audit_dict()


def test_observation_evidence_digest_is_pinned_into_decision() -> None:
    first = _resolve(
        (_assignment(AuthorizationPosture.PREPROVISIONED_ONLY),),
        (_observation(),),
    )
    second = _resolve(
        (_assignment(AuthorizationPosture.PREPROVISIONED_ONLY),),
        (replace(_observation(), evidence_digest="evidence-v2"),),
    )
    assert first.observation_evidence_digests == ("evidence-v1",)
    assert first.decision_digest != second.decision_digest
