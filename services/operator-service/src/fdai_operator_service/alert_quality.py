"""Authenticated alert-quality route assembly and compatibility imports.

Responsibility: dispatch the fixed manifest with bounded timeouts and safe error mapping.
Boundary: current identity and scope checks surround handlers; no provider mutation exists.
Authority and state: Operator owns projections, preferences and inert proposal acceptance.
Dependencies: explicit authenticated bindings; missing dependencies fail closed.
Deployment: composition mounts these routes and separately owns the trusted runtime bridge.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import cast

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from fdai_operator_service.alert_quality_auth import _READ_ROLES as _READ_ROLES
from fdai_operator_service.alert_quality_auth import _REQUEST_ROLES as _REQUEST_ROLES
from fdai_operator_service.alert_quality_auth import _authenticate as _authenticate
from fdai_operator_service.alert_quality_auth import _require_scope as _require_scope
from fdai_operator_service.alert_quality_auth import _revalidate as _revalidate
from fdai_operator_service.alert_quality_boundary import _body as _body
from fdai_operator_service.alert_quality_boundary import _error as _error
from fdai_operator_service.alert_quality_boundary import _query_scope as _query_scope
from fdai_operator_service.alert_quality_boundary import _RequestError as _RequestError
from fdai_operator_service.alert_quality_boundary import _response as _response
from fdai_operator_service.alert_quality_boundary import _unavailable as _unavailable
from fdai_operator_service.alert_quality_config import (
    PRINCIPAL_SCOPES_ENV,
    AlertQualityDependencies,
    ProducerReady,
    alert_quality_dependencies_from_environment,
    parse_alert_quality_principal_scopes,
)
from fdai_operator_service.alert_quality_config import _unique_object as _unique_object
from fdai_operator_service.alert_quality_contracts import (
    MAX_ALERT_QUALITY_BODY_BYTES,
    AlertAssessmentBody,
    AlertProposalBody,
    AlertQualityResponse,
    AlertQualityScopesResponse,
    Operation,
    RouteOperation,
    UnavailableReason,
)
from fdai_operator_service.alert_quality_handlers import _IDEMPOTENCY as _IDEMPOTENCY
from fdai_operator_service.alert_quality_handlers import _get as _get
from fdai_operator_service.alert_quality_handlers import _get_scopes as _get_scopes
from fdai_operator_service.alert_quality_handlers import _post as _post
from fdai_operator_service.alert_quality_handlers import (
    _require_current_evidence as _require_current_evidence,
)
from fdai_operator_service.alert_quality_history_handler import get_alert_quality_history
from fdai_operator_service.alert_quality_records import AlertQualityConflictError
from fdai_operator_service.alert_quality_settings import AlertQualityPreferenceConflictError
from fdai_operator_service.alert_quality_settings_handlers import _settings as _settings
from fdai_operator_service.alert_quality_settings_handlers import (
    _settings_revision as _settings_revision,
)
from fdai_operator_service.alert_quality_sources import _current as _current
from fdai_operator_service.alert_quality_sources import _effective_enabled as _effective_enabled
from fdai_operator_service.alert_quality_sources import _producer_is_ready as _producer_is_ready
from fdai_operator_service.alert_quality_sources import _read_preference as _read_preference
from fdai_operator_service.alert_quality_sources import _read_snapshot as _read_snapshot
from fdai_operator_service.auth import AuthenticationError, AuthorizationError
from fdai_operator_service.families.operations.contracts import ProposalConflictError

__all__ = [
    "ALERT_QUALITY_ROUTE_MANIFEST",
    "MAX_ALERT_QUALITY_BODY_BYTES",
    "PRINCIPAL_SCOPES_ENV",
    "AlertAssessmentBody",
    "AlertProposalBody",
    "AlertQualityDependencies",
    "AlertQualityResponse",
    "AlertQualityScopesResponse",
    "Operation",
    "ProducerReady",
    "RouteOperation",
    "UnavailableReason",
    "alert_quality_dependencies_from_environment",
    "build_alert_quality_routes",
    "parse_alert_quality_principal_scopes",
]

ALERT_QUALITY_ROUTE_MANIFEST = (
    ("GET", "/alert-quality", "get_alert_quality"),
    ("POST", "/alert-quality/assess", "assess_alert_quality"),
    ("POST", "/alert-quality/proposals", "propose_alert_quality"),
    ("GET", "/alert-quality/scopes", "get_alert_quality_scopes"),
    ("GET", "/alert-quality/settings", "get_alert_quality_settings"),
    ("PUT", "/alert-quality/settings", "put_alert_quality_settings"),
    ("GET", "/alert-quality/requests", "get_alert_quality_requests"),
)
_LOGGER = logging.getLogger(__name__)


def build_alert_quality_routes(dependencies: AlertQualityDependencies) -> tuple[Route, ...]:
    """Return the complete independently authenticated assessment/settings manifest."""

    def endpoint(operation: RouteOperation | None) -> Callable[[Request], Awaitable[Response]]:
        async def handle(request: Request) -> Response:
            return await _handle(request, dependencies, operation=operation)

        return handle

    operations: tuple[RouteOperation | None, ...] = (
        None,
        "alert_noise.assess",
        "alert_noise.propose",
        "scopes",
        "settings.get",
        "settings.put",
        "requests.get",
    )
    return tuple(
        Route(path, endpoint(operation), methods=[method], name=name)
        for (method, path, name), operation in zip(
            ALERT_QUALITY_ROUTE_MANIFEST, operations, strict=True
        )
    )


async def _handle(
    request: Request, dependencies: AlertQualityDependencies, *, operation: RouteOperation | None
) -> Response:
    """Bound dispatch and recheck current authorization before mapping any handler outcome."""
    try:
        async with asyncio.timeout(dependencies.timeout_seconds):
            write = operation in {"alert_noise.assess", "alert_noise.propose", "settings.put"}
            owner = operation == "settings.put"
            principal = _authenticate(request, dependencies, write=write, owner=owner)
            try:
                if operation is None:
                    return await _get(request, dependencies, principal)
                if operation == "scopes":
                    return _get_scopes(request, dependencies, principal)
                if operation == "requests.get":
                    return await get_alert_quality_history(request, dependencies, principal)
                if operation in {"settings.get", "settings.put"}:
                    return await _settings(request, dependencies, principal, write=owner)
                return await _post(request, dependencies, principal, cast(Operation, operation))
            finally:
                # Even a timeout or dependency failure cannot return under an old identity.
                _revalidate(request, dependencies, principal, None, write=write, owner=owner)
    except AuthenticationError:
        return _error(401, "unauthenticated")
    except AuthorizationError:
        return _error(403, "forbidden")
    except _RequestError as exc:
        return _error(exc.status, exc.code)
    except AlertQualityPreferenceConflictError:
        return _error(409, "revision_conflict")
    except (ProposalConflictError, AlertQualityConflictError):
        return _error(409, "idempotency_conflict")
    except Exception as exc:  # noqa: BLE001 - injected dependencies fail closed without content
        _LOGGER.warning(
            "alert quality dependency failed",
            extra={"event": "alert_quality.dependency_failed", "failure_type": type(exc).__name__},
        )
        if operation is None:
            return _response(_unavailable(dependencies, "source_unavailable"))
        return _error(503, "unavailable")
