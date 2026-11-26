"""Azure Functions v2 HTTP facade for the development operations gateway."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

import azure.functions as func  # type: ignore[import-untyped]
import httpx

if TYPE_CHECKING:
    from delivery.dev_operations_gateway.gateway import (
        GatewayConfig,
        GatewayError,
        GatewayPrincipal,
        ManagedIdentityTokenProvider,
        OperationsGateway,
    )
    from delivery.dev_operations_gateway.idempotency import (
        AzureBlobIdempotencyConfig,
        AzureBlobIdempotencyLedger,
    )
    from delivery.dev_operations_gateway.principal import (
        PrincipalHeaderError,
        parse_easy_auth_principal,
    )
elif __package__:
    from .gateway import (
        GatewayConfig,
        GatewayError,
        GatewayPrincipal,
        ManagedIdentityTokenProvider,
        OperationsGateway,
    )
    from .idempotency import AzureBlobIdempotencyConfig, AzureBlobIdempotencyLedger
    from .principal import PrincipalHeaderError, parse_easy_auth_principal
else:
    from gateway import (
        GatewayConfig,
        GatewayError,
        GatewayPrincipal,
        ManagedIdentityTokenProvider,
        OperationsGateway,
    )
    from idempotency import AzureBlobIdempotencyConfig, AzureBlobIdempotencyLedger
    from principal import PrincipalHeaderError, parse_easy_auth_principal

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(  # type: ignore[untyped-decorator]
    route="health", trigger_arg_name="_request", methods=["GET"]
)
async def health(_request: func.HttpRequest) -> func.HttpResponse:
    try:
        GatewayConfig.from_env()
    except ValueError as exc:
        return _response(503, {"status": "unavailable", "reason": str(exc)})
    return _response(200, {"status": "ok", "mode": "development"})


@app.route(  # type: ignore[untyped-decorator]
    route="v1/operations/{operation_id}", trigger_arg_name="request", methods=["POST"]
)
async def invoke(request: func.HttpRequest) -> func.HttpResponse:
    try:
        config = GatewayConfig.from_env()
    except ValueError as exc:
        return _response(
            503,
            {"status": "failed", "code": "configuration_invalid", "detail": str(exc)},
        )
    try:
        principal = _principal(request.headers)
        payload = request.get_json()
        if not isinstance(payload, Mapping):
            raise GatewayError(400, "payload_invalid", "request body MUST be a JSON object")
        async with httpx.AsyncClient() as client:
            reader_tokens = ManagedIdentityTokenProvider(
                client_id=config.reader_identity_client_id,
                http_client=client,
            )
            executor_tokens = ManagedIdentityTokenProvider(
                client_id=config.executor_identity_client_id,
                http_client=client,
            )
            gateway = OperationsGateway(
                config=config,
                reader_token_provider=reader_tokens,
                executor_token_provider=executor_tokens,
                idempotency_ledger=AzureBlobIdempotencyLedger(
                    config=AzureBlobIdempotencyConfig(
                        container_url=config.idempotency_container_url
                    ),
                    token_provider=reader_tokens,
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
    try:
        return parse_easy_auth_principal(encoded)
    except PrincipalHeaderError as exc:
        raise GatewayError(401, "unauthenticated", str(exc)) from exc


def _response(status_code: int, payload: Mapping[str, object]) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, separators=(",", ":")),
        status_code=status_code,
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )
