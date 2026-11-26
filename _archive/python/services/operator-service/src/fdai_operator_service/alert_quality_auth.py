"""Current-principal role and exact-scope authorization for alert-quality requests."""

from __future__ import annotations

from fdai_service_contracts import OperatorPrincipal, OperatorPrincipalKind, OperatorRole
from starlette.requests import Request

from fdai_operator_service.alert_quality_config import AlertQualityDependencies
from fdai_operator_service.alert_quality_records import (
    AlertQualityUnavailableError,
    validate_alert_quality_principal,
)
from fdai_operator_service.auth import AuthenticationError, AuthorizationError

_READ_ROLES = frozenset(
    {OperatorRole.READER, OperatorRole.CONTRIBUTOR, OperatorRole.APPROVER, OperatorRole.OWNER}
)
_REQUEST_ROLES = _READ_ROLES - {OperatorRole.READER}


def _authenticate(
    request: Request, dependencies: AlertQualityDependencies, *, write: bool, owner: bool = False
) -> OperatorPrincipal:
    """Resolve exactly one bearer header; writes require a human at the current role floor."""
    if len(request.headers.getlist("authorization")) != 1:
        raise AuthenticationError("authentication required")
    principal = dependencies.authenticator.require_any(
        request.headers.get("authorization"),
        frozenset({OperatorRole.OWNER}) if owner else _REQUEST_ROLES if write else _READ_ROLES,
    )
    if write and principal.principal_kind is not OperatorPrincipalKind.HUMAN:
        raise AuthorizationError("human request authority required")
    try:
        validate_alert_quality_principal(principal.subject_id)
    except ValueError as exc:
        raise AuthenticationError("authentication required") from exc
    return principal


def _require_scope(
    dependencies: AlertQualityDependencies, principal: OperatorPrincipal, scope: str
) -> None:
    """Require an exact server-owned binding without disclosing an embedded subject."""
    if scope not in dependencies.principal_scopes.get(principal.subject_id, frozenset()):
        raise AuthorizationError("scope access denied")
    if principal.subject_id.casefold() in scope.casefold():
        raise AlertQualityUnavailableError("alert quality scope disclosure is unavailable")


def _revalidate(
    request: Request,
    dependencies: AlertQualityDependencies,
    principal: OperatorPrincipal,
    scope: str | None,
    *,
    write: bool,
    owner: bool = False,
) -> None:
    """Reject identity, role or scope drift after awaits and before durable acceptance."""
    if _authenticate(request, dependencies, write=write, owner=owner) != principal:
        raise AuthorizationError("request identity changed")
    if scope is not None:
        _require_scope(dependencies, principal, scope)
