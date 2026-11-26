"""Authenticated read-only request history with access revalidation after dependency I/O."""

from fdai_service_contracts import OperatorPrincipal
from starlette.requests import Request
from starlette.responses import Response

from fdai_operator_service.alert_quality_auth import _require_scope, _revalidate
from fdai_operator_service.alert_quality_boundary import _RequestError, _response
from fdai_operator_service.alert_quality_command import ALERT_REQUEST_KEY
from fdai_operator_service.alert_quality_config import AlertQualityDependencies
from fdai_operator_service.alert_quality_history import AlertQualityRequestHistory
from fdai_operator_service.alert_quality_records import (
    _contains_identity,
    alert_quality_requester_ref,
    validate_alert_quality_scope,
)


async def get_alert_quality_history(
    request: Request, dependencies: AlertQualityDependencies, principal: OperatorPrincipal
) -> Response:
    """Return one exact authorized scope or an explicit error, never an unscoped fallback."""
    fields = request.query_params
    if set(fields) - {"scope_ref", "request_key"} or len(fields.getlist("scope_ref")) != 1:
        raise _RequestError(400, "invalid_request")
    scope = fields["scope_ref"]
    keys = fields.getlist("request_key")
    try:
        validate_alert_quality_scope(scope)
    except ValueError:
        raise _RequestError(400, "invalid_request") from None
    if len(keys) > 1 or (keys and ALERT_REQUEST_KEY.fullmatch(keys[0]) is None):
        raise _RequestError(400, "invalid_request")
    _require_scope(dependencies, principal, scope)
    try:
        if dependencies.request_source is None:
            raise _RequestError(503, "unavailable")
        value = await dependencies.request_source.read(
            principal_id=principal.subject_id,
            scope_ref=scope,
            request_key=keys[0] if keys else None,
        )
        value = AlertQualityRequestHistory.model_validate(value)
        if keys and (
            value.truncated
            or len(value.requests) > 1
            or any(row.request_key != keys[0] for row in value.requests)
        ):
            raise _RequestError(503, "unavailable")
        if (
            value.scope_ref != scope
            or value.read_at > dependencies.clock()
            or any(
                row.plan is not None
                and (
                    row.plan.scope_ref != scope
                    or row.plan.requester_ref
                    != alert_quality_requester_ref(principal.subject_id, scope)
                )
                for row in value.requests
            )
            or _contains_identity(value.model_dump(mode="json"), principal.subject_id)
        ):
            raise _RequestError(503, "unavailable")
        return _response(value)
    finally:
        _revalidate(request, dependencies, principal, scope, write=False)
