"""Authenticated read-only routes for AKS commerce business impact."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_operator_service.auth import (
    AuthenticationError,
    AuthorizationError,
    OperatorAuthenticator,
)
from fdai_operator_service.families.aks_commerce.contracts import (
    AksCommerceProjectionReader,
)
from fdai_operator_service.families.aks_commerce.manifest import (
    AKS_COMMERCE_ROUTE_MANIFEST,
)
from fdai_service_contracts import OperatorRole
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

_READ_ROLES = frozenset(OperatorRole)
_SERVICE_IDS = frozenset({"catalog-browse", "order-fulfillment"})


@dataclass(frozen=True, slots=True)
class AksCommerceFamilyDependencies:
    """Non-authoritative dependencies for the AKS commerce read surface."""

    authenticator: OperatorAuthenticator
    projections: AksCommerceProjectionReader


def build_aks_commerce_routes(
    dependencies: AksCommerceFamilyDependencies,
) -> tuple[Route, ...]:
    """Build the authenticated overview route."""

    async def overview(request: Request) -> Response:
        try:
            dependencies.authenticator.require_any(
                request.headers.get("authorization"),
                _READ_ROLES,
            )
        except AuthenticationError as exc:
            return _error(401, "authentication_required", str(exc))
        except AuthorizationError as exc:
            return _error(403, "role_access_denied", str(exc))
        service_id = request.query_params.get("service_id", "order-fulfillment").strip()
        if service_id not in _SERVICE_IDS:
            return _error(
                400,
                "invalid_service_id",
                "service_id must be catalog-browse or order-fulfillment",
            )
        projection = await dependencies.projections.read_latest(service_id)
        if projection is None:
            return _error(
                404,
                "projection_unavailable",
                "AKS commerce projection is unavailable",
            )
        return JSONResponse(projection.model_dump(mode="json"))

    route = AKS_COMMERCE_ROUTE_MANIFEST[0]
    return (Route(route.path, overview, methods=[route.method], name=route.name),)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "code": code, "message": message}},
        status_code=status,
    )


__all__ = ["AksCommerceFamilyDependencies", "build_aks_commerce_routes"]
