"""Bounded outbound HTTPS transport for authority-free connector evidence metadata."""

from __future__ import annotations

import asyncio
import json
import math
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from fdai_service_contracts.cluster_connector import ConnectorEvidence, connector_time

from fdai.delivery.kubernetes_connector import ConnectorAdmissionReceipt, ConnectorAdmissionStatus
from fdai.delivery.kubernetes_connector_artifact import decode_snapshot
from fdai.shared.providers.workload_identity import WorkloadIdentity

_REQUEST_LIMIT = 32_768
_RESPONSE_LIMIT = 8_192


class ConnectorTransportError(RuntimeError):
    """Expose a fixed failure category, never the endpoint, credential, or response body."""


@dataclass(frozen=True, slots=True)
class ConnectorTransportConfig:
    """Pin a credential-free TLS origin and finite total request budget."""

    origin: str
    audience: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.origin)
        if (
            not self.origin.isascii()
            or len(self.origin) > 2048
            or any(character.isspace() or ord(character) < 32 for character in self.origin)
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "\\" in self.origin
        ):
            raise ValueError("connector origin must be a credential-free HTTPS origin")
        try:
            if parsed.port == 0:
                raise ValueError("connector port cannot be zero")
        except ValueError:
            raise ValueError("connector origin has an invalid port") from None
        if (
            not self.audience
            or len(self.audience) > 512
            or any(character.isspace() or ord(character) < 32 for character in self.audience)
        ):
            raise ValueError("connector audience must be a bounded non-empty identifier")
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or not 0.1 <= self.timeout_seconds <= 30
        ):
            raise ValueError("connector total timeout must be in [0.1, 30]")


class ConnectorEvidenceTransport:
    """Send one envelope without retries; independently match its bounded acknowledgment.

    An optional httpx transport is a composition/testing seam. Production construction uses
    normal TLS certificate validation, disables environment proxies, and follows no redirects.
    Snapshot transfer validates the normalized artifact before sending it. The adapter never
    invokes a mutation. An explicitly supplied TLS context enables certificate authentication;
    disabling certificate or hostname verification is not supported.
    """

    def __init__(
        self,
        config: ConnectorTransportConfig,
        *,
        identity: WorkloadIdentity | None = None,
        tls_context: ssl.SSLContext | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if tls_context is not None and (
            tls_context.verify_mode != ssl.CERT_REQUIRED or not tls_context.check_hostname
        ):
            raise ValueError("connector TLS requires certificate and hostname verification")
        if identity is None and tls_context is None:
            raise ValueError("connector requires workload identity or an explicit mTLS context")
        self._config = config
        self._identity = identity
        self._now = now or (lambda: datetime.now(UTC))
        self._client = httpx.AsyncClient(
            transport=transport,
            verify=tls_context if tls_context is not None else True,
            trust_env=False,
            follow_redirects=False,
            timeout=config.timeout_seconds,
        )

    async def aclose(self) -> None:
        """Release connection-pool resources when the owning worker stops."""
        await self._client.aclose()

    async def send(self, packet: ConnectorEvidence) -> ConnectorAdmissionReceipt:
        """Send exactly one envelope under a budget that includes token acquisition."""
        packet = ConnectorEvidence.model_validate_json(packet.model_dump_json())
        body = packet.model_dump_json().encode("utf-8")
        if len(body) > _REQUEST_LIMIT:
            raise ConnectorTransportError("connector request exceeds the metadata size limit")
        return await self._send(packet, body, "/v1/connector/evidence")

    async def send_snapshot(
        self,
        packet: ConnectorEvidence,
        content: bytes,
        *,
        allow_cluster_resources: bool,
    ) -> ConnectorAdmissionReceipt:
        """Transfer exact validated artifact bytes with their bound evidence envelope."""
        decode_snapshot(content, packet, allow_cluster_resources=allow_cluster_resources)
        body = json.dumps(
            {"evidence": packet.model_dump(mode="json"), "artifact": content.decode("utf-8")},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if len(body) > 2 * 8_388_608 + _REQUEST_LIMIT:
            raise ConnectorTransportError("connector snapshot transfer exceeds its size limit")
        return await self._send(packet, body, "/v1/connector/snapshots")

    async def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._identity is None:
            return headers
        try:
            credential = await self._identity.get_token(self._config.audience)
        except Exception:
            raise ConnectorTransportError("connector identity is unavailable") from None
        if (
            credential.audience != self._config.audience
            or connector_time(credential.expires_at) <= connector_time(self._now())
            or not credential.token
            or len(credential.token) > 16_384
            or not credential.token.isascii()
            or any(
                char.isspace() or ord(char) < 32 or ord(char) == 127 for char in credential.token
            )
        ):
            raise ConnectorTransportError("connector credential is invalid or expired")
        headers["Authorization"] = f"Bearer {credential.token}"
        return headers

    async def _send(
        self, packet: ConnectorEvidence, body: bytes, path: str
    ) -> ConnectorAdmissionReceipt:
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                headers = await self._headers()
                async with self._client.stream(
                    "POST",
                    self._config.origin.rstrip("/") + path,
                    content=body,
                    headers=headers,
                    follow_redirects=False,
                ) as response:
                    if response.status_code not in {200, 201}:
                        raise ConnectorTransportError(
                            "connector gateway did not accept the envelope"
                        )
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        if len(content) + len(chunk) > _RESPONSE_LIMIT:
                            raise ConnectorTransportError(
                                "connector acknowledgment exceeds the size limit"
                            )
                        content.extend(chunk)
                return _acknowledgment(bytes(content), packet)
        except ConnectorTransportError:
            raise
        except (ValueError, TypeError):
            raise ConnectorTransportError("connector response or credential is malformed") from None
        except (TimeoutError, httpx.HTTPError):
            raise ConnectorTransportError(
                "connector request failed or exceeded its deadline"
            ) from None


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate acknowledgment field")
        result[key] = value
    return result


def _acknowledgment(content: bytes, packet: ConnectorEvidence) -> ConnectorAdmissionReceipt:
    try:
        value = json.loads(content, object_pairs_hook=_unique_fields)
    except (ValueError, UnicodeDecodeError):
        raise ConnectorTransportError("connector acknowledgment is not valid JSON") from None
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "status", "evidence_digest", "sequence"}
        or value["schema_version"] != "1.0.0"
        or not isinstance(value["status"], str)
        or value["status"] not in {"accepted", "duplicate"}
        or value["evidence_digest"] != packet.digest
        or type(value["sequence"]) is not int
        or value["sequence"] != packet.sequence
    ):
        raise ConnectorTransportError("connector acknowledgment does not match the envelope")
    return ConnectorAdmissionReceipt(
        ConnectorAdmissionStatus(value["status"]),
        packet.digest,
        packet.sequence,
    )
