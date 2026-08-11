"""Bounded Azure control-plane and metadata transport for live preflight."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

_ARM_ENDPOINT = "https://management.azure.com"
_ARM_AUDIENCE = "https://management.azure.com"
_VAULT_AUDIENCE = "https://vault.azure.net"


class PreflightError(RuntimeError):
    """The live preflight could not produce a complete result."""


class AzureReader(Protocol):
    """Read-only Azure operations required by the deployment preflight."""

    def get_json(self, path: str, *, api_version: str) -> dict[str, Any]: ...

    def get_values(
        self,
        path: str,
        *,
        api_version: str,
        params: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]: ...

    def query_role_assignments(
        self, *, subscription_id: str, principal_id: str
    ) -> list[dict[str, Any]]: ...

    def secret_status(self, *, vault_endpoint: str, secret_name: str) -> int: ...


class AzureCliReader:
    """Read Azure control and data planes with short-lived Azure CLI tokens."""

    def __init__(self, *, subscription_id: str, timeout_seconds: int = 20) -> None:
        self._subscription_id = subscription_id
        self._timeout_seconds = timeout_seconds
        self._tokens: dict[str, str] = {}

    def get_json(self, path: str, *, api_version: str) -> dict[str, Any]:
        url = f"{_ARM_ENDPOINT}{path}?{urlencode({'api-version': api_version})}"
        status, payload = self._request_json(url, audience=_ARM_AUDIENCE)
        if status >= 400 or not isinstance(payload, dict):
            raise PreflightError("Azure Resource Manager read failed")
        return payload

    def get_values(
        self,
        path: str,
        *,
        api_version: str,
        params: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        query = {"api-version": api_version, **dict(params or {})}
        url: str | None = f"{_ARM_ENDPOINT}{path}?{urlencode(query)}"
        values: list[dict[str, Any]] = []
        pages = 0
        while url:
            pages += 1
            if pages > 32:
                raise PreflightError("Azure Resource Manager pagination exceeded its bound")
            status, payload = self._request_json(url, audience=_ARM_AUDIENCE)
            if status >= 400 or not isinstance(payload, dict):
                raise PreflightError("Azure Resource Manager collection read failed")
            page = payload.get("value")
            if not isinstance(page, list):
                raise PreflightError("Azure Resource Manager collection is incomplete")
            values.extend(item for item in page if isinstance(item, dict))
            next_link = payload.get("nextLink")
            url = next_link if isinstance(next_link, str) and next_link else None
        return values

    def query_role_assignments(
        self, *, subscription_id: str, principal_id: str
    ) -> list[dict[str, Any]]:
        query = (
            "AuthorizationResources "
            "| where type =~ 'microsoft.authorization/roleassignments' "
            f"| where tostring(properties.principalId) =~ '{principal_id}' "
            "| project roleDefinitionId=tostring(properties.roleDefinitionId), "
            "scope=tostring(properties.scope)"
        )
        body = {
            "subscriptions": [subscription_id],
            "query": query,
            "options": {"resultFormat": "objectArray", "$top": 1000},
        }
        url = f"{_ARM_ENDPOINT}/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
        status, payload = self._request_json(
            url,
            audience=_ARM_AUDIENCE,
            method="POST",
            body=body,
        )
        if status >= 400 or not isinstance(payload, dict):
            raise PreflightError("Azure Resource Graph role read failed")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise PreflightError("Azure Resource Graph role result is incomplete")
        return [row for row in rows if isinstance(row, dict)]

    def secret_status(self, *, vault_endpoint: str, secret_name: str) -> int:
        url = f"{vault_endpoint.rstrip('/')}/secrets/{quote(secret_name, safe='')}?api-version=7.4"
        status, _payload = self._request_json(url, audience=_VAULT_AUDIENCE)
        return status

    def _request_json(
        self,
        url: str,
        *,
        audience: str,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
    ) -> tuple[int, Any]:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if parsed.scheme != "https" or not (
            hostname == "management.azure.com" or hostname.endswith(".vault.azure.net")
        ):
            raise PreflightError("Azure preflight URL is outside the approved hosts")
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(  # noqa: S310 - URL scheme and Azure host are validated above.
            url,
            data=encoded,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token(audience)}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                payload = response.read()
                return response.status, json.loads(payload) if payload else {}
        except HTTPError as exc:
            return exc.code, {}
        except (OSError, URLError, ValueError) as exc:
            raise PreflightError("Azure read did not return a complete result") from exc

    def _token(self, audience: str) -> str:
        token = self._tokens.get(audience)
        if token is not None:
            return token
        command = [
            "az",
            "account",
            "get-access-token",
            "--resource",
            audience,
            "--subscription",
            self._subscription_id,
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PreflightError("Azure CLI token acquisition failed") from exc
        token = completed.stdout.strip()
        if not token:
            raise PreflightError("Azure CLI returned an empty access token")
        self._tokens[audience] = token
        return token
