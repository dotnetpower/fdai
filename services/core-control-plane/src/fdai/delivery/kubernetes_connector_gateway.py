"""mTLS-only bounded snapshot ingress; no executor or provider credentials."""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
from collections.abc import Callable
from datetime import datetime

from aiohttp import web
from fdai_service_contracts.cluster_connector import ConnectorEvidence

from fdai.delivery.kubernetes_connector_snapshot import (
    ConnectorRegistrationReader,
    ConnectorSnapshotInbox,
)

MAX_TRANSFER_BYTES = 2 * 8_388_608 + 32_768


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate transfer field")
        value[key] = item
    return value


def create_connector_gateway(
    *,
    inbox: ConnectorSnapshotInbox,
    registrations: ConnectorRegistrationReader,
    now: Callable[[], datetime],
    max_concurrent_requests: int = 4,
) -> web.Application:
    """Build ingress that admits only actual verified TLS client certificates.

    Run behind a TLS listener with CERT_REQUIRED, not a TLS-terminating proxy. An HTTP
    listener, forwarded certificate header, bearer token or absent client certificate is
    never accepted as a principal. The server-owned registry pins certificate fingerprints.
    """
    if type(max_concurrent_requests) is not int or not 1 <= max_concurrent_requests <= 16:
        raise ValueError("connector concurrency must be in [1, 16]")
    slots = asyncio.Semaphore(max_concurrent_requests)

    async def receive(request: web.Request) -> web.Response:
        transport = request.transport
        tls = transport.get_extra_info("ssl_object") if transport is not None else None
        if tls is None or tls.context.verify_mode != ssl.CERT_REQUIRED:
            raise web.HTTPUnauthorized(text="verified client certificate required")
        certificate = tls.getpeercert(binary_form=True)
        if not certificate:
            raise web.HTTPUnauthorized(text="verified client certificate required")
        principal = "sha256:" + hashlib.sha256(certificate).hexdigest()
        if slots.locked():
            raise web.HTTPServiceUnavailable(text="connector request capacity unavailable")
        async with slots:
            try:
                async with asyncio.timeout(15):
                    registration = await registrations.read(principal)
                    if registration is None:
                        raise web.HTTPForbidden(text="connector enrollment unavailable")
                    registration.admit(
                        principal_ref=principal,
                        scope=registration.scope,
                        capability="inventory.snapshot",
                        now=now(),
                    )
                    if (
                        request.content_type != "application/json"
                        or request.headers.get("Content-Encoding", "identity") != "identity"
                    ):
                        raise web.HTTPUnsupportedMediaType(text="uncompressed JSON required")
                    body = bytearray()
                    async for chunk in request.content.iter_chunked(65_536):
                        if len(body) + len(chunk) > MAX_TRANSFER_BYTES:
                            raise web.HTTPRequestEntityTooLarge(
                                max_size=MAX_TRANSFER_BYTES, actual_size=len(body) + len(chunk)
                            )
                        body.extend(chunk)
                    value = json.loads(body, object_pairs_hook=_unique_object)
                    if (
                        not isinstance(value, dict)
                        or set(value) != {"evidence", "artifact"}
                        or not isinstance(value["artifact"], str)
                    ):
                        raise ValueError("invalid snapshot transfer")
                    packet = ConnectorEvidence.model_validate(value["evidence"])
                    receipt = await inbox.accept(
                        packet, value["artifact"].encode("utf-8"), principal_ref=principal
                    )
                    return web.json_response(
                        {
                            "schema_version": "1.0.0",
                            "status": receipt.status.value,
                            "evidence_digest": receipt.evidence_digest,
                            "sequence": receipt.sequence,
                        },
                        status=201 if receipt.status == "accepted" else 200,
                    )
            except web.HTTPException:
                raise
            except (ValueError, TypeError, RecursionError, KeyError, OverflowError):
                raise web.HTTPUnprocessableEntity(
                    text="connector snapshot was not admitted"
                ) from None
            except TimeoutError:
                raise web.HTTPGatewayTimeout(text="connector request deadline exceeded") from None
            except Exception:
                raise web.HTTPServiceUnavailable(text="connector persistence unavailable") from None

    app = web.Application(
        client_max_size=MAX_TRANSFER_BYTES, handler_args={"auto_decompress": False}
    )
    app.router.add_post("/v1/connector/snapshots", receive)
    return app
