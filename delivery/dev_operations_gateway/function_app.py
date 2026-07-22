"""Azure Functions v2 HTTP facade for the development operations gateway."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

import azure.functions as func
import httpx

if TYPE_CHECKING:
    from delivery.dev_operations_gateway.gateway import (
        GatewayConfig,
        GatewayError,
        GatewayPrincipal,
        ManagedIdentityTokenProvider,
        OperationsGateway,
    )
else:
    from gateway import (
        GatewayConfig,
        GatewayError,
        GatewayPrincipal,
        ManagedIdentityTokenProvider,
        OperationsGateway,
    )

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="health", methods=["GET"])
async def health(_request: func.HttpRequest) -> func.HttpResponse:
    try:
        GatewayConfig.from_env()
    except ValueError as exc:
        return _response(503, {"status": "unavailable", "reason": str(exc)})
    return _response(200, {"status": "ok", "mode": "development"})


@app.route(route="v1/operations/{operation_id}", methods=["POST"])
async def invoke(request: func.HttpRequest) -> func.HttpResponse:
    try:
        config = GatewayConfig.from_env()
        principal = _principal(request.headers)
        payload = request.get_json()
        if not isinstance(payload, Mapping):
            raise GatewayError(400, "payload_invalid", "request body MUST be a JSON object")
        async with httpx.AsyncClient() as client:
            gateway = OperationsGateway(
                config=config,
                reader_token_provider=ManagedIdentityTokenProvider(
                    client_id=config.reader_identity_client_id,
                    http_client=client,
                ),
                executor_token_provider=ManagedIdentityTokenProvider(
                    client_id=config.executor_identity_client_id,
                    http_client=client,
                ),
                http_client=client,
            )
            result = await gateway.invoke(
                str(request.route_params.get("operation_id", "")),
                payload,
                principal,
            )
        return _response(200, result)
    except GatewayError as exc:
        return _response(
            exc.status_code,
            {"status": "failed", "code": exc.code, "detail": str(exc)},
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"status": "failed", "code": "request_invalid", "detail": str(exc)})


def _principal(headers: Mapping[str, str]) -> GatewayPrincipal:
    encoded = headers.get("X-MS-CLIENT-PRINCIPAL", "")
    if not encoded:
        raise GatewayError(401, "unauthenticated", "Easy Auth principal is required")
    try:
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayError(401, "unauthenticated", "Easy Auth principal is invalid") from exc
    claims = payload.get("claims") if isinstance(payload, Mapping) else None
    if not isinstance(claims, list):
        raise GatewayError(401, "unauthenticated", "Easy Auth claims are missing")
    object_id = ""
    groups: set[str] = set()
    roles: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        claim_type = str(claim.get("typ", ""))
        value = str(claim.get("val", ""))
        if claim_type in {"oid", "http://schemas.microsoft.com/identity/claims/objectidentifier"}:
            object_id = value
        if claim_type in {
            "groups",
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups",
        }:
            groups.add(value)
        if claim_type in {
            "roles",
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
        }:
            roles.add(value)
    if not object_id:
        raise GatewayError(401, "unauthenticated", "Easy Auth object id is missing")
    return GatewayPrincipal(
        object_id=object_id,
        groups=frozenset(groups),
        roles=frozenset(roles),
    )


def _response(status_code: int, payload: Mapping[str, object]) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, separators=(",", ":")),
        status_code=status_code,
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )
