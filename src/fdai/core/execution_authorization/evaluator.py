"""Provider-neutral runtime assembly for execution-authorization decisions."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.rule_catalog.schema.authorization_requirement import AuthorizationRequirementSpec
from fdai.rule_catalog.schema.execution_authorization import AuthorizationPolicyAssignment
from fdai.rule_catalog.schema.scope import ResourceContext
from fdai.shared.providers.execution_authorization import (
    AuthorizationScopeResolutionStatus,
    EffectiveAuthorizationProbe,
    ExecutionAccessGrantPlanner,
    ExecutionAccessGrantPlanRequest,
    ExecutionAccessGrantProposal,
    ExecutionAuthorizationContext,
    ExecutionAuthorizationContextProvider,
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationResult,
    ExecutionAuthorizationScopeResolver,
    ExecutionAuthorizationStatus,
    ExecutionIdentityResolver,
    ProviderPermissionMapper,
)

from .decision_set import (
    RequirementOutcome,
    build_result,
    combined_digest,
    combined_status,
)
from .grant_planning import validate_grant_proposal
from .models import AccessObservationStatus, AuthorizationRequirement
from .observation import probe_authorization_observation
from .resolver import (
    authorization_policy_bundle_digest,
    matching_authorization_assignments,
    resolve_execution_authorization,
)

_POLICY_TERMINAL_STATUSES = frozenset(
    {
        ExecutionAuthorizationStatus.DELEGATED,
        ExecutionAuthorizationStatus.PROHIBITED,
        ExecutionAuthorizationStatus.POLICY_CONFLICT,
        ExecutionAuthorizationStatus.UNCONFIGURED,
    }
)


@dataclass(frozen=True, slots=True)
class ResolverBackedExecutionAuthorizationEvaluator:
    requirements: tuple[AuthorizationRequirementSpec, ...]
    assignments: tuple[AuthorizationPolicyAssignment, ...]
    context_provider: ExecutionAuthorizationContextProvider
    scope_resolver: ExecutionAuthorizationScopeResolver
    identity_resolver: ExecutionIdentityResolver
    permission_mapper: ProviderPermissionMapper
    effective_probe: EffectiveAuthorizationProbe
    grant_planner: ExecutionAccessGrantPlanner | None = None
    evaluator_ref: str = "resolver-backed-execution-authorization-v1"

    async def evaluate(
        self,
        request: ExecutionAuthorizationRequest,
    ) -> ExecutionAuthorizationResult:
        context = await self.context_provider.resolve_context(request)
        resource = ResourceContext(
            organization=context.organization,
            account=context.account,
            resource_group=context.resource_group,
            resource_id=context.resource_id,
            resource_type=context.resource_type,
            tags=context.tags,
        )
        applicable = tuple(
            sorted(
                (
                    requirement
                    for requirement in self.requirements
                    if requirement.applies_to(
                        action_type_id=request.action_type_id,
                        resource_type=context.resource_type,
                    )
                ),
                key=lambda item: item.requirement_id,
            )
        )
        if not applicable:
            return self._result(
                request=request,
                context=context,
                status=ExecutionAuthorizationStatus.UNCONFIGURED,
                outcomes=(),
                extra_reasons=("no_applicable_authorization_requirement",),
            )

        outcomes = tuple(
            [
                await self._evaluate_requirement(
                    request=request,
                    context=context,
                    resource=resource,
                    spec=spec,
                )
                for spec in applicable
            ]
        )
        status = combined_status(outcomes)
        extra_reasons: tuple[str, ...] = ()
        grant_proposals: tuple[ExecutionAccessGrantProposal, ...] = ()
        if status is ExecutionAuthorizationStatus.GRANT_REQUIRED:
            if self.grant_planner is None:
                status = ExecutionAuthorizationStatus.UNKNOWN
                extra_reasons = ("grant_planner_unavailable",)
            else:
                provisional_digest = combined_digest(
                    request=request,
                    context=context,
                    status=status,
                    outcomes=outcomes,
                    extra_reasons=(),
                )
                grant_proposals = await self._plan_missing_grants(
                    request=request,
                    context=context,
                    decision_digest=provisional_digest,
                    outcomes=outcomes,
                )
        return self._result(
            request=request,
            context=context,
            status=status,
            outcomes=outcomes,
            extra_reasons=extra_reasons,
            grant_proposals=grant_proposals,
        )

    async def _evaluate_requirement(
        self,
        *,
        request: ExecutionAuthorizationRequest,
        context: ExecutionAuthorizationContext,
        resource: ResourceContext,
        spec: AuthorizationRequirementSpec,
    ) -> RequirementOutcome:
        scope_resolution = await self.scope_resolver.resolve_scopes(
            request=request,
            context=context,
            scope_expressions=spec.scope_expressions,
        )
        if scope_resolution.status is AuthorizationScopeResolutionStatus.UNKNOWN:
            return RequirementOutcome(
                requirement_id=spec.requirement_id,
                status=ExecutionAuthorizationStatus.UNKNOWN,
                reasons=(scope_resolution.reason_code,),
                scope_evidence_digest=scope_resolution.evidence_digest,
            )

        mapping = self.permission_mapper.resolve(spec.capability_id)
        if mapping.capability_id != spec.capability_id:
            return RequirementOutcome(
                requirement_id=spec.requirement_id,
                status=ExecutionAuthorizationStatus.UNKNOWN,
                reasons=("provider_mapping_capability_mismatch",),
                scope_evidence_digest=scope_resolution.evidence_digest,
            )
        identity = await self.identity_resolver.resolve(
            execution_profile=spec.execution_profile,
            target_resource_ref=request.target_resource_ref,
        )
        if identity.execution_profile != spec.execution_profile:
            return RequirementOutcome(
                requirement_id=spec.requirement_id,
                status=ExecutionAuthorizationStatus.UNKNOWN,
                reasons=("execution_identity_profile_mismatch",),
                scope_evidence_digest=scope_resolution.evidence_digest,
                mapping=mapping,
            )
        requirement = AuthorizationRequirement(
            requirement_id=spec.requirement_id,
            capability_id=spec.capability_id,
            action_type_ids=spec.action_type_ids,
            resource_types=spec.resource_types,
            scope_refs=scope_resolution.scope_refs,
            execution_profile=spec.execution_profile,
            mapping_digest=mapping.mapping_digest,
        )
        matching = matching_authorization_assignments(
            assignments=self.assignments,
            requirement=requirement,
            resource=resource,
        )
        policy_digest = authorization_policy_bundle_digest(matching)
        policy_decision = resolve_execution_authorization(
            action_type_id=request.action_type_id,
            resource=resource,
            requirement=requirement,
            assignments=self.assignments,
            observations=(),
            identity_ref=identity.identity_ref,
            policy_bundle_digest=policy_digest,
            inventory_generation=context.inventory_generation,
            evaluated_at=context.evaluated_at,
        )
        if policy_decision.status in _POLICY_TERMINAL_STATUSES:
            return RequirementOutcome(
                requirement_id=spec.requirement_id,
                status=policy_decision.status,
                reasons=policy_decision.reasons,
                scope_evidence_digest=scope_resolution.evidence_digest,
                decision=policy_decision,
                identity_binding=identity,
                mapping=mapping,
            )

        observations = tuple(
            [
                await probe_authorization_observation(
                    probe=self.effective_probe,
                    identity=identity,
                    mapping=mapping,
                    capability_id=spec.capability_id,
                    scope_ref=scope_ref,
                )
                for scope_ref in requirement.scope_refs
            ]
        )
        evaluated_at = max(
            context.evaluated_at,
            *(observation.observed_at for observation in observations),
        )
        decision = resolve_execution_authorization(
            action_type_id=request.action_type_id,
            resource=resource,
            requirement=requirement,
            assignments=self.assignments,
            observations=observations,
            identity_ref=identity.identity_ref,
            policy_bundle_digest=policy_digest,
            inventory_generation=context.inventory_generation,
            evaluated_at=evaluated_at,
        )
        return RequirementOutcome(
            requirement_id=spec.requirement_id,
            status=decision.status,
            reasons=decision.reasons,
            scope_evidence_digest=scope_resolution.evidence_digest,
            decision=decision,
            observations=observations,
            identity_binding=identity,
            mapping=mapping,
        )

    async def _plan_missing_grants(
        self,
        *,
        request: ExecutionAuthorizationRequest,
        context: ExecutionAuthorizationContext,
        decision_digest: str,
        outcomes: tuple[RequirementOutcome, ...],
    ) -> tuple[ExecutionAccessGrantProposal, ...]:
        planner = self.grant_planner
        if planner is None:  # pragma: no cover - caller guards this invariant
            raise ValueError("grant planner unavailable")
        proposals: list[ExecutionAccessGrantProposal] = []
        for outcome in outcomes:
            if outcome.status is not ExecutionAuthorizationStatus.GRANT_REQUIRED:
                continue
            decision = outcome.decision
            mapping = outcome.mapping
            if decision is None or decision.constraints is None or mapping is None:
                raise ValueError("grant-required decision is missing planning evidence")
            allowed_scopes = {
                observation.scope_ref
                for observation in outcome.observations
                if observation.status is AccessObservationStatus.ALLOWED
            }
            constraints = decision.constraints
            for scope_ref in sorted(set(decision.scope_refs) - allowed_scopes):
                plan_request = ExecutionAccessGrantPlanRequest(
                    authorization_decision_digest=decision_digest,
                    original_request=request,
                    requirement_id=decision.requirement_id,
                    capability_id=decision.capability_id,
                    execution_profile=decision.execution_profile,
                    executor_identity_ref=decision.identity_ref,
                    scope_ref=scope_ref,
                    mapping_digest=mapping.mapping_digest,
                    allowed_grant_modes=frozenset(
                        mode.value for mode in constraints.allowed_grant_modes
                    ),
                    max_duration_seconds=constraints.max_duration_seconds,
                    quorum=constraints.quorum,
                    approver_roles=constraints.approver_roles,
                    requester_ref=context.requester_ref,
                    requested_at=context.evaluated_at,
                )
                proposal = await planner.plan_grant(plan_request)
                validate_grant_proposal(plan_request, proposal)
                proposals.append(proposal)
        return tuple(proposals)

    def _result(
        self,
        *,
        request: ExecutionAuthorizationRequest,
        context: ExecutionAuthorizationContext,
        status: ExecutionAuthorizationStatus,
        outcomes: tuple[RequirementOutcome, ...],
        extra_reasons: tuple[str, ...],
        grant_proposals: tuple[ExecutionAccessGrantProposal, ...] = (),
    ) -> ExecutionAuthorizationResult:
        return build_result(
            request=request,
            context=context,
            status=status,
            outcomes=outcomes,
            extra_reasons=extra_reasons,
            evaluator_ref=self.evaluator_ref,
            grant_proposals=grant_proposals,
        )


__all__ = [
    "ResolverBackedExecutionAuthorizationEvaluator",
]
