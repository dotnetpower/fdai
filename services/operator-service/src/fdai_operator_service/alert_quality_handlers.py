"""Scoped report reads and inert assessment/proposal acceptance for alert quality."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime

from fdai_service_contracts import OperatorPrincipal, OperatorPrincipalKind
from starlette.requests import Request
from starlette.responses import Response

from fdai_operator_service.alert_quality_auth import _REQUEST_ROLES, _require_scope, _revalidate
from fdai_operator_service.alert_quality_boundary import (
    _body,
    _query_scope,
    _RequestError,
    _response,
    _unavailable,
)
from fdai_operator_service.alert_quality_config import AlertQualityDependencies
from fdai_operator_service.alert_quality_contracts import (
    AlertAssessmentBody,
    AlertProposalBody,
    AlertQualityResponse,
    AlertQualityScopesResponse,
    Operation,
    UnavailableReason,
)
from fdai_operator_service.alert_quality_records import (
    AlertQualitySnapshot,
    AlertQualityUnavailableError,
    alert_quality_requester_ref,
)
from fdai_operator_service.alert_quality_sources import (
    _current,
    _effective_enabled,
    _producer_is_ready,
    _read_preference,
    _read_snapshot,
)
from fdai_operator_service.auth import AuthenticationError, AuthorizationError
from fdai_operator_service.families.operations.contracts import EventProposal

_IDEMPOTENCY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")
_LOGGER = logging.getLogger("fdai_operator_service.alert_quality")


def _get_scopes(
    request: Request, dependencies: AlertQualityDependencies, principal: OperatorPrincipal
) -> Response:
    """Return only the authenticated subject's opaque configured scopes."""
    if request.url.query:
        raise _RequestError(400, "invalid_request")
    scopes = tuple(sorted(dependencies.principal_scopes.get(principal.subject_id, frozenset())))
    if any(principal.subject_id.casefold() in scope.casefold() for scope in scopes):
        raise AlertQualityUnavailableError("alert quality scope disclosure is unavailable")
    return _response(AlertQualityScopesResponse(scope_refs=scopes))


async def _get(
    request: Request, dependencies: AlertQualityDependencies, principal: OperatorPrincipal
) -> Response:
    """Project retained evidence and current requestability, then revalidate access."""
    scope = _query_scope(request)
    _require_scope(dependencies, principal, scope)
    enabled = dependencies.enabled and dependencies.preference_store is None
    try:
        snapshot = await _read_snapshot(dependencies, principal.subject_id, scope)
        ready = await _producer_is_ready(dependencies)
        preference, readable = await _read_preference(dependencies, scope)
        enabled = _effective_enabled(dependencies, preference, readable)
        now = dependencies.clock()
        if snapshot is not None:
            current = _current(snapshot.assessment, now)
            if snapshot.assessment.observed_at > now:
                return _response(
                    _unavailable(dependencies, "assessment_not_current", enabled=enabled)
                )
            reason: UnavailableReason | None = None if current else "assessment_not_current"
        else:
            if not ready:
                return _response(_unavailable(dependencies, "assessment_missing", enabled=enabled))
            reason = None
        return _response(
            AlertQualityResponse(
                source="alert-noise-governance",
                available=True,
                enabled=enabled,
                requestable=(
                    ready
                    and enabled
                    and dependencies.source is not None
                    and dependencies.proposal_writer is not None
                    and principal.principal_kind is OperatorPrincipalKind.HUMAN
                    and not principal.roles.isdisjoint(_REQUEST_ROLES)
                ),
                authority="shadow",
                unavailable_reason=reason,
                assessment=None if snapshot is None else snapshot.assessment,
                plans=() if snapshot is None else snapshot.plans,
            )
        )
    except (AuthenticationError, AuthorizationError):
        raise
    except Exception as exc:  # noqa: BLE001 - no fallback evidence or dependency details
        _LOGGER.warning(
            "alert quality source unavailable",
            extra={
                "event": "alert_quality.source_unavailable",
                "failure_type": type(exc).__name__,
            },
        )
        return _response(_unavailable(dependencies, "source_unavailable", enabled=enabled))
    finally:
        # Includes the readiness await and the first-report path.
        _revalidate(request, dependencies, principal, scope, write=False)


