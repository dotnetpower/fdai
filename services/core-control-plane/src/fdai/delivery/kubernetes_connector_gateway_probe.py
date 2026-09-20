"""Authenticated, non-persisting gateway admission observation for one connector scope."""

from __future__ import annotations

import asyncio
import json
import secrets
import ssl
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Literal

import httpx
from fdai_service_contracts.cluster_connector import (
    ConnectorContract,
    ConnectorScope,
    Digest,
    connector_time,
)
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import ObserverDeploymentFact
from pydantic import Field, field_validator

from fdai.delivery.kubernetes_connector_transport import ConnectorTransportConfig

GATEWAY_PROBE_PATH = "/v1/connector/preflight"


class GatewayProbe(ConnectorContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    scope_digest: Digest
    nonce: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64)]


class GatewayProbeReceipt(GatewayProbe):
    observed_at: datetime
    execution_authority: Literal[False] = False

    @field_validator("observed_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @field_validator("execution_authority", mode="before")
    @classmethod
    def _authority(cls, value: object) -> object:
        if value is not False:
            raise ValueError("gateway probe cannot grant authority")
        return value


class GatewayObserverPreflight:
    """Prove current mTLS enrollment admission only, never topology, policy or inventory health."""

    def __init__(
        self,
        *,
        origin: str,
        scope: ConnectorScope,
        tls: ssl.SSLContext,
        now: Callable[[], datetime],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        ConnectorTransportConfig(origin, "gateway-preflight")
        if tls.verify_mode != ssl.CERT_REQUIRED or not tls.check_hostname:
            raise ValueError("gateway preflight requires verified TLS")
        self._origin, self._scope, self._tls, self._now, self._transport = (
            origin,
            scope,
            tls,
            now,
            transport,
        )

    async def collect(self) -> ObserverDeploymentFact:
        from fdai.delivery.kubernetes_connector_gateway import _unique_object

        observed = connector_time(self._now())
        challenge = GatewayProbe(
            scope_digest=canonical_digest(self._scope.model_dump(mode="json")),
            nonce=secrets.token_hex(32),
        )
        state: Literal["allowed", "unknown"] = "unknown"
        evidence: dict[str, object] = {"scope_digest": challenge.scope_digest, "state": "unknown"}
        try:
            async with (
                asyncio.timeout(10),
                httpx.AsyncClient(
                    verify=self._tls,
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=3,
                ) as client,
            ):
                async with client.stream(
                    "POST",
                    self._origin + GATEWAY_PROBE_PATH,
                    json=challenge.model_dump(mode="json"),
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("Content-Encoding", "identity") != "identity"
                    ):
                        raise ValueError("gateway preflight response unavailable")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > 4096:
                            raise ValueError("gateway preflight response too large")
                        body.extend(chunk)
                receipt = GatewayProbeReceipt.model_validate(
                    json.loads(body, object_pairs_hook=_unique_object)
                )
                completed = connector_time(self._now())
                if (
                    receipt.scope_digest != challenge.scope_digest
                    or receipt.nonce != challenge.nonce
                ):
                    raise ValueError("gateway preflight response binding mismatch")
                if (
                    not observed - timedelta(seconds=5)
                    <= receipt.observed_at
                    <= completed + timedelta(seconds=5)
                ):
                    raise ValueError("gateway preflight server clock is outside its bound")
                state = "allowed"
                evidence = receipt.model_dump(mode="json")
        except (httpx.HTTPError, TimeoutError, ValueError):
            evidence["reason"] = "gateway_admission_unavailable"
        if not observed <= connector_time(self._now()) < observed + timedelta(minutes=5):
            raise ValueError("gateway preflight observation expired")
        return ObserverDeploymentFact(
            target_ref=self._scope.cluster_ref,
            name="mtls_gateway",
            state=state,
            source="network_probe",
            evidence_digest=canonical_digest(evidence),
            observed_at=observed,
            expires_at=observed + timedelta(minutes=5),
        )
