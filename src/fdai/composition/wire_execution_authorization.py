"""Composition binding for ontology-driven execution authorization."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fdai.core.execution_authorization import ResolverBackedExecutionAuthorizationEvaluator
from fdai.rule_catalog.schema.authorization_requirement import (
    load_authorization_requirement_catalog,
)
from fdai.rule_catalog.schema.execution_authorization import (
    load_authorization_assignment_catalog,
)
from fdai.shared.providers.execution_authorization import (
    EffectiveAuthorizationProbe,
    ExecutionAccessGrantPlanner,
    ExecutionAccessGrantSink,
    ExecutionAuthorizationContextProvider,
    ExecutionAuthorizationScopeResolver,
    ExecutionIdentityResolver,
    ProviderPermissionMapper,
)

from ._helpers import Container


def bind_execution_authorization(
    container: Container,
    *,
    requirements_root: Path,
    assignments_root: Path,
    known_action_type_ids: frozenset[str],
    known_resource_types: frozenset[str],
    known_capability_ids: frozenset[str],
    known_execution_profiles: frozenset[str],
    context_provider: ExecutionAuthorizationContextProvider,
    scope_resolver: ExecutionAuthorizationScopeResolver,
    identity_resolver: ExecutionIdentityResolver,
    permission_mapper: ProviderPermissionMapper,
    effective_probe: EffectiveAuthorizationProbe,
    grant_planner: ExecutionAccessGrantPlanner | None = None,
    grant_sink: ExecutionAccessGrantSink | None = None,
) -> Container:
    """Validate catalogs and return a container with authorization required."""

    if (grant_planner is None) != (grant_sink is None):
        raise ValueError("execution authorization grant planner and sink MUST be bound together")
    requirements = load_authorization_requirement_catalog(
        requirements_root,
        known_action_type_ids=known_action_type_ids,
        known_resource_types=known_resource_types,
        known_capability_ids=known_capability_ids,
        known_execution_profiles=known_execution_profiles,
    )
    if not requirements:
        raise ValueError("execution authorization requires at least one requirement")
    assignments = load_authorization_assignment_catalog(
        assignments_root,
        known_capability_ids=known_capability_ids,
        known_execution_profiles=known_execution_profiles,
    )
    evaluator = ResolverBackedExecutionAuthorizationEvaluator(
        requirements=requirements,
        assignments=assignments,
        context_provider=context_provider,
        scope_resolver=scope_resolver,
        identity_resolver=identity_resolver,
        permission_mapper=permission_mapper,
        effective_probe=effective_probe,
        grant_planner=grant_planner,
    )
    return replace(
        container,
        execution_authorization_evaluator=evaluator,
        execution_access_grant_sink=grant_sink,
        execution_authorization_required=True,
    )


__all__ = ["bind_execution_authorization"]
