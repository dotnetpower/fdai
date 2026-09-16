"""Requester-only Console consent for sending one report-line approval request."""

from __future__ import annotations

import re
from typing import Final

from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    ReportLineContactOutbox,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
)
from fdai_service_contracts import (
    OperatorPrincipalKind,
    build_report_line_contact_command,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

_MAX_BODY_BYTES: Final = 1_024
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")


def make_report_line_contact_route(
    *,
    authorize: AuthorizePrincipal,
    outbox: ReportLineContactOutbox | None,
) -> tuple[Route, ...]:
    """Build a consent route that cannot approve or execute the parked action."""

    async def list_report_line_contacts(request: Request) -> Response:
        if outbox is None:
            return error_response(503, "report-line contact outbox is not configured")
        principal = await authorize(request)
        if principal.principal_kind is not OperatorPrincipalKind.HUMAN:
            return error_response(403, "report-line contact requests require a human")
        try:
            contexts = await outbox.list_report_line_contact_contexts(
                requester_ref=principal.oid.strip().casefold(),
                limit=100,
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(
            {
                "items": [
                    {
                        "approval_id": item.approval_id,
                        "consent_id": item.consent_id,
                        "consent_revision": item.consent_revision,
                        "action_type": item.action_type,
                        "target_ref": item.target_ref,
                        "route_subjects": list(item.route_subjects),
                        "expires_at": item.expires_at.isoformat(),
                        "approval_authority": False,
                        "execution_authority": False,
                    }
                    for item in contexts
                ],
                "total": len(contexts),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def post_report_line_contact(request: Request) -> Response:
        if outbox is None:
            return error_response(503, "report-line contact outbox is not configured")
        principal = await authorize(request)
        if principal.principal_kind is not OperatorPrincipalKind.HUMAN:
            return error_response(403, "report-line contact consent requires a human")
        approval_id = str(request.path_params["approval_id"])
        if not approval_id or len(approval_id) > 200:
            return error_response(400, "approval_id is invalid")
        try:
            context = await outbox.get_report_line_contact_context(approval_id)
        except IamFamilyError as exc:
            return family_error(exc)
        if context is None:
            return error_response(404, "pending report-line contact request was not found")
        if principal.oid.strip().casefold() != context.requester_ref:
            return error_response(403, "only the requester may decide report-line contact")
        request_key = request.headers.get("idempotency-key", "").strip()
        if _IDEMPOTENCY_KEY.fullmatch(request_key) is None:
            return error_response(400, "valid Idempotency-Key header is required")
        body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
        if set(body) != {"consent", "expected_revision"}:
            return error_response(
                400,
                "report-line contact body MUST contain consent and expected_revision",
            )
        consent = body.get("consent")
        expected_revision = body.get("expected_revision")
        if not isinstance(consent, bool):
            return error_response(400, "consent MUST be boolean")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
            or expected_revision != context.consent_revision
        ):
            return error_response(409, "report-line contact consent revision is stale")
        command = build_report_line_contact_command(
            approval_id=approval_id,
            requester_ref=principal.oid,
            consent=consent,
            expected_consent_revision=expected_revision,
            requested_at=context.consent_requested_at,
            idempotency_key=request_key,
        )
        try:
            await outbox.enqueue_report_line_contact(command)
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(
            {
                "approval_id": approval_id,
                "status": "contact_queued",
                "consent": consent,
                "consent_id": context.consent_id,
                "execution_authority": False,
                "approval_authority": False,
            },
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )

    return (
        Route(
            "/hil/report-line-contact-requests",
            list_report_line_contacts,
            methods=["GET"],
            name="list_report_line_contacts",
        ),
        Route(
            "/hil/{approval_id}/report-line-contact",
            post_report_line_contact,
            methods=["POST"],
            name="post_report_line_contact",
        ),
    )


__all__ = ["make_report_line_contact_route"]
