"""Authenticated, access-scoped Cost Governance route factory."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Awaitable, Callable, Mapping
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
    COST_DISCLOSURE_RETENTION_DAYS,
    CostAccessDecision,
    CostAccessReader,
    CostActivationReader,
    CostActivationSnapshot,
    CostActivationWriter,
    CostAnalyticsReader,
    CostDisclosureAuditRecord,
    CostDisclosureAuditWriter,
    CostProjectionReader,
)
from fdai_operator_service.families.cost_governance.manifest import (
    COST_GOVERNANCE_ROUTE_MANIFEST,
    CostGovernanceRoute,
)
from fdai_operator_service.families.cost_governance.projection import (
    projection_evidence as _projection_evidence,
)
from fdai_operator_service.families.cost_governance.projection import (
    projection_items as _projection_items,
)
from fdai_operator_service.families.cost_governance.projection import (
    resource_candidates as _resource_candidates,
)
from fdai_operator_service.families.cost_governance.projection import (
    surface_complete as _surface_complete,
)
from fdai_service_contracts import (
    DISCLOSURE_PRESETS,
    CostAccessGrant,
    CostAmountPrecision,
    CostAnalyticsBudget,
    CostAnalyticsProjection,
    CostAnalyticsRecommendation,
    CostAnalyticsTrendPoint,
    CostDecisionCaseProjection,
    CostDisclosureCeiling,
    CostDisclosurePolicy,
    CostGovernanceAvailability,
    CostGovernanceProjection,
    CostGovernanceUnavailableReason,
    CostGranularity,
    CostIdentityVisibility,
    CostSettlementOutcomeProjection,
    CostSummaryProjection,
    OperatorRole,
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
    disclosure_audit: CostDisclosureAuditWriter | None = None
    pseudonym_key: bytes | None = None
    authenticated_review_access: bool = False
    clock: Clock = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        if self.pseudonym_key is not None and len(self.pseudonym_key) != 32:
            raise ValueError("Cost Governance pseudonym key MUST contain exactly 32 bytes")


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
        now = dependencies.clock()
        access = await dependencies.access.read_access(
            principal_id=principal.subject_id,
            purpose="cost-governance-review",
            scope=scope,
            now=now,
        )
        if (
            access.grant is None or access.ceiling is None
        ) and dependencies.authenticated_review_access:
            access = _configured_review_access(
                principal_id=principal.subject_id,
                scope=scope,
                now=now,
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
        limit = _limit(request)
        analytics_snapshot = (
            await dependencies.analytics.read_analytics(scope=scope)
            if dependencies.analytics is not None
            else None
        )
        if analytics_snapshot is not None and scope != "*" and analytics_snapshot.scope_id != scope:
            return _error(
                503,
                "analytics_scope_mismatch",
                "Cost Analytics snapshot does not match the requested scope",
            )
        effective_scope = (
            analytics_snapshot.scope_id
            if scope == "*" and analytics_snapshot is not None
            else scope
        )
        raw_analytics = analytics_snapshot.projection if analytics_snapshot is not None else None
        records = (
            ()
            if hidden or surface == "optimization-cases" or surface == "outcomes"
            else await dependencies.projections.read_records(
                surface=surface,
                scope=effective_scope,
                limit=limit,
            )
        )
        analytics = _disclose_analytics(
            raw_analytics,
            disclosure,
            pseudonym_key=dependencies.pseudonym_key,
        )
        evidence_snapshot = await dependencies.projections.read_projection_evidence(
            scope=effective_scope,
            analytics_snapshot_id=(
                analytics_snapshot.snapshot_id if analytics_snapshot is not None else None
            ),
        )
        pseudonym_key = dependencies.pseudonym_key
        candidates = _resource_candidates(
            analytics,
            disclosure,
            pseudonym_key=pseudonym_key,
        )
        can_disclose_lineage = (
            disclosure.granularity is CostGranularity.RESOURCE
            and disclosure.identity_visibility is not CostIdentityVisibility.NONE
            and pseudonym_key is not None
        )
        cases: tuple[CostDecisionCaseProjection, ...] = ()
        outcomes: tuple[CostSettlementOutcomeProjection, ...] = ()
        if surface == "optimization-cases" and pseudonym_key is not None and can_disclose_lineage:
            cases = await dependencies.projections.read_decision_cases(
                scope=effective_scope,
                limit=limit,
                pseudonym_key=pseudonym_key,
            )
        elif surface == "outcomes" and pseudonym_key is not None and can_disclose_lineage:
            outcomes = await dependencies.projections.read_settlement_outcomes(
                scope=effective_scope,
                limit=limit,
                pseudonym_key=pseudonym_key,
            )
        try:
            items, resource_mode = _projection_items(
                surface=surface,
                records=records,
                disclosure=disclosure,
                candidates=candidates,
                cases=cases,
                outcomes=outcomes,
                pseudonym_key=pseudonym_key,
            )
        except ValueError:
            return _error(503, "disclosure_unavailable", "Cost disclosure cannot be completed")
        evidence = _projection_evidence(
            snapshot=evidence_snapshot,
            disclosure=disclosure,
            analytics=raw_analytics,
            analytics_snapshot_id=(
                analytics_snapshot.snapshot_id if analytics_snapshot is not None else None
            ),
            candidates=candidates,
            can_disclose_lineage=can_disclose_lineage,
            requested_surface=surface,
            observation_returned_count=(
                None
                if hidden or surface == "optimization-cases" or surface == "outcomes"
                else len(records)
            ),
            candidate_returned_count=len(candidates),
            case_returned_count=len(cases),
            settlement_returned_count=len(outcomes),
            now=now,
        )
        projection_payload = CostGovernanceProjection(
            surface=surface,
            disclosure=disclosure,
            generated_at=now,
            source_authority={
                "optimization-cases": "cost-governance-decision-store",
                "outcomes": "cost-governance-settlement-store",
            }.get(surface, "cost-observation"),
            complete=_surface_complete(
                surface,
                evidence,
                resource_efficiency_mode=resource_mode,
            ),
            items=items,
            suppressed_count=sum(
                1 for item in items if isinstance(item, CostSummaryProjection) and item.suppressed
            ),
            analytics=analytics,
            evidence=evidence,
            resource_efficiency_mode=resource_mode,
        )
        if dependencies.disclosure_audit is not None:
            try:
                await dependencies.disclosure_audit.append_disclosure_audit(
                    _disclosure_audit_record(
                        principal_id=principal.subject_id,
                        scope=effective_scope,
                        surface=surface,
                        grant_revision=access.grant.revision,
                        ceiling_revision=access.ceiling.revision,
                        activation_revision=activation.revision,
                        disclosure=disclosure,
                        record_count=len(projection_payload.items),
                        suppressed_count=projection_payload.suppressed_count,
                        occurred_at=now,
                    )
                )
            except RuntimeError:
                return _error(
                    503,
                    "disclosure_audit_unavailable",
                    "Cost disclosure audit is unavailable",
                )
        response = JSONResponse(projection_payload.model_dump(mode="json", exclude_none=True))
        if entry.legacy_alias:
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = '</cost-governance/overview>; rel="successor-version"'
        return response

    endpoint.__name__ = entry.name
    return Route(entry.path, endpoint, methods=[entry.method], name=entry.name)


def _disclosure_audit_record(
    *,
    principal_id: str,
    scope: str,
    surface: str,
    grant_revision: int,
    ceiling_revision: int,
    activation_revision: int,
    disclosure: CostDisclosurePolicy,
    record_count: int,
    suppressed_count: int,
    occurred_at: datetime,
) -> CostDisclosureAuditRecord:
    disclosure_digest = _digest(disclosure.model_dump(mode="json"))
    principal_digest = _digest(principal_id)
    scope_digest = _digest(scope)
    decision_id = _digest(
        {
            "activation_revision": activation_revision,
            "ceiling_revision": ceiling_revision,
            "disclosure_digest": disclosure_digest,
            "grant_revision": grant_revision,
            "occurred_at": occurred_at.isoformat(),
            "principal_digest": principal_digest,
            "record_count": record_count,
            "retention_until": (
                occurred_at + timedelta(days=COST_DISCLOSURE_RETENTION_DAYS)
            ).isoformat(),
            "scope_digest": scope_digest,
            "suppressed_count": suppressed_count,
            "surface": surface,
        }
    )
    return CostDisclosureAuditRecord(
        decision_id=decision_id,
        principal_digest=principal_digest,
        scope_digest=scope_digest,
        surface=surface,
        grant_revision=grant_revision,
        ceiling_revision=ceiling_revision,
        activation_revision=activation_revision,
        disclosure_digest=disclosure_digest,
        record_count=record_count,
        suppressed_count=suppressed_count,
        occurred_at=occurred_at,
        retention_until=occurred_at + timedelta(days=COST_DISCLOSURE_RETENTION_DAYS),
    )


def _digest(value: object) -> str:
    payload = (
        value.encode()
        if isinstance(value, str)
        else json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _disclose_analytics(
    analytics: CostAnalyticsProjection | None,
    disclosure: CostDisclosurePolicy,
    *,
    pseudonym_key: bytes | None,
) -> CostAnalyticsProjection | None:
    if analytics is None or disclosure.granularity is CostGranularity.NONE:
        return None
    recommendations_allowed = (
        disclosure.granularity is CostGranularity.RESOURCE
        and disclosure.identity_visibility is not CostIdentityVisibility.NONE
        and pseudonym_key is not None
    )
    recommendations = (
        tuple(
            CostAnalyticsRecommendation(
                **{
                    **item.model_dump(),
                    "resource_ref": (
                        _resource_pseudonym(item.resource_ref, pseudonym_key)
                        if item.resource_ref is not None
                        else None
                    ),
                    "monthly_savings": _disclosed_amount(item.monthly_savings, disclosure),
                }
            )
            for item in analytics.recommendations
        )
        if recommendations_allowed
        else ()
    )
    if disclosure.amount_precision in {
        CostAmountPrecision.NONE,
        CostAmountPrecision.BAND,
    }:
        return CostAnalyticsProjection(
            source_authority=analytics.source_authority,
            observed_at=analytics.observed_at,
            complete=analytics.complete,
            window_start_at=analytics.window_start_at,
            window_end_at=analytics.window_end_at,
            sources=analytics.sources,
            recommendations=recommendations,
            limitations=tuple(
                sorted(
                    {
                        *analytics.limitations,
                        "analytics_amount_suppressed",
                        *(
                            ("analytics_recommendations_suppressed",)
                            if analytics.recommendations and not recommendations_allowed
                            else ()
                        ),
                    }
                )
            ),
        )
    trend = tuple(
        projected
        for item in analytics.trend
        if (projected := _disclosed_trend(item, disclosure)) is not None
    )
    budgets = tuple(
        budget
        for item in analytics.budgets
        if (budget := _disclosed_budget(item, disclosure)) is not None
    )
    recommendation_amount_suppressed = (
        any(
            item.monthly_savings is not None and item.monthly_savings > 0
            for item in analytics.recommendations
        )
        if not recommendations_allowed
        else any(
            source.monthly_savings is not None
            and source.monthly_savings > 0
            and disclosed.monthly_savings is None
            for source, disclosed in zip(
                analytics.recommendations,
                recommendations,
                strict=True,
            )
        )
    )
    amount_suppressed = (
        len(trend) != len(analytics.trend)
        or len(budgets) != len(analytics.budgets)
        or recommendation_amount_suppressed
    )
    recommendation_details_suppressed = bool(
        analytics.recommendations and not recommendations_allowed
    )
    return CostAnalyticsProjection(
        source_authority=analytics.source_authority,
        observed_at=analytics.observed_at,
        complete=analytics.complete,
        window_start_at=analytics.window_start_at,
        window_end_at=analytics.window_end_at,
        sources=analytics.sources,
        trend=trend,
        budgets=budgets,
        recommendations=recommendations,
        limitations=tuple(
            sorted(
                {
                    *analytics.limitations,
                    *(("analytics_amount_suppressed",) if amount_suppressed else ()),
                    *(
                        ("analytics_recommendations_suppressed",)
                        if recommendation_details_suppressed
                        else ()
                    ),
                }
            )
        ),
    )


def _disclosed_trend(
    item: CostAnalyticsTrendPoint,
    disclosure: CostDisclosurePolicy,
) -> CostAnalyticsTrendPoint | None:
    amount = _disclosed_amount(item.amount, disclosure)
    if amount is None:
        return None
    return CostAnalyticsTrendPoint(**{**item.model_dump(), "amount": amount})


def _disclosed_budget(
    item: CostAnalyticsBudget,
    disclosure: CostDisclosurePolicy,
) -> CostAnalyticsBudget | None:
    amount = _disclosed_amount(item.amount, disclosure)
    current_spend = _disclosed_amount(item.current_spend, disclosure)
    if amount is None or current_spend is None or amount <= 0:
        return None
    return CostAnalyticsBudget(
        **{
            **item.model_dump(),
            "amount": amount,
            "current_spend": current_spend,
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
    rounded = (value / increment).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * increment
    return None if value > 0 and rounded == 0 else rounded


def _resource_pseudonym(value: str, key: bytes | None) -> str:
    if key is None:
        raise ValueError("resource pseudonym requires a server-held key")
    digest = hmac.new(key, f"cost-candidate:{value}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"resource:{digest}"


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


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "code": code, "message": message}},
        status_code=status,
    )


__all__ = ["CostGovernanceFamilyDependencies", "build_cost_governance_routes"]
