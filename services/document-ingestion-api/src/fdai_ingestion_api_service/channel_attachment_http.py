"""Internal authenticated HTTPS transport for channel attachment handoff."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    ChannelAttachmentTerminalReceipt,
    CompatibilityError,
)
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_ingestion_api_service.auth import (
    AuthenticationError,
    ChannelAttachmentWorkloadAuthenticator,
    WorkloadAuthorizationError,
)
from fdai_ingestion_api_service.channel_attachment import (
    ChannelAttachmentAdmissionDeniedError,
    ChannelAttachmentConflictError,
    ChannelAttachmentIntakeService,
)
from fdai_ingestion_api_service.contract_codecs import (
    CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_V1,
    CHANNEL_ATTACHMENT_RECEIPT_PRODUCER_V1,
)

_ROOT = "/internal/document-ingestion/channel-attachments/v1"
_REQUEST_DIGEST_HEADER = "x-fdai-request-digest"
_CONTENT_SHA256_HEADER = "x-fdai-content-sha256"


class ChannelAttachmentIntake(Protocol):
    """Expose only the application operations needed by the internal transport."""

    async def admit(self, request: ChannelAttachmentAdmissionRequest) -> object: ...

    async def commit(
        self,
        *,
        handoff_id: str,
        request_digest: str,
        observed_size: int,
        observed_sha256: str,
        chunks: AsyncIterator[bytes],
    ) -> ChannelAttachmentCommitReceipt: ...

    async def status(
        self,
        *,
        handoff_id: str,
        request_digest: str,
    ) -> (
        ChannelAttachmentAdmissionReceipt
        | ChannelAttachmentCommitReceipt
        | ChannelAttachmentTerminalReceipt
    ): ...


@dataclass(frozen=True, slots=True)
class ChannelAttachmentHttpConfig:
    """Bound internal request size and process lifecycle dependencies."""

    max_admission_bytes: int = 32_768
    startup_checks: tuple[Callable[[], Awaitable[None]], ...] = ()
    readiness_checks: tuple[Callable[[], Awaitable[None]], ...] = ()
    background_tasks: tuple[Callable[[], Coroutine[object, object, None]], ...] = ()
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.max_admission_bytes <= 262_144:
            raise ValueError("channel attachment admission body limit is invalid")


def build_channel_attachment_app(
    *,
    authenticator: ChannelAttachmentWorkloadAuthenticator,
    intake: ChannelAttachmentIntakeService,
    config: ChannelAttachmentHttpConfig | None = None,
) -> Starlette:
    """Build the internal app without public upload routes or worker imports."""

    resolved = config or ChannelAttachmentHttpConfig()
    lifecycle_started = False
    running_tasks: tuple[asyncio.Task[None], ...] = ()

    def authenticate(request: Request) -> None:
        authenticator.authenticate(request.headers.get("authorization"))

    async def live(_request: Request) -> Response:
        if not lifecycle_started:
            return _error(503, "not_live", "channel attachment intake is not live")
        return JSONResponse({"status": "live"})

    async def ready(_request: Request) -> Response:
        if not lifecycle_started:
            return _error(503, "not_ready", "channel attachment intake is not ready")
        if any(task.done() for task in running_tasks):
            return _error(503, "not_ready", "channel attachment intake is not ready")
        try:
            for check in resolved.readiness_checks:
                await check()
        except Exception:
            return _error(503, "not_ready", "channel attachment intake is not ready")
        return JSONResponse({"status": "ready"})

    async def auth_probe(request: Request) -> Response:
        authenticate(request)
        return Response(status_code=204)

    async def admit(request: Request) -> Response:
        authenticate(request)
        body = await _bounded_body(request.stream(), maximum=resolved.max_admission_bytes)
        payload = CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_V1.decode(body)
        admission = await intake.admit(ChannelAttachmentAdmissionRequest.model_validate(payload))
        return _receipt(admission, status_code=201)

    async def commit(request: Request) -> Response:
        authenticate(request)
        handoff_id = _handoff_id(request.path_params.get("handoff_id"))
        request_digest = _digest_header(request, _REQUEST_DIGEST_HEADER)
        content_sha256 = request.headers.get(_CONTENT_SHA256_HEADER, "")
        if len(content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in content_sha256
        ):
            raise ValueError("channel attachment content SHA-256 header is invalid")
        content_length = request.headers.get("content-length")
        if content_length is None:
            raise ValueError("channel attachment Content-Length is required")
        try:
            observed_size = int(content_length)
        except ValueError as exc:
            raise ValueError("channel attachment Content-Length is invalid") from exc
        if observed_size < 1:
            raise ValueError("channel attachment Content-Length MUST be positive")
        receipt = await intake.commit(
            handoff_id=handoff_id,
            request_digest=request_digest,
            observed_size=observed_size,
            observed_sha256=content_sha256,
            chunks=request.stream(),
        )
        return _receipt(receipt, status_code=200)

    async def status(request: Request) -> Response:
        authenticate(request)
        receipt = await intake.status(
            handoff_id=_handoff_id(request.path_params.get("handoff_id")),
            request_digest=_digest_header(request, _REQUEST_DIGEST_HEADER),
        )
        return _receipt(receipt, status_code=200)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        nonlocal lifecycle_started, running_tasks
        for check in resolved.startup_checks:
            await check()
        running_tasks = tuple(asyncio.create_task(task()) for task in resolved.background_tasks)
        lifecycle_started = True
        try:
            yield
        finally:
            lifecycle_started = False
            for task in running_tasks:
                task.cancel()
            for task in running_tasks:
                with suppress(asyncio.CancelledError):
                    await task
            running_tasks = ()
            for callback in resolved.shutdown_callbacks:
                await callback()

    async def authentication_error(_request: Request, _exc: Exception) -> Response:
        return _error(401, "unauthorized", "authentication is required")

    async def authorization_error(_request: Request, _exc: Exception) -> Response:
        return _error(403, "forbidden", "channel attachment intake is denied")

    async def conflict_error(_request: Request, _exc: Exception) -> Response:
        return _error(409, "handoff_conflict", "channel attachment handoff conflicts")

    async def invalid_request(_request: Request, _exc: Exception) -> Response:
        return _error(400, "invalid_request", "channel attachment request is invalid")

    return Starlette(
        routes=[
            Route("/health/live", live, methods=["GET"]),
            Route("/health/ready", ready, methods=["GET"]),
            Route(f"{_ROOT}/auth-probe", auth_probe, methods=["GET"]),
            Route(f"{_ROOT}/admissions", admit, methods=["POST"]),
            Route(f"{_ROOT}/{{handoff_id}}/content", commit, methods=["PUT"]),
            Route(f"{_ROOT}/{{handoff_id}}", status, methods=["GET"]),
        ],
        exception_handlers={
            AuthenticationError: authentication_error,
            WorkloadAuthorizationError: authorization_error,
            ChannelAttachmentAdmissionDeniedError: authorization_error,
            ChannelAttachmentConflictError: conflict_error,
            CompatibilityError: invalid_request,
            ValidationError: invalid_request,
            ValueError: invalid_request,
        },
        lifespan=lifespan,
    )


def _receipt(receipt: object, *, status_code: int) -> JSONResponse:
    if not hasattr(receipt, "model_dump"):
        raise RuntimeError("channel attachment intake returned an invalid receipt")
    payload = receipt.model_dump(mode="json")
    encoded = CHANNEL_ATTACHMENT_RECEIPT_PRODUCER_V1.encode(payload)
    return JSONResponse(json.loads(encoded), status_code=status_code)


async def _bounded_body(chunks: AsyncIterator[bytes], *, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > maximum:
            raise ValueError("channel attachment admission body exceeds the byte limit")
    return bytes(body)


def _handoff_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("channel-attachment-")
        or len(value) != 83
        or any(character not in "0123456789abcdef" for character in value[19:])
    ):
        raise ValueError("channel attachment handoff id is invalid")
    return value


def _digest_header(request: Request, name: str) -> str:
    value = request.headers.get(name, "")
    if (
        not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} header is invalid")
    return value


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


__all__ = ["ChannelAttachmentHttpConfig", "build_channel_attachment_app"]
