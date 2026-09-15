"""Owner-only scoped duty request routes; the browser never calls a planner or provider."""

from __future__ import annotations

from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.contracts import AuthorizePrincipal
from fdai_operator_service.families.iam.errors import IamFamilyError
from fdai_operator_service.families.iam.http import (
    error_response,
    family_error,
    read_json_object,
    require_revision,
    require_string,
)
from fdai_operator_service.families.iam.scoped_duty_contracts import ScopedDutyOutbox
from fdai_service_contracts.scoped_duty import ScopedDutyRequest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


def make_scoped_duty_routes(
    *,
    outbox: ScopedDutyOutbox | None,
    authorize: AuthorizePrincipal,
) -> tuple[Route, ...]:
    """Build the same bounded authenticated proposal surface in every execution venue."""

    async def respond(request: Request, operation: str) -> Response:
        principal = await authorize(request)
        if not has_capability(principal.roles, IamCapability.MANAGE_GROUP_MEMBERSHIP):
            return error_response(403, "Owner capability is required for scoped duty reviews")
        if outbox is None:
            return error_response(503, "scoped duty source and request bindings are unavailable")
        try:
            if operation == "catalog":
                result = await outbox.catalog()
            elif operation == "projection":
                if set(request.query_params) != {"agent_name", "scope_ref"}:
                    raise ValueError("scoped projection requires exact agent_name and scope_ref")
                result = await outbox.projection(
                    agent_name=request.query_params["agent_name"],
                    scope_ref=request.query_params["scope_ref"],
                )
            elif operation == "get":
                result = await outbox.get(str(request.path_params["case_id"]))
            else:
                body = await read_json_object(request, maximum=32_000)
                if operation == "create":
                    if set(body) != {"idempotency_key", "request", "justification"}:
                        raise ValueError("scoped creation fields do not match the contract")
                    justification = require_string(body, "justification")
                    if not 20 <= len(justification) <= 2000:
                        raise ValueError(
                            "scoped duty justification MUST contain 20-2000 characters"
                        )
                    result = await outbox.create(
                        principal=principal,
                        idempotency_key=require_string(body, "idempotency_key"),
                        request=ScopedDutyRequest.model_validate(body["request"]),
                        justification=justification,
                    )
                else:
                    allowed = {"expected_revision"} | (
                        {"decision", "plan_digest"} if operation == "review" else set()
                    )
                    if set(body) != allowed:
                        raise ValueError("scoped transition fields do not match the contract")
                    result = await outbox.transition(
                        principal=principal,
                        case_id=str(request.path_params["case_id"]),
                        expected_revision=require_revision(body, positive=True),
                        decision=(
                            require_string(body, "decision") if operation == "review" else None
                        ),
                        plan_digest=(
                            require_string(body, "plan_digest") if operation == "review" else None
                        ),
                    )
        except IamFamilyError as exc:
            return family_error(exc)
        except ValidationError:
            return error_response(400, "scoped duty declaration is malformed")
        except ValueError as exc:
            return error_response(400, str(exc))
        return JSONResponse(
            {**result, "execution_authority": False},
            status_code=202 if request.method == "POST" else 200,
            headers={"Cache-Control": "no-store"},
        )

    async def scoped_catalog(request: Request) -> Response:
        return await respond(request, "catalog")

    async def scoped_projection(request: Request) -> Response:
        return await respond(request, "projection")

    async def get_scoped_case(request: Request) -> Response:
        return await respond(request, "get")

    async def create_scoped_case(request: Request) -> Response:
        return await respond(request, "create")

    async def submit_scoped_case(request: Request) -> Response:
        return await respond(request, "submit")

    async def review_scoped_case(request: Request) -> Response:
        return await respond(request, "review")

    return (
        Route("/handover/scoped-duties/catalog", scoped_catalog, methods=["GET"]),
        Route("/handover/scoped-duties", scoped_projection, methods=["GET"]),
        Route("/handover/scoped-duty-cases", create_scoped_case, methods=["POST"]),
        Route("/handover/scoped-duty-cases/{case_id:str}", get_scoped_case, methods=["GET"]),
        Route(
            "/handover/scoped-duty-cases/{case_id:str}/submit", submit_scoped_case, methods=["POST"]
        ),
        Route(
            "/handover/scoped-duty-cases/{case_id:str}/review", review_scoped_case, methods=["POST"]
        ),
    )


__all__ = ["make_scoped_duty_routes"]
