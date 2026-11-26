"""Provider-neutral hierarchical authorization scope resolution."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.rule_catalog.schema.scope import ScopeRef
from fdai.shared.providers.execution_authorization import (
    AuthorizationScopeResolution,
    AuthorizationScopeResolutionStatus,
    ExecutionAuthorizationContext,
    ExecutionAuthorizationRequest,
)

from ._canonical import canonical_digest


@dataclass(frozen=True, slots=True)
class HierarchicalAuthorizationScopeResolver:
    """Resolve target and ancestor expressions from a pinned neutral context."""

    async def resolve_scopes(
        self,
        *,
        request: ExecutionAuthorizationRequest,
        context: ExecutionAuthorizationContext,
        scope_expressions: tuple[str, ...],
    ) -> AuthorizationScopeResolution:
        del request
        paths = {
            "target": (
                context.organization,
                context.account,
                context.resource_group,
                context.resource_id,
            ),
            "ancestor(resource_group)": (
                context.organization,
                context.account,
                context.resource_group,
            ),
            "ancestor(account)": (context.organization, context.account),
        }
        resolved: list[str] = []
        try:
            for expression in scope_expressions:
                segments = paths.get(expression)
                if segments is None:
                    return _unknown(
                        context=context,
                        scope_expressions=scope_expressions,
                        reason="scope_expression_requires_graph",
                    )
                scope_ref = ScopeRef(segments=segments).render()
                if scope_ref not in resolved:
                    resolved.append(scope_ref)
        except ValueError:
            return _unknown(
                context=context,
                scope_expressions=scope_expressions,
                reason="invalid_scope_context",
            )
        return AuthorizationScopeResolution(
            status=AuthorizationScopeResolutionStatus.RESOLVED,
            scope_refs=tuple(resolved),
            evidence_digest=canonical_digest(
                {
                    "inventory_generation": context.inventory_generation,
                    "scope_expressions": scope_expressions,
                    "scope_refs": resolved,
                }
            ),
            reason_code="scope_resolved",
        )


def _unknown(
    *,
    context: ExecutionAuthorizationContext,
    scope_expressions: tuple[str, ...],
    reason: str,
) -> AuthorizationScopeResolution:
    return AuthorizationScopeResolution(
        status=AuthorizationScopeResolutionStatus.UNKNOWN,
        scope_refs=(),
        evidence_digest=canonical_digest(
            {
                "inventory_generation": context.inventory_generation,
                "scope_expressions": scope_expressions,
                "reason": reason,
            }
        ),
        reason_code=reason,
    )


__all__ = ["HierarchicalAuthorizationScopeResolver"]
