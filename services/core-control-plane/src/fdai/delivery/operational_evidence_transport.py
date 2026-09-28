"""Bounded issuance transports: one attempt, a two-second limit, and no retry.

A timeout, ``429``, ``503``, or any other transport failure ends the attempt as unavailable.
The HTTP body is only a claim: owners re-read the named record from the proof store before it
counts, so a forged response body admits nothing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
)
from pydantic import ValidationError

from fdai.core.operational_evidence.issuance import OperationalEvidenceVerifierEngine

ISSUANCE_PATH = "/v1/operational-evidence/issuance"
_LOGGER = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 4096


class OperationalEvidenceTransport(Protocol):
    """Deliver one request to the verifier workload and return its content-free response."""

    async def send(
        self, request: OperationalEvidenceIssuanceRequest
    ) -> OperationalEvidenceIssuanceResponse: ...


class BoundedOperationalEvidenceIssuer:
    """Provider-seam implementation: exactly one bounded attempt per request."""

    def __init__(self, transport: OperationalEvidenceTransport, *, timeout_seconds: float = 2.0):
        if not 0 < timeout_seconds <= 2.0:
            raise ValueError("operational evidence issuance limit MUST be in (0, 2] seconds")
        self._transport = transport
        self._timeout = timeout_seconds

    async def issue(
        self, request: OperationalEvidenceIssuanceRequest
    ) -> OperationalEvidenceIssuanceResponse:
        try:
            async with asyncio.timeout(self._timeout):
                return await self._transport.send(request)
        except (TimeoutError, OSError, httpx.HTTPError, ValidationError, ValueError) as exc:
            _LOGGER.warning(
                "operational_evidence_issuance_unavailable",
                extra={"purpose_id": request.lookup.purpose_id, "error_type": type(exc).__name__},
            )
            return OperationalEvidenceIssuanceResponse.unavailable(request)


class HttpOperationalEvidenceTransport:
    """POST one request to the internal verifier endpoint; every non-200 is unavailable."""

    def __init__(self, client: httpx.AsyncClient, *, base_url: str) -> None:
        url = httpx.URL(base_url)
        loopback = url.host in {"127.0.0.1", "localhost", "::1"}
        if (
            not url.host
            or url.scheme not in {"http", "https"}
            or (url.scheme == "http" and not loopback)
        ):
            raise ValueError("verifier endpoint MUST use HTTPS or a loopback HTTP address")
        self._client = client
        self._url = str(url.join(ISSUANCE_PATH))

    async def send(
        self, request: OperationalEvidenceIssuanceRequest
    ) -> OperationalEvidenceIssuanceResponse:
        response = await self._client.post(
            self._url,
            content=request.model_dump_json().encode(),
            headers={"content-type": "application/json"},
        )
        if response.status_code != 200 or len(response.content) > _MAX_RESPONSE_BYTES:
            return OperationalEvidenceIssuanceResponse.unavailable(request)
        return OperationalEvidenceIssuanceResponse.model_validate_json(response.content)


class InProcessOperationalEvidenceTransport:
    """Call a verifier engine in the same event loop; for tests and loopback tooling only.

    The engine still writes through its own verifier-role connection. Running it inside a
    consumer process never makes that process an authorized writer; the proof-store grants
    readback decides whether the venue is writer-exclusive.
    """

    def __init__(self, engine: OperationalEvidenceVerifierEngine, *, caller_principal: str):
        self._engine = engine
        self._caller = caller_principal

    async def send(
        self, request: OperationalEvidenceIssuanceRequest
    ) -> OperationalEvidenceIssuanceResponse:
        return await self._engine.issue(request, caller_principal=self._caller)


__all__ = [
    "ISSUANCE_PATH",
    "BoundedOperationalEvidenceIssuer",
    "HttpOperationalEvidenceTransport",
    "InProcessOperationalEvidenceTransport",
    "OperationalEvidenceTransport",
]
