"""Human report-line observation and no-authority command routes."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    AuthorizePrincipal,
    IamPrincipal,
    ReportingLineCaseQuery,
    ReportingLineCreateCommand,
    ReportingLineOutbox,
    ReportingLineTransitionCommand,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
    require_revision,
    require_string,
)
from fdai_service_contracts import OperatorRole
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

_MAX_BODY_BYTES: Final = 16_000


def make_reporting_line_routes(
    *,
    outbox: ReportingLineOutbox | None,
    authorize: AuthorizePrincipal,
) -> tuple[Route, ...]:
    """Build bounded report-line routes that never grant approval authority."""

    async def list_cases(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "reporting-line outbox is not configured")
        try:
            limit, offset = _pagination(request)
            cases, total = await outbox.list_report_line_case_page(
                ReportingLineCaseQuery(principal=principal, limit=limit, offset=offset)
            )
        except (ValueError, IamFamilyError) as exc:
            return (
                family_error(exc)
                if isinstance(exc, IamFamilyError)
                else error_response(400, str(exc))
            )
        return JSONResponse(
            {
                "items": [dict(item) for item in cases],
                "total": total,
                "next_cursor": offset + len(cases) if offset + len(cases) < total else None,
                "authority": "observation_only",
            },
            headers={"Cache-Control": "no-store"},
        )

    async def current_graph(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "reporting-line outbox is not configured")
        try:
            limit, offset = _pagination(request)
            projection = await outbox.report_line_projection(
                ReportingLineCaseQuery(principal=principal, limit=limit, offset=offset)
            )
        except (ValueError, IamFamilyError) as exc:
            return (
                family_error(exc)
                if isinstance(exc, IamFamilyError)
                else error_response(400, str(exc))
            )
        return JSONResponse(
            {**dict(projection), "authority": "observation_only"},
            headers={"Cache-Control": "no-store"},
        )

    async def get_case(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "reporting-line outbox is not configured")
        try:
            case = await outbox.get_report_line_case(
                str(request.path_params["case_id"]),
                principal=principal,
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse(
            {**dict(case), "authority": "observation_only"},
            headers={"Cache-Control": "no-store"},
        )

    async def create_case(request: Request) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.AUTHOR_DRAFT_PR):
            return error_response(403, "reporting-line import requires Contributor or higher")
        if outbox is None:
            return error_response(503, "reporting-line outbox is not configured")
        try:
            body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
            command = ReportingLineCreateCommand(
                principal=principal,
                idempotency_key=require_string(body, "idempotency_key"),
                upload_id=require_string(body, "upload_id"),
                candidate_id=require_string(body, "candidate_id"),
                effective_from=_optional_timestamp(body.get("effective_from")),
                effective_until=_optional_timestamp(body.get("effective_until")),
                supersedes_case_id=_optional_string(body.get("supersedes_case_id")),
            )
            created = await outbox.create_report_line_case(command)
        except IamFamilyError as exc:
            return family_error(exc)
        except ValueError as exc:
            return error_response(400, str(exc))
        return JSONResponse(
            {**dict(created), "authority": "observation_only"},
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )

    async def confirm_case(request: Request) -> Response:
        principal = await authorize(request)
        if outbox is None:
            return error_response(503, "reporting-line outbox is not configured")
        try:
            body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
            confirmed = await outbox.confirm_report_line(
                _transition(request, body, principal=principal)
            )
        except IamFamilyError as exc:
            return family_error(exc)
        except ValueError as exc:
            return error_response(400, str(exc))
        return JSONResponse(
            {**dict(confirmed), "authority": "observation_only"},
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )

    async def review_case(request: Request) -> Response:
        principal = await authorize(request)
        if OperatorRole.OWNER not in principal.roles:
            return error_response(403, "reporting-line review requires Owner")
        if outbox is None:
            return error_response(503, "reporting-line outbox is not configured")
        try:
            body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
            reviewed = await outbox.review_report_line(
                _transition(request, body, principal=principal)
            )
        except IamFamilyError as exc:
            return family_error(exc)
        except ValueError as exc:
            return error_response(400, str(exc))
        return JSONResponse(
            {**dict(reviewed), "authority": "observation_only"},
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )

    return (
        Route("/handover/reporting-lines", current_graph, methods=["GET"]),
        Route("/handover/reporting-line-cases", list_cases, methods=["GET"]),
        Route("/handover/reporting-line-cases", create_case, methods=["POST"]),
        Route(
            "/handover/reporting-line-cases/{case_id:str}",
            get_case,
            methods=["GET"],
        ),
        Route(
            "/handover/reporting-line-cases/{case_id:str}/confirm",
            confirm_case,
            methods=["POST"],
        ),
        Route(
            "/handover/reporting-line-cases/{case_id:str}/review",
            review_case,
            methods=["POST"],
        ),
    )


def _transition(
    request: Request,
    body: dict[str, object],
    *,
    principal: IamPrincipal,
) -> ReportingLineTransitionCommand:
    allowed = {"expected_revision", "decision", "edge_digest"}
    if set(body) != allowed:
        raise ValueError("reporting-line transition body has unexpected fields")
    return ReportingLineTransitionCommand(
        principal=principal,
        case_id=str(request.path_params["case_id"]),
        expected_revision=require_revision(body, positive=True),
        decision=require_string(body, "decision"),
        edge_digest=require_string(body, "edge_digest"),
    )


def _pagination(request: Request) -> tuple[int, int]:
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("cursor", "0"))
    except ValueError as exc:
        raise ValueError("reporting-line pagination MUST be integers") from exc
    if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
        raise ValueError("reporting-line pagination is outside its bounds")
    return limit, offset


def _optional_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("reporting-line effective time MUST be timestamp text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reporting-line effective time MUST be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("reporting-line effective time MUST be timezone-aware")
    return parsed


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("reporting-line optional reference MUST be exact")
    return value


__all__ = ["make_reporting_line_routes"]
