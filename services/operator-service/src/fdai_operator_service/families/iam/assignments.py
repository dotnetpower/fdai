"""Owner-only human assignment observation and request routes."""

from __future__ import annotations

from typing import Any, Final

from fdai_service_contracts import OperatorRole
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import (
    AssignmentCaseQuery,
    AssignmentCreateCommand,
    AssignmentRequestOutbox,
    AssignmentTransitionCommand,
    AuthorizePrincipal,
    HumanIdentityDirectory,
    IamPrincipal,
)
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
    require_revision,
    require_string,
)

_MAX_BODY_BYTES: Final = 32_000
_MAX_DUTY_BINDINGS: Final = 30
_MAX_GOAL_REFS: Final = 20


def make_assignment_routes(
    *,
    outbox: AssignmentRequestOutbox | None,
    authorize: AuthorizePrincipal,
    directory: HumanIdentityDirectory | None,
    identity_provider: str = "entra",
) -> tuple[Route, ...]:
    """Build assignment routes that persist cases but never apply IAM or ownership."""

    async def list_cases(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_owner(principal)
        if denied is not None:
            return denied
        if outbox is None:
            return error_response(503, "assignment request outbox is not configured")
        try:
            limit, cursor = _pagination(request)
            cases, total = await outbox.list_case_page(
                AssignmentCaseQuery(principal=principal, limit=limit, offset=cursor)
            )
        except (ValueError, IamFamilyError) as exc:
            if isinstance(exc, IamFamilyError):
                return family_error(exc)
            return error_response(400, str(exc))
        next_cursor = cursor + len(cases) if cursor + len(cases) < total else None
        return JSONResponse(
            {
                "items": [dict(item) for item in cases],
                "total": total,
                "next_cursor": next_cursor,
                "authority": "observation_only",
            }
        )

    async def get_case(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_owner(principal)
        if denied is not None:
            return denied
        if outbox is None:
            return error_response(503, "assignment request outbox is not configured")
        try:
            case = await outbox.get_case(str(request.path_params["case_id"]))
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse({**dict(case), "authority": "observation_only"})

    async def create_case(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_owner(principal)
        if denied is not None:
            return denied
        unavailable = _dependencies(outbox=outbox, directory=directory)
        if unavailable is not None:
            return unavailable
        if outbox is None or directory is None:
            return error_response(503, "assignment dependencies are unavailable")
        try:
            body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
            command = _create_command(
                body,
                principal=principal,
                identity_provider=identity_provider,
            )
            identity = await _exact_identity(
                directory,
                command.subject_id,
                identity_provider=identity_provider,
            )
            if identity is None:
                return error_response(400, "target identity was not found")
            created = await outbox.create_case(command)
        except IamFamilyError as exc:
            return family_error(exc)
        except ValueError as exc:
            return error_response(400, str(exc))
        except Exception:  # noqa: BLE001 - directory details are not caller-safe.
            return error_response(503, "human identity directory is unavailable")
        return JSONResponse(
            {**dict(created), "authority": "observation_only"},
            status_code=201,
        )

    async def submit_case(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_owner(principal)
        if denied is not None:
            return denied
        unavailable = _dependencies(outbox=outbox, directory=directory)
        if unavailable is not None:
            return unavailable
        if outbox is None or directory is None:
            return error_response(503, "assignment dependencies are unavailable")
        try:
            body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
            case_id = str(request.path_params["case_id"])
            current = await outbox.get_case(case_id)
            subject_id = _case_subject_id(current)
            identity = await _exact_identity(
                directory,
                subject_id,
                identity_provider=identity_provider,
            )
            if identity is None:
                return error_response(400, "target identity was not found")
            submitted = await outbox.submit_for_review(
                AssignmentTransitionCommand(
                    principal=principal,
                    case_id=case_id,
                    expected_revision=require_revision(body, positive=True),
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        except ValueError as exc:
            return error_response(400, str(exc))
        except Exception:  # noqa: BLE001 - directory details are not caller-safe.
            return error_response(503, "human identity directory is unavailable")
        return JSONResponse({**dict(submitted), "authority": "observation_only"})

    async def review_case(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_owner(principal)
        if denied is not None:
            return denied
        if outbox is None:
            return error_response(503, "assignment request outbox is not configured")
        try:
            body = await read_json_object(request, maximum=_MAX_BODY_BYTES)
            reviewed = await outbox.review(
                AssignmentTransitionCommand(
                    principal=principal,
                    case_id=str(request.path_params["case_id"]),
                    expected_revision=require_revision(body, positive=True),
                    decision=require_string(body, "decision"),
                )
            )
        except IamFamilyError as exc:
            return family_error(exc)
        return JSONResponse({**dict(reviewed), "authority": "observation_only"})

    async def list_assignments(request: Request) -> Response:
        principal = await authorize(request)
        denied = _require_owner(principal)
        if denied is not None:
            return denied
        if outbox is None:
            return error_response(503, "assignment request outbox is not configured")
        try:
            limit, cursor = _pagination(request)
            payload = await outbox.assignment_projection(
                AssignmentCaseQuery(principal=principal, limit=limit, offset=cursor)
            )
        except (ValueError, IamFamilyError) as exc:
            if isinstance(exc, IamFamilyError):
                return family_error(exc)
            return error_response(400, str(exc))
        return JSONResponse({**dict(payload), "authority": "observation_only"})

    return (
        Route("/iam/assignments", list_assignments, methods=["GET"]),
        Route("/iam/assignment-cases", list_cases, methods=["GET"]),
        Route("/iam/assignment-cases", create_case, methods=["POST"]),
        Route("/iam/assignment-cases/{case_id:str}", get_case, methods=["GET"]),
        Route(
            "/iam/assignment-cases/{case_id:str}/submit",
            submit_case,
            methods=["POST"],
        ),
        Route(
            "/iam/assignment-cases/{case_id:str}/review",
            review_case,
            methods=["POST"],
        ),
    )


def _require_owner(principal: IamPrincipal) -> Response | None:
    if not has_capability(principal.roles, IamCapability.MANAGE_GROUP_MEMBERSHIP):
        return error_response(403, "manage-group-membership capability is required")
    return None


def _dependencies(
    *, outbox: AssignmentRequestOutbox | None, directory: HumanIdentityDirectory | None
) -> Response | None:
    if outbox is None:
        return error_response(503, "assignment request outbox is not configured")
    if directory is None:
        return error_response(501, "human identity directory is not configured")
    return None


def _pagination(request: Request) -> tuple[int, int]:
    limit = int(request.query_params.get("limit", "50"))
    cursor = int(request.query_params.get("cursor", "0"))
    if not 1 <= limit <= 100:
        raise ValueError("limit MUST be between 1 and 100")
    if not 0 <= cursor <= 10_000:
        raise ValueError("cursor MUST be between 0 and 10000")
    return limit, cursor


def _create_command(
    body: dict[str, Any], *, principal: IamPrincipal, identity_provider: str
) -> AssignmentCreateCommand:
    allowed = {
        "idempotency_key",
        "subject",
        "requested_role",
        "duty_bindings",
        "goal_refs",
        "justification",
    }
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ValueError(f"unknown assignment fields: {', '.join(unknown)}")
    subject = body.get("subject")
    if not isinstance(subject, dict):
        raise ValueError("subject MUST be an object")
    provider = require_string(subject, "provider")
    if provider.casefold() != identity_provider.casefold():
        raise ValueError("subject provider does not match the configured provider")
    duties = body.get("duty_bindings")
    goals = body.get("goal_refs")
    if not isinstance(duties, list) or not all(isinstance(item, dict) for item in duties):
        raise ValueError("duty_bindings MUST be an object list")
    if len(duties) > _MAX_DUTY_BINDINGS:
        raise ValueError(f"duty_bindings MUST contain at most {_MAX_DUTY_BINDINGS} items")
    if not isinstance(goals, list) or not all(isinstance(item, str) for item in goals):
        raise ValueError("goal_refs MUST be a string list")
    if len(goals) > _MAX_GOAL_REFS:
        raise ValueError(f"goal_refs MUST contain at most {_MAX_GOAL_REFS} items")
    role = OperatorRole(require_string(body, "requested_role"))
    if role is OperatorRole.BREAK_GLASS:
        raise ValueError("BreakGlass is not available for routine assignment")
    return AssignmentCreateCommand(
        principal=principal,
        idempotency_key=require_string(body, "idempotency_key"),
        subject_provider=provider,
        subject_id=require_string(subject, "subject_id"),
        requested_role=role,
        duty_bindings=tuple(duties),
        goal_refs=tuple(goals),
        justification=require_string(body, "justification"),
    )


async def _exact_identity(
    directory: HumanIdentityDirectory,
    subject_id: str,
    *,
    identity_provider: str,
) -> object | None:
    identity = await directory.get_by_subject_id(subject_id)
    if identity is None:
        return None
    if identity.provider.casefold() != identity_provider.casefold():
        raise ValueError("target identity provider does not match the configured provider")
    if not identity.active:
        raise ValueError("target identity is inactive")
    return identity


def _case_subject_id(case: Any) -> str:
    try:
        subject_id = case["intent"]["subject"]["subject_id"]
    except (KeyError, TypeError) as exc:
        raise ValueError("assignment case subject identity is unavailable") from exc
    if not isinstance(subject_id, str):
        raise ValueError("assignment case subject identity is invalid")
    return subject_id


__all__ = ["make_assignment_routes"]
