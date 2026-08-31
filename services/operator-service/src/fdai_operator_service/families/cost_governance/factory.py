"""Authenticated, access-scoped Cost Governance route factory."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from fdai_operator_service.auth import (
    AuthenticationError,
    AuthorizationError,
    OperatorAuthenticator,
)
from fdai_operator_service.families.cost_governance.contracts import (
    CostAccessDecision,
    CostAccessReader,
    CostActivationReader,
    CostActivationSnapshot,
    CostActivationWriter,
    CostAnalyticsReader,
    CostProjectionReader,
)
from fdai_operator_service.families.cost_governance.manifest import (
    COST_GOVERNANCE_ROUTE_MANIFEST,
    CostGovernanceRoute,
)
from fdai_service_contracts import (
    DISCLOSURE_PRESETS,
    CostAccessGrant,
    CostAmountPrecision,
    CostAnalyticsBudget,
    CostAnalyticsProjection,
    CostAnalyticsRecommendation,
    CostAnalyticsTrendPoint,
    CostDisclosureCeiling,
    CostDisclosurePolicy,
    CostGovernanceAvailability,
    CostGovernanceItem,
    CostGovernanceProjection,
    CostGovernanceUnavailableReason,
    CostGranularity,
    CostIdentityVisibility,
    CostResourceEfficiencyProjection,
    CostSummaryProjection,
    CostTrendProjection,
    OperatorRole,
    disclose_cost_records,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

PACKAGE_ID: Final = "cost-governance"
READ_ROLES: Final = frozenset(OperatorRole)
MANAGE_ROLES: Final = frozenset({OperatorRole.OWNER})
_REQUEST_ID: Final = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{7,127}$")
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CostGovernanceFamilyDependencies:
    """Explicit non-authoritative dependencies for the Cost Governance family."""

    authenticator: OperatorAuthenticator
    access: CostAccessReader
    activation: CostActivationReader
    projections: CostProjectionReader
    analytics: CostAnalyticsReader | None = None
    activation_writer: CostActivationWriter | None = None
    pseudonym_key: bytes | None = None
    authenticated_review_access: bool = False
    clock: Clock = lambda: datetime.now(UTC)


def build_cost_governance_routes(
    dependencies: CostGovernanceFamilyDependencies,
) -> tuple[Route, ...]:
    """Build read routes plus the Owner-scoped activation settings boundary."""

    settings_endpoint = _settings_endpoint(dependencies)
    return (
        *(
            _build_route(entry, dependencies)
            for entry in COST_GOVERNANCE_ROUTE_MANIFEST
            if entry.surface != "settings"
        ),
        *(
            Route(
                entry.path,
                settings_endpoint,
                methods=[entry.method],
                name=entry.name,
            )
            for entry in COST_GOVERNANCE_ROUTE_MANIFEST
            if entry.surface == "settings"
        ),
    )


def _build_route(
    entry: CostGovernanceRoute,
    dependencies: CostGovernanceFamilyDependencies,
) -> Route:
    surface = entry.surface
    if surface == "settings":
        raise ValueError("settings routes use the dedicated activation boundary")

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
        if (
            access.grant is None or access.ceiling is None
        ) and dependencies.authenticated_review_access:
            access = _configured_review_access(
                principal_id=principal.subject_id,
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
            if surface == "availability":
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

        if surface == "availability":
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
                surface=surface,
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
        raw_analytics = (
            await dependencies.analytics.read_analytics(scope=scope)
            if dependencies.analytics is not None
            else None
        )
        analytics = _disclose_analytics(raw_analytics, disclosure)
        projection_payload = CostGovernanceProjection(
            surface=surface,
            disclosure=disclosure,
            generated_at=dependencies.clock(),
            source_authority="cost-observation",
            complete=(
                all(item.completeness == 1 for item in records)
                and (raw_analytics is None or raw_analytics.complete)
            ),
            items=_typed_projection_items(surface, items),
            suppressed_count=sum(1 for item in items if item.get("suppressed") is True),
            analytics=analytics,
        )
        response = JSONResponse(projection_payload.model_dump(mode="json", exclude_none=True))
        if entry.legacy_alias:
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = '</cost-governance/overview>; rel="successor-version"'
        return response

    endpoint.__name__ = entry.name
    return Route(entry.path, endpoint, methods=[entry.method], name=entry.name)


def _disclose_analytics(
    analytics: CostAnalyticsProjection | None,
    disclosure: CostDisclosurePolicy,
) -> CostAnalyticsProjection | None:
    if analytics is None or disclosure.granularity is CostGranularity.NONE:
        return None
    identity_visible = disclosure.identity_visibility is not CostIdentityVisibility.NONE
    recommendations = tuple(
        CostAnalyticsRecommendation(
            **{
                **item.model_dump(),
                "resource_ref": item.resource_ref if identity_visible else None,
                "monthly_savings": _disclosed_amount(item.monthly_savings, disclosure),
            }
        )
        for item in analytics.recommendations
    )
    if disclosure.amount_precision in {
        CostAmountPrecision.NONE,
        CostAmountPrecision.BAND,
    }:
        return CostAnalyticsProjection(
            source_authority=analytics.source_authority,
            observed_at=analytics.observed_at,
            complete=analytics.complete,
            recommendations=recommendations,
            limitations=tuple(sorted({*analytics.limitations, "analytics_amount_suppressed"})),
        )
    return CostAnalyticsProjection(
        source_authority=analytics.source_authority,
        observed_at=analytics.observed_at,
        complete=analytics.complete,
        trend=tuple(
            CostAnalyticsTrendPoint(
                **{
                    **item.model_dump(),
                    "amount": _disclosed_required_amount(item.amount, disclosure),
                }
            )
            for item in analytics.trend
        ),
        budgets=tuple(
            budget
            for item in analytics.budgets
            if (budget := _disclosed_budget(item, disclosure)) is not None
        ),
        recommendations=recommendations,
        limitations=analytics.limitations,
    )


def _disclosed_required_amount(
    value: Decimal,
    disclosure: CostDisclosurePolicy,
) -> Decimal:
    disclosed = _disclosed_amount(value, disclosure)
    if disclosed is None:
        raise ValueError("required analytics amount was suppressed")
    return disclosed


def _disclosed_budget(
    item: CostAnalyticsBudget,
    disclosure: CostDisclosurePolicy,
) -> CostAnalyticsBudget | None:
    amount = _disclosed_required_amount(item.amount, disclosure)
    if amount <= 0:
        return None
    return CostAnalyticsBudget(
        **{
            **item.model_dump(),
            "amount": amount,
            "current_spend": _disclosed_required_amount(
                item.current_spend,
                disclosure,
            ),
            "forecast_spend": _disclosed_amount(item.forecast_spend, disclosure),
        }
    )


def _disclosed_amount(
    value: Decimal | None,
    disclosure: CostDisclosurePolicy,
) -> Decimal | None:
    if value is None:
        return None
    if disclosure.amount_precision is CostAmountPrecision.EXACT:
        return value
    if disclosure.amount_precision is not CostAmountPrecision.ROUNDED:
        return None
    increment = disclosure.rounding_increment
    return (value / increment).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * increment


def _settings_endpoint(
    dependencies: CostGovernanceFamilyDependencies,
) -> Callable[[Request], Awaitable[Response]]:
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

        activation = await dependencies.activation.read_activation(PACKAGE_ID)
        can_manage = bool(principal.roles & MANAGE_ROLES)
        if request.method == "GET":
            return JSONResponse(_settings_payload(activation, can_manage=can_manage))
        if not can_manage:
            return _error(403, "role_access_denied", "Owner role is required")
        if dependencies.activation_writer is None:
            return _error(
                503,
                "activation_writer_unavailable",
                "Cost Governance activation changes are unavailable",
            )
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "invalid_json", "Request body MUST be valid JSON")
        if not isinstance(body, Mapping):
            return _error(400, "invalid_body", "Request body MUST be an object")
        enabled = body.get("enabled")
        expected_revision = body.get("expected_revision")
        request_id = body.get("request_id")
        if not isinstance(enabled, bool):
            return _error(400, "invalid_enabled", "enabled MUST be a boolean")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            return _error(400, "invalid_revision", "expected_revision MUST be an integer")
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            return _error(400, "invalid_request_id", "request_id has an invalid format")
        try:
            updated = await dependencies.activation_writer.set_enabled(
                package_id=PACKAGE_ID,
                actor_id=principal.subject_id,
                enabled=enabled,
                expected_revision=expected_revision,
                request_id=request_id,
            )
        except ValueError as exc:
            return _error(409, "activation_conflict", str(exc))
        except RuntimeError as exc:
            return _error(503, "activation_unavailable", str(exc))
        return JSONResponse(_settings_payload(updated, can_manage=True))

    return endpoint


def _configured_review_access(
    *,
    principal_id: str,
    scope: str,
    now: datetime,
) -> CostAccessDecision:
    policy = DISCLOSURE_PRESETS["aggregate"]
    return CostAccessDecision(
        grant=CostAccessGrant(
            grant_id=f"configured-authenticated-review:{principal_id}",
            principal_id=principal_id,
            revision=0,
            purpose="cost-governance-review",
            scopes=(scope,),
            disclosure=policy,
            effective_at=now,
            expires_at=now + timedelta(minutes=15),
            source_authority="configured-authenticated-review-policy",
        ),
        ceiling=CostDisclosureCeiling(
            revision=0,
            disclosure=policy,
            effective_at=now,
            source_authority="configured-authenticated-review-policy",
        ),
    )


def _settings_payload(
    activation: CostActivationSnapshot | None,
    *,
    can_manage: bool,
) -> dict[str, object]:
    if activation is None:
        return {
            "available": False,
            "enabled": False,
            "can_manage": can_manage,
            "activation_revision": None,
            "availability_reasons": ["package_absent"],
            "package_version": None,
        }
    return {
        "available": activation.available,
        "enabled": activation.enabled,
        "can_manage": can_manage,
        "activation_revision": activation.revision,
        "availability_reasons": list(activation.availability_reasons),
        "package_version": activation.package_version,
    }


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
        elif surface in {"optimization-cases", "outcomes"}:
            continue
    return tuple(projected)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "code": code, "message": message}},
        status_code=status,
    )


__all__ = ["CostGovernanceFamilyDependencies", "build_cost_governance_routes"]
