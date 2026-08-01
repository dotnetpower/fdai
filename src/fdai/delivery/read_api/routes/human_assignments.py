"""Owner-only observation API for human-agent assignment cases."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from fdai.core.human_assignment import (
    AssignmentCase,
    AssignmentCaseService,
    AssignmentConflictError,
    AssignmentIntent,
    AssignmentModelError,
    AssignmentPermissionError,
    AssignmentServiceError,
    AssignmentTransitionError,
    DutyBinding,
    ProviderSubject,
    ReviewDecision,
    StaleAssignmentRevisionError,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, Role, has_capability
from fdai.core.stewardship.coverage import build_coverage_report
from fdai.core.stewardship.model import Duty, StewardKind, StewardshipMap
from fdai.shared.providers.human_identity import HumanIdentityDirectory, IdentityRosterEntry

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]
_MAX_BODY_BYTES: Final[int] = 32_000
_MAX_DUTY_BINDINGS: Final[int] = 30
_MAX_GOAL_REFS: Final[int] = 20
_MAX_PROJECTION_CASES: Final[int] = 500


def append_human_assignment_routes(
    routes: list[BaseRoute],
    *,
    service: AssignmentCaseService,
    authorize: AuthorizePrincipal,
    directory: HumanIdentityDirectory | None,
    stewardship_map: StewardshipMap | None,
    identity_provider: str = "entra",
    role_group_ids: Mapping[str, str] | None = None,
) -> None:
    """Register assignment routes without binding any IAM mutation provider."""

    async def list_cases(request: Request) -> Response:
        principal = await authorize(request)
        try:
            _require_owner(principal)
            limit, cursor = _pagination(request)
            cases, total = await service.list_case_page(
                principal=principal,
                limit=limit,
                offset=cursor,
            )
        except AssignmentPermissionError as exc:
            return _error(403, str(exc))
        except (AssignmentServiceError, ValueError) as exc:
            return _error(400, str(exc))
        next_cursor = cursor + len(cases) if cursor + len(cases) < total else None
        return JSONResponse(
            {
                "items": [case.to_dict() for case in cases],
                "total": total,
                "next_cursor": next_cursor,
                "authority": "observation_only",
            }
        )

    async def get_case(request: Request) -> Response:
        principal = await authorize(request)
        try:
            _require_owner(principal)
            case = await service.get_case(request.path_params["case_id"])
        except AssignmentPermissionError as exc:
            return _error(403, str(exc))
        except AssignmentServiceError as exc:
            return _error(404, str(exc))
        return JSONResponse({**case.to_dict(), "authority": "observation_only"})

    async def create_case(request: Request) -> Response:
        principal = await authorize(request)
        try:
            _require_owner(principal)
            if directory is None:
                return _error(501, "human identity directory is not configured")
            body = await _read_json_object(request)
            intent = _intent(body, principal=principal, identity_provider=identity_provider)
            identity = await _exact_active_identity(
                directory,
                intent.subject.subject_id,
                identity_provider=identity_provider,
            )
            if identity is None:
                raise AssignmentModelError("target identity was not found")
            created = await service.create_case(principal=principal, intent=intent)
        except AssignmentPermissionError as exc:
            return _error(403, str(exc))
        except AssignmentConflictError as exc:
            return _error(409, str(exc))
        except _DirectoryUnavailableError:
            return _error(503, "human identity directory is unavailable")
        except (AssignmentModelError, AssignmentServiceError, ValueError) as exc:
            return _error(400, str(exc))
        return JSONResponse(
            {**created.to_dict(), "authority": "observation_only"},
            status_code=201,
        )

    async def submit_case(request: Request) -> Response:
        principal = await authorize(request)
        try:
            _require_owner(principal)
            if directory is None:
                return _error(501, "human identity directory is not configured")
            body = await _read_json_object(request)
            current = await service.get_case(request.path_params["case_id"])
            identity = await _exact_active_identity(
                directory,
                current.intent.subject.subject_id,
                identity_provider=identity_provider,
            )
            if identity is None:
                raise AssignmentModelError("target identity was not found")
            submitted = await service.submit_for_review(
                principal=principal,
                case_id=request.path_params["case_id"],
                expected_revision=_integer(body, "expected_revision"),
            )
        except AssignmentPermissionError as exc:
            return _error(403, str(exc))
        except (StaleAssignmentRevisionError, AssignmentConflictError) as exc:
            return _error(409, str(exc))
        except _DirectoryUnavailableError:
            return _error(503, "human identity directory is unavailable")
        except (AssignmentTransitionError, AssignmentServiceError, ValueError) as exc:
            return _error(400, str(exc))
        return JSONResponse({**submitted.to_dict(), "authority": "observation_only"})

    async def review_case(request: Request) -> Response:
        principal = await authorize(request)
        try:
            _require_owner(principal)
            body = await _read_json_object(request)
            reviewed = await service.review(
                principal=principal,
                case_id=request.path_params["case_id"],
                expected_revision=_integer(body, "expected_revision"),
                decision=ReviewDecision(_string(body, "decision")),
            )
        except AssignmentPermissionError as exc:
            return _error(403, str(exc))
        except (StaleAssignmentRevisionError, AssignmentConflictError) as exc:
            return _error(409, str(exc))
        except (AssignmentTransitionError, AssignmentServiceError, ValueError) as exc:
            return _error(400, str(exc))
        return JSONResponse({**reviewed.to_dict(), "authority": "observation_only"})

    async def list_assignments(request: Request) -> Response:
        principal = await authorize(request)
        try:
            _require_owner(principal)
            limit, cursor = _pagination(request)
            payload = await _assignment_projection(
                service=service,
                principal=principal,
                directory=directory,
                stewardship_map=stewardship_map,
                identity_provider=identity_provider,
                role_group_ids=role_group_ids or {},
                limit=limit,
                cursor=cursor,
            )
        except AssignmentPermissionError as exc:
            return _error(403, str(exc))
        except _DirectoryUnavailableError:
            return _error(503, "human identity directory is unavailable")
        except (AssignmentServiceError, ValueError) as exc:
            return _error(400, str(exc))
        return JSONResponse(payload)

    routes.extend(
        (
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
    )


async def _assignment_projection(
    *,
    service: AssignmentCaseService,
    principal: Principal,
    directory: HumanIdentityDirectory | None,
    stewardship_map: StewardshipMap | None,
    identity_provider: str,
    role_group_ids: Mapping[str, str],
    limit: int,
    cursor: int,
) -> dict[str, object]:
    first_case_page, case_total = await service.list_case_page(
        principal=principal,
        limit=100,
        offset=0,
    )
    all_cases = list(first_case_page)
    while len(all_cases) < min(case_total, _MAX_PROJECTION_CASES):
        assignment_case_page, _ = await service.list_case_page(
            principal=principal,
            limit=min(100, _MAX_PROJECTION_CASES - len(all_cases)),
            offset=len(all_cases),
        )
        if not assignment_case_page:
            break
        all_cases.extend(assignment_case_page)

    roster: tuple[IdentityRosterEntry, ...] = ()
    directory_availability = "not_configured"
    if directory is not None and role_group_ids:
        try:
            roster = await directory.list_role_roster(role_group_ids, limit=500)
        except Exception as exc:  # noqa: BLE001 - provider failures fail closed
            raise _DirectoryUnavailableError from exc
        directory_availability = "available"

    people = {
        (item.provider.casefold(), item.subject_id): item
        for item in roster
        if item.principal_type == "person"
    }
    subject_keys = set(people)
    subject_keys.update(
        (case.intent.subject.provider.casefold(), case.intent.subject.subject_id)
        for case in all_cases
    )
    if stewardship_map is not None:
        subject_keys.update(
            (identity_provider.casefold(), subject.id)
            for agent in stewardship_map.agents.values()
            for subject in agent.stewards
            if subject.kind is StewardKind.USER
        )

    records = [
        _project_subject(
            key=key,
            identity=people.get(key),
            cases=tuple(
                case
                for case in all_cases
                if (case.intent.subject.provider.casefold(), case.intent.subject.subject_id) == key
            ),
            stewardship_map=stewardship_map,
        )
        for key in sorted(subject_keys)
    ]
    projected_subject_page = records[cursor : cursor + limit]
    next_cursor = (
        cursor + len(projected_subject_page)
        if cursor + len(projected_subject_page) < len(records)
        else None
    )
    return {
        "items": projected_subject_page,
        "total": len(records),
        "next_cursor": next_cursor,
        "authority": "observation_only",
        "directory_availability": directory_availability,
        "case_projection_truncated": case_total > _MAX_PROJECTION_CASES,
    }


def _project_subject(
    *,
    key: tuple[str, str],
    identity: IdentityRosterEntry | None,
    cases: tuple[AssignmentCase, ...],
    stewardship_map: StewardshipMap | None,
) -> dict[str, object]:
    provider, subject_id = key
    latest_case = cases[0] if cases else None
    duties: list[dict[str, object]] = []
    coverage: list[dict[str, object]] = []
    report = build_coverage_report(stewardship_map) if stewardship_map is not None else None
    if stewardship_map is not None and report is not None:
        for agent_name, agent in stewardship_map.agents.items():
            matching = tuple(subject for subject in agent.stewards if subject.id == subject_id)
            duties.extend(
                {
                    "agent_name": agent_name,
                    "duty": subject.duty.value if subject.duty is not None else None,
                    "responsibility": subject.responsibility.value,
                    "source": "stewardship",
                }
                for subject in matching
            )
            if matching:
                coverage.append(
                    {
                        "agent_name": agent_name,
                        "primary_count": len(agent.primary),
                        "backup_or_escalation_count": len(agent.backup) + len(agent.escalation),
                        "finding_codes": sorted(
                            finding.code
                            for finding in report.findings
                            if finding.agent == agent_name
                        ),
                    }
                )

    return {
        "subject": {
            "provider": provider,
            "subject_id": subject_id,
            "display_name": identity.display_name if identity is not None else None,
            "username": identity.username if identity is not None else None,
            "active": identity.active if identity is not None else None,
        },
        "roles": list(identity.roles) if identity is not None else None,
        "duties": duties,
        "coverage": coverage or None,
        "case": latest_case.to_dict() if latest_case is not None else None,
        "handover": {
            "goal_refs": list(latest_case.intent.goal_refs) if latest_case is not None else [],
            "state": None,
            "evidence_refs": None,
            "availability": "not_connected",
        },
    }


async def _exact_active_identity(
    directory: HumanIdentityDirectory,
    subject_id: str,
    *,
    identity_provider: str,
) -> object | None:
    try:
        identity = await directory.get_by_subject_id(subject_id)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider failures fail closed
        raise _DirectoryUnavailableError from exc
    if identity is None:
        return None
    if identity.provider.casefold() != identity_provider.casefold():
        raise AssignmentModelError(
            "target identity provider does not match the configured provider"
        )
    if not identity.active:
        raise AssignmentModelError("target identity is inactive")
    return identity


def _intent(
    body: dict[str, Any],
    *,
    principal: Principal,
    identity_provider: str,
) -> AssignmentIntent:
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
        raise AssignmentModelError(f"unknown assignment fields: {', '.join(unknown)}")
    subject = _mapping(body, "subject")
    provider = _string(subject, "provider")
    if provider.casefold() != identity_provider.casefold():
        raise AssignmentModelError("subject provider does not match the configured provider")
    raw_duties = _object_list(body, "duty_bindings", maximum=_MAX_DUTY_BINDINGS)
    raw_goals = _string_list(body, "goal_refs", maximum=_MAX_GOAL_REFS)
    return AssignmentIntent(
        idempotency_key=_string(body, "idempotency_key"),
        subject=ProviderSubject(provider=provider, subject_id=_string(subject, "subject_id")),
        requested_role=Role(_string(body, "requested_role")),
        duty_bindings=tuple(
            DutyBinding(
                agent_name=_string(item, "agent_name"),
                duty=Duty(_string(item, "duty")),
                scope_ref=_string(item, "scope_ref"),
            )
            for item in raw_duties
        ),
        goal_refs=tuple(raw_goals),
        requester_ref=principal.oid,
        justification=_string(body, "justification"),
    )


def _require_owner(principal: Principal) -> None:
    if not has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP):
        raise AssignmentPermissionError("manage-group-membership capability is required")


def _pagination(request: Request) -> tuple[int, int]:
    limit = int(request.query_params.get("limit", "50"))
    cursor = int(request.query_params.get("cursor", "0"))
    if limit < 1 or limit > 100:
        raise ValueError("limit MUST be between 1 and 100")
    if cursor < 0 or cursor > 10_000:
        raise ValueError("cursor MUST be between 0 and 10000")
    return limit, cursor


async def _read_json_object(request: Request) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            parsed_content_length = int(content_length)
        except ValueError as exc:
            raise AssignmentServiceError("content-length MUST be an integer") from exc
        if parsed_content_length > _MAX_BODY_BYTES:
            raise AssignmentServiceError(f"request body MUST be at most {_MAX_BODY_BYTES} bytes")
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise AssignmentServiceError(f"request body MUST be at most {_MAX_BODY_BYTES} bytes")
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AssignmentServiceError("request body MUST be a JSON object") from exc
    if not isinstance(value, dict):
        raise AssignmentServiceError("request body MUST be a JSON object")
    return value


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise AssignmentModelError(f"{key} MUST be an object")
    return item


def _object_list(value: dict[str, Any], key: str, *, maximum: int) -> tuple[dict[str, Any], ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise AssignmentModelError(f"{key} MUST be an object list")
    if len(items) > maximum:
        raise AssignmentModelError(f"{key} MUST contain at most {maximum} items")
    return tuple(items)


def _string_list(value: dict[str, Any], key: str, *, maximum: int) -> tuple[str, ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise AssignmentModelError(f"{key} MUST be a string list")
    if len(items) > maximum:
        raise AssignmentModelError(f"{key} MUST contain at most {maximum} items")
    return tuple(items)


def _string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise AssignmentModelError(f"{key} MUST be a string")
    return item


def _integer(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int):
        raise AssignmentModelError(f"{key} MUST be an integer")
    return item


class _DirectoryUnavailableError(RuntimeError):
    """Raised after redacting an identity-provider failure."""


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"status": status, "message": message}}, status_code=status)


__all__ = ["append_human_assignment_routes"]
