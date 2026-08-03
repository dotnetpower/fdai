"""End-to-end assembly tests for the resolver-backed authorization evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.execution_authorization import (
    AuthorizationConstraints,
    AuthorizationEnforcement,
    AuthorizationPolicyAssignment,
    AuthorizationPosture,
    AuthorizationScopeLevel,
    GrantMode,
    HierarchicalAuthorizationScopeResolver,
    ResolverBackedExecutionAuthorizationEvaluator,
)
from fdai.rule_catalog.schema.authorization_requirement import AuthorizationRequirementSpec
from fdai.rule_catalog.schema.provenance import Provenance
from fdai.rule_catalog.schema.scope import ScopeBinding, ScopeRef
from fdai.shared.providers.execution_authorization import (
    EffectiveAccessStatus,
    EffectiveAuthorizationProbeRequest,
    EffectiveAuthorizationProbeResult,
    ExecutionAccessGrantPlanRequest,
    ExecutionAccessGrantProposal,
    ExecutionAuthorizationContext,
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationStatus,
    ExecutionIdentityBinding,
    ProviderPermissionMapping,
)

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


@dataclass
class _ContextProvider:
    calls: int = 0

    async def resolve_context(
        self, request: ExecutionAuthorizationRequest
    ) -> ExecutionAuthorizationContext:
        self.calls += 1
        return ExecutionAuthorizationContext(
            organization="example",
            account="account",
            resource_group="group",
            resource_id="resource",
            resource_type="object-storage",
            inventory_generation="inventory-v1",
            evaluated_at=_NOW,
            requester_ref="requester",
        )


@dataclass
class _IdentityResolver:
    calls: int = 0

    async def resolve(
        self, *, execution_profile: str, target_resource_ref: str
    ) -> ExecutionIdentityBinding:
        self.calls += 1
        assert target_resource_ref == "target-ref"
        return ExecutionIdentityBinding(
            execution_profile=execution_profile,
            identity_ref="executor-ref",
            binding_digest="identity-binding-v1",
        )


@dataclass
class _Mapper:
    calls: int = 0

    def resolve(self, capability_id: str) -> ProviderPermissionMapping:
        self.calls += 1
        return ProviderPermissionMapping(
            capability_id=capability_id,
            provider="example-provider",
            operations=("objects/write",),
            audience_ref="control-plane",
            authorization_plane="control-plane",
            mapping_digest="mapping-v1",
        )


@dataclass
class _Probe:
    status: EffectiveAccessStatus
    calls: int = 0

    async def probe(
        self, request: EffectiveAuthorizationProbeRequest
    ) -> EffectiveAuthorizationProbeResult:
        self.calls += 1
        assert request.identity_ref == "executor-ref"
        return EffectiveAuthorizationProbeResult(
            status=self.status,
            evidence_digest=f"probe-{self.status.value}",
            observed_at=_NOW,
            expires_at=_NOW + timedelta(minutes=5),
        )


@dataclass
class _GrantPlanner:
    calls: int = 0

    async def plan_grant(
        self, request: ExecutionAccessGrantPlanRequest
    ) -> ExecutionAccessGrantProposal:
        self.calls += 1
        return ExecutionAccessGrantProposal(
            idempotency_key=request.original_request.idempotency_key,
            original_action_id=request.original_request.action_id,
            authorization_decision_digest=request.authorization_decision_digest,
            requirement_id=request.requirement_id,
            capability_id=request.capability_id,
            execution_profile=request.execution_profile,
            executor_identity_ref=request.executor_identity_ref,
            scope_ref=request.scope_ref,
            grant_mode="action_bound",
            mapping_digest=request.mapping_digest,
            plan_digest="grant-plan-v1",
            requester_ref=request.requester_ref,
            requested_at=request.requested_at,
            expires_at=request.requested_at + timedelta(minutes=5),
            quorum=request.quorum,
            approver_roles=request.approver_roles,
        )


def _requirement(
    *, scope_expressions: tuple[str, ...] = ("target",)
) -> AuthorizationRequirementSpec:
    return AuthorizationRequirementSpec(
        requirement_id="object.write.target",
        version="1.0.0",
        capability_id="object.write",
        action_type_ids=frozenset({"object.update"}),
        resource_types=frozenset({"object-storage"}),
        scope_expressions=scope_expressions,
        execution_profile="change-executor",
        provenance=Provenance(created_at=_NOW, created_by="example-team"),
    )


def _assignment(
    posture: AuthorizationPosture = AuthorizationPosture.REQUEST_JIT,
) -> AuthorizationPolicyAssignment:
    return AuthorizationPolicyAssignment(
        assignment_id="authz.object-write",
        capabilities=frozenset({"object.write"}),
        execution_profiles=frozenset({"change-executor"}),
        scope=ScopeBinding(includes=(ScopeRef.parse("scope://example/account"),)),
        posture=posture,
        constraints=AuthorizationConstraints(
            allowed_grant_modes=frozenset({GrantMode.ACTION_BOUND}),
            max_scope=AuthorizationScopeLevel.RESOURCE,
            max_duration_seconds=900,
            quorum=2,
            approver_roles=frozenset({"owner"}),
            required_evidence=frozenset({"effective_access"}),
        ),
        enforcement=AuthorizationEnforcement.ENFORCE,
    )


def _request() -> ExecutionAuthorizationRequest:
    return ExecutionAuthorizationRequest(
        action_id="action-1",
        action_type_id="object.update",
        target_resource_ref="target-ref",
        correlation_id="correlation-1",
        idempotency_key="idempotency-1",
    )


def _evaluator(
    *,
    probe: _Probe,
    posture: AuthorizationPosture = AuthorizationPosture.REQUEST_JIT,
    requirement: AuthorizationRequirementSpec | None = None,
    grant_planner: _GrantPlanner | None = None,
) -> tuple[
    ResolverBackedExecutionAuthorizationEvaluator,
    _ContextProvider,
    _IdentityResolver,
    _Mapper,
]:
    context_provider = _ContextProvider()
    identity_resolver = _IdentityResolver()
    mapper = _Mapper()
    evaluator = ResolverBackedExecutionAuthorizationEvaluator(
        requirements=(requirement or _requirement(),),
        assignments=(_assignment(posture),),
        context_provider=context_provider,
        scope_resolver=HierarchicalAuthorizationScopeResolver(),
        identity_resolver=identity_resolver,
        permission_mapper=mapper,
        effective_probe=probe,
        grant_planner=grant_planner,
    )
    return evaluator, context_provider, identity_resolver, mapper


async def test_allowed_probe_reaches_authorized_result() -> None:
    probe = _Probe(EffectiveAccessStatus.ALLOWED)
    evaluator, context_provider, identity_resolver, mapper = _evaluator(probe=probe)

    result = await evaluator.evaluate(_request())

    assert result.status is ExecutionAuthorizationStatus.AUTHORIZED
    assert result.can_enter_risk_gate
    assert result.executor_identity_ref == "executor-ref"
    assert result.grant_proposals == ()
    assert (context_provider.calls, identity_resolver.calls, mapper.calls, probe.calls) == (
        1,
        1,
        1,
        1,
    )


async def test_denied_probe_plans_one_exact_bounded_grant() -> None:
    probe = _Probe(EffectiveAccessStatus.DENIED)
    planner = _GrantPlanner()
    evaluator, _, _, _ = _evaluator(probe=probe, grant_planner=planner)

    result = await evaluator.evaluate(_request())

    assert result.status is ExecutionAuthorizationStatus.GRANT_REQUIRED
    assert len(result.grant_proposals) == 1
    assert result.grant_proposals[0].scope_ref == "scope://example/account/group/resource"
    assert result.grant_proposals[0].authorization_decision_digest == result.decision_digest
    assert planner.calls == 1


async def test_multiple_missing_requirements_plan_every_grant() -> None:
    probe = _Probe(EffectiveAccessStatus.DENIED)
    planner = _GrantPlanner()
    second = AuthorizationRequirementSpec(
        requirement_id="object.write.secondary",
        version="1.0.0",
        capability_id="object.write",
        action_type_ids=frozenset({"object.update"}),
        resource_types=frozenset({"object-storage"}),
        scope_expressions=("target",),
        execution_profile="change-executor",
        provenance=Provenance(created_at=_NOW, created_by="example-team"),
    )
    evaluator, _, _, _ = _evaluator(probe=probe, grant_planner=planner)
    evaluator = ResolverBackedExecutionAuthorizationEvaluator(
        requirements=(*evaluator.requirements, second),
        assignments=evaluator.assignments,
        context_provider=evaluator.context_provider,
        scope_resolver=evaluator.scope_resolver,
        identity_resolver=evaluator.identity_resolver,
        permission_mapper=evaluator.permission_mapper,
        effective_probe=evaluator.effective_probe,
        grant_planner=planner,
    )

    result = await evaluator.evaluate(_request())

    assert result.status is ExecutionAuthorizationStatus.GRANT_REQUIRED
    assert tuple(
        (proposal.requirement_id, proposal.scope_ref) for proposal in result.grant_proposals
    ) == (
        ("object.write.secondary", "scope://example/account/group/resource"),
        ("object.write.target", "scope://example/account/group/resource"),
    )
    assert planner.calls == 2


async def test_prohibit_assignment_skips_effective_access_probe() -> None:
    probe = _Probe(EffectiveAccessStatus.ALLOWED)
    evaluator, _, _, _ = _evaluator(
        probe=probe,
        posture=AuthorizationPosture.PROHIBIT,
    )

    result = await evaluator.evaluate(_request())

    assert result.status is ExecutionAuthorizationStatus.PROHIBITED
    assert probe.calls == 0


async def test_graph_scope_resolution_failure_is_unknown_without_provider_guessing() -> None:
    probe = _Probe(EffectiveAccessStatus.ALLOWED)
    evaluator, _, identity_resolver, mapper = _evaluator(
        probe=probe,
        requirement=_requirement(scope_expressions=("related(depends_on,2)",)),
    )

    result = await evaluator.evaluate(_request())

    assert result.status is ExecutionAuthorizationStatus.UNKNOWN
    assert result.reason_codes == ("object.write.target:scope_expression_requires_graph",)
    assert (identity_resolver.calls, mapper.calls, probe.calls) == (0, 0, 0)


async def test_no_applicable_requirement_is_unconfigured() -> None:
    probe = _Probe(EffectiveAccessStatus.ALLOWED)
    evaluator, _, identity_resolver, mapper = _evaluator(probe=probe)
    request = ExecutionAuthorizationRequest(
        action_id="action-1",
        action_type_id="object.delete",
        target_resource_ref="target-ref",
        correlation_id="correlation-1",
        idempotency_key="idempotency-1",
    )

    result = await evaluator.evaluate(request)

    assert result.status is ExecutionAuthorizationStatus.UNCONFIGURED
    assert result.reason_codes == ("no_applicable_authorization_requirement",)
    assert (identity_resolver.calls, mapper.calls, probe.calls) == (0, 0, 0)
