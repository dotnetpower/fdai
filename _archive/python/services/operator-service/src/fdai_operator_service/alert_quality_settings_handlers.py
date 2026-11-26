"""Scoped Settings reads and revision-bound human Owner preference updates."""

from __future__ import annotations

import re
from typing import cast

from fdai_service_contracts import OperatorPrincipal
from starlette.requests import Request
from starlette.responses import Response

from fdai_operator_service.alert_quality_auth import _require_scope, _revalidate
from fdai_operator_service.alert_quality_boundary import (
    _body,
    _query_scope,
    _RequestError,
    _response,
)
from fdai_operator_service.alert_quality_config import AlertQualityDependencies
from fdai_operator_service.alert_quality_records import (
    AlertQualityUnavailableError,
    alert_quality_requester_ref,
)
from fdai_operator_service.alert_quality_settings import (
    MAX_ALERT_QUALITY_REVISION,
    AlertQualityPreference,
    AlertQualityPrerequisites,
    AlertQualitySettingsBody,
    project_alert_quality_settings,
    verify_alert_quality_preference,
)
from fdai_operator_service.alert_quality_sources import _producer_is_ready, _read_preference


async def _settings(
    request: Request,
    dependencies: AlertQualityDependencies,
    principal: OperatorPrincipal,
    *,
    write: bool,
) -> Response:
    """Revalidate scoped access around preference I/O and immediately before atomic insertion."""
    body = await _body(request, AlertQualitySettingsBody) if write else None
    scope = _query_scope(request) if body is None else body.scope_ref
    _require_scope(dependencies, principal, scope)
    try:
        expected = _settings_revision(request, body) if body is not None else None
        ready = await _producer_is_ready(dependencies)
        preference: AlertQualityPreference | None
        if body is not None:
            store = dependencies.preference_store
            if store is None:
                raise _RequestError(503, "unavailable")

            def guard() -> None:
                _revalidate(request, dependencies, principal, scope, write=True, owner=True)

            guard()
            requester = alert_quality_requester_ref(principal.subject_id, scope)
            preference = await store.set_enabled(
                scope_ref=scope,
                enabled=body.enabled,
                expected_revision=cast(int, expected),
                requester_ref=requester,
                before_commit=guard,
            )
            preference = verify_alert_quality_preference(
                preference, scope_ref=scope, now=dependencies.clock()
            )
            if (
                preference.expected_revision != expected
                or preference.enabled is not body.enabled
                or preference.requester_ref != requester
            ):
                raise AlertQualityUnavailableError(
                    "alert quality preference receipt is unavailable"
                )
            readable = True
        else:
            preference, readable = await _read_preference(dependencies, scope)
        projection = project_alert_quality_settings(
            scope_ref=scope,
            preference=preference,
            default_enabled=dependencies.enabled,
            prerequisites=AlertQualityPrerequisites(
                source_bound=dependencies.source is not None,
                writer_bound=dependencies.proposal_writer is not None,
                producer_ready=ready,
                preference_store_available=readable,
            ),
        )
        response = _response(projection)
        if projection.revision is not None:
            response.headers["ETag"] = f'"{projection.revision}"'
        return response
    finally:
        _revalidate(request, dependencies, principal, scope, write=write, owner=write)


def _settings_revision(request: Request, body: AlertQualitySettingsBody) -> int:
    """Accept one bounded precondition, never weak tags, wildcards or coercion."""
    values = request.headers.getlist("if-match")
    if len(values) > 1 or (values and body.expected_revision is not None):
        raise _RequestError(400, "invalid_request")
    if not values:
        if body.expected_revision is None:
            raise _RequestError(428, "precondition_required")
        return body.expected_revision
    raw = values[0]
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    if re.fullmatch(r"0|[1-9][0-9]{0,15}", raw) is None or int(raw) >= MAX_ALERT_QUALITY_REVISION:
        raise _RequestError(400, "invalid_request")
    return int(raw)
