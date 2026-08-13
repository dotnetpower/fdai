"""Service-local Starlette factory for workflow and governed catalog routes.

Responsibility: Parse bounded HTTP requests and dispatch typed reads or proposals.
Boundary: Domain validation, durable reads, and proposal publication remain injected.
Authority and state: The factory never executes, promotes, or owns durable state.
Dependencies: Starlette, neutral service contracts, and workflow-family protocols.
Deployment: Runs inside Operator Service without importing the FDAI monolith.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import cast

from fdai_operator_service.families.workflow.contracts import (
    WorkflowOperation,
    WorkflowPrincipalAuthorizer,
    WorkflowProposal,
    WorkflowProposalWriter,
    WorkflowReadRequest,
    WorkflowReadStore,
)
from fdai_operator_service.families.workflow.manifest import (
    WORKFLOW_FAMILY_ROUTE_MANIFEST,
    PaginationSpec,
    WorkflowRouteSpec,
)
from fdai_operator_service.redaction import redact_mapping
from fdai_service_contracts import JsonObject, RuleSearchRequest
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

_MAX_QUERY_VALUE_CHARS = 2_048
_MAX_PATH_VALUE_CHARS = 256
_MAX_IDEMPOTENCY_CHARS = 200
_MAX_REVISION_CHARS = 256


def build_workflow_family_routes(
    *,
    authorize: WorkflowPrincipalAuthorizer,
    read_store: WorkflowReadStore,
    proposal_writer: WorkflowProposalWriter,
) -> tuple[Route, ...]:
    """Build the exact workflow family while keeping every mutation proposal-only."""
    return tuple(
        Route(
            spec.path,
            _build_endpoint(
                spec,
                authorize=authorize,
                read_store=read_store,
                proposal_writer=proposal_writer,
            ),
            methods=[spec.method],
            name=spec.name,
        )
        for spec in WORKFLOW_FAMILY_ROUTE_MANIFEST
    )


def _build_endpoint(
    spec: WorkflowRouteSpec,
    *,
    authorize: WorkflowPrincipalAuthorizer,
    read_store: WorkflowReadStore,
    proposal_writer: WorkflowProposalWriter,
) -> Callable[[Request], Awaitable[Response]]:
    async def endpoint(request: Request) -> Response:
        principal = await authorize(request, spec.required_roles)
        query, limit, offset = _validated_query(request, spec.pagination)
        path_parameters = _validated_path_parameters(request.path_params)
        body = await _body(request, maximum=spec.maximum_body_bytes)
        if spec.operation is WorkflowOperation.RULE_SEARCH:
            try:
                body = RuleSearchRequest.model_validate(body).model_dump(mode="json")
            except ValidationError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Rule search request is invalid",
                ) from exc

        if spec.dispatch == "read":
            result = await read_store.read(
                WorkflowReadRequest(
                    operation=spec.operation,
                    principal_id=principal.subject_id,
                    query=query,
                    path_parameters=path_parameters,
                    body=body,
                    limit=limit,
                    offset=offset,
                )
            )
            return JSONResponse(
                redact_mapping(result.payload),
                status_code=result.status_code,
                headers={
                    "X-FDAI-Provenance": result.provenance.source_ref,
                    "X-FDAI-Revision": result.provenance.revision,
                },
            )

        _require_shadow(body)
        idempotency_key = _required_header(
            request,
            "Idempotency-Key",
            maximum=_MAX_IDEMPOTENCY_CHARS,
        )
        expected_revision = _required_header(
            request,
            "If-Match",
            maximum=_MAX_REVISION_CHARS,
        )
        proposal = WorkflowProposal(
            operation=spec.operation,
            principal_id=principal.subject_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            request_source=f"operator-http:{spec.name}",
            path_parameters=path_parameters,
            payload=body or {},
        )
        receipt = await proposal_writer.submit(proposal)
        return JSONResponse(
            {
                "accepted": True,
                "proposal_id": receipt.proposal_id,
                "operation": proposal.operation.value,
                "mode": proposal.mode,
                "idempotency_key": proposal.idempotency_key,
                "revision": receipt.revision,
                "duplicate": receipt.duplicate,
            },
            status_code=202,
            headers={"X-FDAI-Revision": receipt.revision},
        )

    endpoint.__name__ = spec.name
    return endpoint


def _validated_query(
    request: Request,
    pagination: PaginationSpec | None,
) -> tuple[dict[str, str], int | None, int | None]:
    query = dict(request.query_params)
    for key, value in query.items():
        if len(key) > 128 or len(value) > _MAX_QUERY_VALUE_CHARS:
            raise HTTPException(status_code=400, detail="query parameter exceeds its bound")

    limit: int | None = None
    offset: int | None = None
    if pagination is not None:
        limit = _bounded_integer(
            query.pop("limit", str(pagination.default_limit)),
            name="limit",
            minimum=1,
            maximum=pagination.maximum_limit,
        )
        if pagination.supports_offset:
            offset = _bounded_integer(
                query.pop("offset", "0"),
                name="offset",
                minimum=0,
                maximum=2_147_483_647,
            )
        elif "offset" in query:
            raise HTTPException(status_code=400, detail="offset is not supported")

    if request.url.path == "/api/v1/skill-sources/search":
        needle = query.get("q", "").strip()
        if not needle or len(needle) > 128:
            raise HTTPException(status_code=400, detail="skill source search q MUST be bounded")
    if request.url.path.startswith("/admin/trajectory-datasets"):
        if not query.get("purpose", "").strip() or not query.get("access_scope", "").strip():
            raise HTTPException(
                status_code=400,
                detail="purpose and access_scope are required",
            )
    if request.url.path == "/kpi/promotion-gates":
        if "window_days" in query:
            _bounded_integer(
                query["window_days"],
                name="window_days",
                minimum=1,
                maximum=365,
            )
        if len(query.get("action_type", "")) > 256:
            raise HTTPException(status_code=400, detail="action_type filter is too long")
    return query, limit, offset


def _validated_path_parameters(raw: Mapping[str, object]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value or len(value) > _MAX_PATH_VALUE_CHARS:
            raise HTTPException(status_code=400, detail=f"{key} path parameter is malformed")
        values[key] = value
    return values


async def _body(request: Request, *, maximum: int) -> JsonObject | None:
    if maximum == 0:
        raw = await request.body()
        if raw:
            raise HTTPException(status_code=400, detail="request body MUST be empty")
        return None
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Content-Length MUST be an integer",
            ) from exc
        if declared > maximum:
            raise HTTPException(status_code=413, detail="request body is too large")
    raw = await request.body()
    if len(raw) > maximum:
        raise HTTPException(status_code=413, detail="request body is too large")
    try:
        value = json.loads(raw or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be valid JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be a JSON object")
    return cast(JsonObject, value)


def _require_shadow(body: JsonObject | None) -> None:
    if body is None:
        return
    requested_mode = body.get("mode", "shadow")
    if requested_mode != "shadow":
        raise HTTPException(
            status_code=409,
            detail="Operator workflow requests are proposal-only and MUST remain shadow",
        )


def _required_header(request: Request, name: str, *, maximum: int) -> str:
    value = request.headers.get(name, "").strip()
    if not value or len(value) > maximum:
        raise HTTPException(
            status_code=428 if not value else 400,
            detail=f"{name} MUST be a bounded non-empty value",
        )
    return value


def _bounded_integer(raw: str, *, name: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name} MUST be an integer") from exc
    if value < minimum or value > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"{name} MUST be between {minimum} and {maximum}",
        )
    return value


__all__ = ["build_workflow_family_routes"]
