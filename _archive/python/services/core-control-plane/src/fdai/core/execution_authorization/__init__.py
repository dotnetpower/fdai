"""Ontology-driven execution-authorization resolution."""

from .evaluator import ResolverBackedExecutionAuthorizationEvaluator
from .grant_request import (
    AccessGrantDecision,
    AccessGrantRequest,
    AccessGrantRequestConflictError,
    AccessGrantRequestError,
    AccessGrantRequestPermissionError,
    AccessGrantRequestService,
    AccessGrantRequestStatus,
)
from .models import (
    AccessObservationStatus,
    AuthorizationConstraints,
    AuthorizationDecision,
    AuthorizationEnforcement,
    AuthorizationObservation,
    AuthorizationPolicyAssignment,
    AuthorizationPosture,
    AuthorizationRequirement,
    AuthorizationScopeLevel,
    AuthorizationStatus,
    GrantMode,
    ResolvedAuthorizationConstraints,
)
from .resolver import (
    ALGORITHM_VERSION,
    authorization_policy_bundle_digest,
    matching_authorization_assignments,
    resolve_execution_authorization,
)
from .scope_resolution import HierarchicalAuthorizationScopeResolver

__all__ = [
    "ALGORITHM_VERSION",
    "AccessGrantDecision",
    "AccessGrantRequest",
    "AccessGrantRequestConflictError",
    "AccessGrantRequestError",
    "AccessGrantRequestPermissionError",
    "AccessGrantRequestService",
    "AccessGrantRequestStatus",
    "AccessObservationStatus",
    "AuthorizationConstraints",
    "AuthorizationDecision",
    "AuthorizationEnforcement",
    "AuthorizationObservation",
    "AuthorizationPolicyAssignment",
    "AuthorizationPosture",
    "AuthorizationRequirement",
    "AuthorizationScopeLevel",
    "AuthorizationStatus",
    "authorization_policy_bundle_digest",
    "GrantMode",
    "HierarchicalAuthorizationScopeResolver",
    "matching_authorization_assignments",
    "ResolvedAuthorizationConstraints",
    "ResolverBackedExecutionAuthorizationEvaluator",
    "resolve_execution_authorization",
]
