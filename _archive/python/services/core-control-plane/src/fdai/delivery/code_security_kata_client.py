"""Authenticated in-cluster observation of code-security scanner Jobs and bounded stdout."""

from __future__ import annotations

import json
import os
import ssl
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class KataApiError(RuntimeError):
    """A Kubernetes operation failed; callers do not retry ambiguous writes or provider errors."""


class InClusterKataClient:
    """The controller's service-account identity never appears in a scanner Job or its logs."""

    def __init__(
        self,
        endpoint: str,
        *,
        token_file: Path,
        ca_file: Path,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        target = urlsplit(endpoint)
        if (
            target.scheme != "https"
            or not target.hostname
            or target.username
            or target.password
            or target.path not in ("", "/")
            or target.query
            or target.fragment
        ):
            raise ValueError("Kubernetes API must be an HTTPS origin without credentials")
        self._token_file = token_file
        self._http = httpx.AsyncClient(
            base_url=endpoint.rstrip("/"),
            verify=ssl.create_default_context(cafile=str(ca_file)),
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            transport=transport,
        )

    @classmethod
    def from_environment(cls) -> InClusterKataClient:
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "").strip()
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443").strip()
        if not host or not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise ValueError("Kata scanning requires an in-cluster Kubernetes API binding")
        # Bracket the configured IPv6 address; hostnames and IPv4 remain unchanged.
        host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        directory = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        return cls(
            f"https://{host}:{port}", token_file=directory / "token", ca_file=directory / "ca.crt"
        )

    def _headers(self) -> dict[str, str]:
        with self._token_file.open("r") as stream:
            token = stream.read(16385).strip()
        if not token or len(token) > 16384 or any(char.isspace() for char in token):
            raise KataApiError("Kubernetes service-account credential is unavailable")
        return {"Authorization": f"Bearer {token}"}

    async def request(
        self, method: str, path: str, *, body: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        try:
            async with self._http.stream(
                method, path, json=body, headers=self._headers()
            ) as response:
                if response.status_code not in (200, 201, 202):
                    raise KataApiError(
                        f"Kubernetes operation failed with HTTP {response.status_code}"
                    )
                content = bytearray()
                async for block in response.aiter_bytes():
                    if len(content) + len(block) > 2 * 1024**2:
                        raise KataApiError("Kubernetes metadata exceeds the response limit")
                    content.extend(block)
        except httpx.HTTPError as exc:
            raise KataApiError("Kubernetes request transport failed") from exc
        try:
            payload = json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise KataApiError("Kubernetes returned invalid JSON metadata") from exc
        if not isinstance(payload, dict):
            raise KataApiError("Kubernetes metadata must be an object")
        return payload

    async def stdout(self, namespace: str, pod_name: str, limit: int) -> tuple[bytes, bool]:
        path = f"/api/v1/namespaces/{namespace}/pods/{pod_name}/log?container=scanner"
        result = bytearray()
        try:
            async with self._http.stream("GET", path, headers=self._headers()) as response:
                if response.status_code != 200:
                    raise KataApiError(f"Kubernetes stdout failed with HTTP {response.status_code}")
                async for block in response.aiter_bytes():
                    available = limit + 1 - len(result)
                    result.extend(block[:available])
                    if len(result) > limit:
                        return bytes(result[:limit]), True
        except httpx.HTTPError as exc:
            raise KataApiError("Kubernetes stdout transport failed") from exc
        return bytes(result), False

    async def aclose(self) -> None:
        await self._http.aclose()