async def _post(
    request: Request,
    dependencies: AlertQualityDependencies,
    principal: OperatorPrincipal,
    operation: Operation,
) -> Response:
    """Enqueue an exact, currently authorized request without granting execution authority."""
    body = await _body(
        request, AlertProposalBody if operation == "alert_noise.propose" else AlertAssessmentBody
    )
    _require_scope(dependencies, principal, body.scope_ref)
    try:
        _revalidate(request, dependencies, principal, body.scope_ref, write=True)
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1 or _IDEMPOTENCY.fullmatch(keys[0]) is None:
            raise _RequestError(400, "invalid_request")
        writer = dependencies.proposal_writer
        if dependencies.source is None or writer is None or dependencies.producer_ready is None:
            raise _RequestError(503, "unavailable")
        if not await _producer_is_ready(dependencies):
            raise _RequestError(503, "unavailable")
        snapshot = None
        if isinstance(body, AlertProposalBody):
            snapshot = await _read_snapshot(dependencies, principal.subject_id, body.scope_ref)
            _require_current_evidence(snapshot, body, dependencies.clock())
            if not await _producer_is_ready(dependencies):
                raise _RequestError(503, "unavailable")
        preference, readable = await _read_preference(dependencies, body.scope_ref)
        enabled = _effective_enabled(dependencies, preference, readable)
        if not enabled:
            raise _RequestError(503, "unavailable")
        # Namespace the existing globally keyed outbox by principal, NOT body content.
        # Reusing a key with another scope, operation or treatment therefore conflicts.
        raw_key = json.dumps(
            ["operator-alert-quality-request-v1", principal.subject_id, keys[0]],
            separators=(",", ":"),
        )
        request_key = "alert-noise:" + hashlib.sha256(raw_key.encode()).hexdigest()
        proposal = EventProposal(
            operation=operation,
            principal_id=principal.subject_id,
            idempotency_key=request_key,
            correlation_id=request_key,
            payload={
                **body.model_dump(mode="json"),
                "request_idempotency_key": keys[0],
                "requester_ref": alert_quality_requester_ref(principal.subject_id, body.scope_ref),
            },
        )
        # No await may separate the final identity/scope/time checks from enqueue.
        _revalidate(request, dependencies, principal, body.scope_ref, write=True)
        if dependencies.source is None or dependencies.proposal_writer is not writer:
            raise _RequestError(503, "unavailable")
        if isinstance(body, AlertProposalBody):
            _require_current_evidence(snapshot, body, dependencies.clock())
        receipt = await writer.propose(proposal)
        _revalidate(request, dependencies, principal, body.scope_ref, write=True)
        if receipt.durably_queued is not True or receipt.correlation_id != request_key:
            raise AlertQualityUnavailableError("durable alert quality acceptance is unavailable")
        response = _response(
            _unavailable(
                dependencies,
                "assessment_pending" if operation == "alert_noise.assess" else "proposal_pending",
                enabled=enabled,
            ),
            status=202,
        )
        response.headers["X-Correlation-ID"] = request_key
        return response
    finally:
        _revalidate(request, dependencies, principal, body.scope_ref, write=True)


def _require_current_evidence(
    snapshot: AlertQualitySnapshot | None, body: AlertProposalBody, now: datetime
) -> None:
    """Bind a proposed treatment to the exact unexpired retained evidence."""
    if (
        snapshot is None
        or not _current(snapshot.assessment, now)
        or snapshot.assessment.evidence_digest != body.evidence_digest
    ):
        raise _RequestError(409, "evidence_not_current")
