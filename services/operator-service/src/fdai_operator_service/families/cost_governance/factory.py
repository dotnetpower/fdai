"""Authenticated, access-scoped Cost Governance route factory."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from fdai_operator_service.auth import (
    AuthenticationError,
    AuthorizationError,
    OperatorAuthenticator,
)
from fdai_operator_service.families.cost_governance.contracts import (
    CostAccessReader,
    CostActivationReader,
    CostProjectionReader,
)
from fdai_operator_service.families.cost_governance.manifest import (
    COST_GOVERNANCE_ROUTE_MANIFEST,
    CostGovernanceRoute,
)
from fdai_service_contracts import (
    CostAmountPrecision,
    CostGovernanceAvailability,
    CostGovernanceItem,
    CostGovernanceProjection,
    CostGovernanceUnavailableReason,
    CostGranularity,
    CostIdentityVisibility,
    CostOptimizationCaseProjection,
    CostOutcomeProjection,
    CostResourceEfficiencyProjection,
    CostSummaryProjection,
    CostTrendProjection,
    OperatorRole,
    disclose_cost_records,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

PACKAGE_ID: Final = "fdai-cost-governance"
READ_ROLES: Final = frozenset(OperatorRole)
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CostGovernanceFamilyDependencies:
    """Explicit non-authoritative dependencies for the Cost Governance family."""

    authenticator: OperatorAuthenticator
    access: CostAccessReader
    activation: CostActivationReader
    projections: CostProjectionReader
    pseudonym_key: bytes | None = None
    clock: Clock = lambda: datetime.now(UTC)


def build_cost_governance_routes(
    dependencies: CostGovernanceFamilyDependencies,
) -> tuple[Route, ...]:
    """Build read routes with authentication, grant, and activation preflight."""

    return tuple(_build_route(entry, dependencies) for entry in COST_GOVERNANCE_ROUTE_MANIFEST)


def _build_route(
    entry: CostGovernanceRoute,
    dependencies: CostGovernanceFamilyDependencies,
) -> Route:
    async def endpoint(request: Request) -> Response:
        try:
            principal = dependencies.authenticator.require_any(
                request.headers.get("authorization"),
                READ_ROLES,
            )
        except AuthenticationError as exc:
            return _error(401, "authentication_required", str(exc))
        except AuthorizationError as exc:
            return _error(403, "role_access_denied", str(exc))

        scope = request.query_params.get("scope", "*").strip()
        if not scope or len(scope) > 1024:
            return _error(400, "invalid_scope", "scope must contain 1 to 1024 characters")
        access = await dependencies.access.read_access(
            principal_id=principal.subject_id,
            purpose="cost-governance-review",
            scope=scope,
            now=dependencies.clock(),
        )
        if access.grant is None or access.ceiling is None:
            reason = access.reason or CostGovernanceUnavailableReason.ACCESS_GRANT_MISSING
            return _error(403, reason.value, "Cost Governance access is required")
        if "*" not in access.grant.scopes and scope not in access.grant.scopes:
            return _error(
                403,
                CostGovernanceUnavailableReason.ACCESS_SCOPE_MISMATCH.value,
                "Cost Governance scope is not granted",
            )
        disclosure = access.grant.disclosure.meet(access.ceiling.disclosure)

        activation = await dependencies.activation.read_activation(PACKAGE_ID)
        unavailable = _activation_reason(activation)
        if unavailable is not None:
            if entry.surface == "availability":
                availability_payload = CostGovernanceAvailability(
                    available=False,
                    enabled=False,
                    access_allowed=True,
                    activation_revision=activation.revision if activation else None,
                    availability_reasons=(
                        activation.availability_reasons
                        if activation
                        else (CostGovernanceUnavailableReason.PACKAGE_ABSENT.value,)
                    ),
                    package_version=activation.package_version if activation else None,
                    image_digest=activation.image_digest if activation else None,
                    asset_manifest_digest=(
                        activation.asset_manifest_digest if activation else None
                    ),
                    semantic_profile_digest=(
                        activation.semantic_profile_digest if activation else None
                    ),
                    ontology_release_digest=(
                        activation.ontology_release_digest if activation else None
                    ),
                    reason=unavailable,
                    disclosure=disclosure,
                )
                return JSONResponse(
                    availability_payload.model_dump(mode="json"),
                    status_code=404,
                )
            return _error(404, unavailable.value, "Cost Governance is unavailable")
        if activation is None:  # Defensive narrowing after the typed reason check.
            return _error(404, "package_absent", "Cost Governance is unavailable")

        if entry.surface == "availability":
            availability_payload = CostGovernanceAvailability(
                available=True,
                enabled=activation.enabled,
                access_allowed=True,
                activation_revision=activation.revision,
                availability_reasons=(),
                package_version=activation.package_version,
                image_digest=activation.image_digest,
                asset_manifest_digest=activation.asset_manifest_digest,
                semantic_profile_digest=activation.semantic_profile_digest,
                ontology_release_digest=activation.ontology_release_digest,
                disclosure=disclosure,
            )
            return JSONResponse(availability_payload.model_dump(mode="json"))

        if not activation.enabled:
            return _error(
                404,
                CostGovernanceUnavailableReason.PACKAGE_DISABLED.value,
                "Cost Governance is disabled",
            )
        hidden = (
            disclosure.granularity is CostGranularity.NONE
            and disclosure.identity_visibility is CostIdentityVisibility.NONE
            and disclosure.amount_precision is CostAmountPrecision.NONE
        )
        records = (
            ()
            if hidden
            else await dependencies.projections.read_records(
                surface=entry.surface,
                scope=scope,
                limit=_limit(request),
            )
        )
        try:
            items = disclose_cost_records(
                records,
                disclosure,
                pseudonym_key=dependencies.pseudonym_key,
            )
        except ValueError:
            return _error(503, "disclosure_unavailable", "Cost disclosure cannot be completed")
        projection_payload = CostGovernanceProjection(
            surface=entry.surface,
            disclosure=disclosure,
            generated_at=dependencies.clock(),
            source_authority="cost-observation",
            complete=all(item.completeness == 1 for item in records),
            items=_typed_projection_items(entry.surface, items),
            suppressed_count=sum(1 for item in items if item.get("suppressed") is True),
        )
        response = JSONResponse(projection_payload.model_dump(mode="json", exclude_none=True))
        if entry.legacy_alias:
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = '</cost-governance/overview>; rel="successor-version"'
        return response

    endpoint.__name__ = entry.name
    return Route(entry.path, endpoint, methods=["GET"], name=entry.name)


def _activation_reason(activation: object) -> CostGovernanceUnavailableReason | None:
    if activation is None:
        return CostGovernanceUnavailableReason.PACKAGE_ABSENT
    if getattr(activation, "available", False):
        return None
    reasons = tuple(getattr(activation, "availability_reasons", ()))
    first = reasons[0] if reasons else ""
    if first == "host_incompatible":
        return CostGovernanceUnavailableReason.HOST_INCOMPATIBLE
    if first == "ontology_incompatible":
        return CostGovernanceUnavailableReason.ONTOLOGY_INCOMPATIBLE
    if first.startswith("missing_provider:"):
        return CostGovernanceUnavailableReason.MISSING_PROVIDER
    return CostGovernanceUnavailableReason.PACKAGE_INCOMPATIBLE


def _limit(request: Request) -> int:
    raw = request.query_params.get("limit", "200")
    try:
        value = int(raw)
    except ValueError:
        return 200
    return max(1, min(value, 500))


def _typed_projection_items(
    surface: str,
    items: Sequence[Mapping[str, object]],
) -> tuple[CostGovernanceItem, ...]:
    projected: list[CostGovernanceItem] = []
    for item in items:
        if "record_count" in item:
            projected.append(CostSummaryProjection.model_validate(item))
        elif surface == "overview":
            projected.append(CostTrendProjection.model_validate(item))
        elif surface == "resource-efficiency":
            projected.append(CostResourceEfficiencyProjection.model_validate(item))
        elif surface == "optimization-cases":
            projected.append(CostOptimizationCaseProjection.model_validate(item))
        else:
            projected.append(CostOutcomeProjection.model_validate(item))
    return tuple(projected)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "code": code, "message": message}},
        status_code=status,
    )


__all__ = ["CostGovernanceFamilyDependencies", "build_cost_governance_routes"]
