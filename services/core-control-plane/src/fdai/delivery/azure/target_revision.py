"""Azure Resource Manager revision reads that pin a development approval to exact target state."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from fdai.delivery.azure.alert_noise_http import AZURE_ALERT_APIS
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ORIGIN = "https://management.azure.com"
_AUDIENCE = _ORIGIN + "/.default"
_MAX_BYTES = 1_000_000
_RESOURCE = re.compile(
    r"^/subscriptions/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
    r"/resourceGroups/[A-Za-z0-9_.()-]{1,90}"
    r"/providers/(?P<type>[A-Za-z0-9.]{1,100}/[A-Za-z0-9]{1,100})/[A-Za-z0-9_.()-]{1,260}$"
)
REVISION_API_VERSIONS = {
    resource_type: version
    for resource_type, version in AZURE_ALERT_APIS.items()
    if resource_type != "Microsoft.AlertsManagement/alerts"
}
_REVISION_FIELDS = ("id", "type", "location", "tags", "properties")


def revision_digest(body: Mapping[str, Any]) -> str:
    """Digest the provider ETag, or the complete configuration when the type has none."""
    etag = body.get("etag")
    material = (
        {"etag": etag}
        if isinstance(etag, str) and etag.strip()
        else {field: body.get(field) for field in _REVISION_FIELDS}
    )
    canonical = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AzureTargetRevisionReader:
    """Read one pinned resource by exact ID; any doubt establishes no revision."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        identity: WorkloadIdentity,
        timeout_seconds: float = 10.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("revision read timeout MUST be between 0 and 30 seconds")
        self._http, self._identity = http, identity
        self._timeout, self._clock = timeout_seconds, clock

    async def read_revision(self, target_ref: str) -> str | None:
        """Return the exact current revision digest of ``target_ref``, or ``None``."""
        match = _RESOURCE.fullmatch(target_ref)
        if match is None:
            return None
        resource_type = match.group("type").casefold()
        version = next(
            (
                api_version
                for name, api_version in REVISION_API_VERSIONS.items()
                if name.casefold() == resource_type
            ),
            None,
        )
        if version is None:
            return None
        try:
            token = await self._identity.get_token(_AUDIENCE)
        except Exception:  # noqa: BLE001 - an unavailable identity establishes no revision
            return None
        if (
            token.audience != _AUDIENCE
            or not token.token
            or token.expires_at.tzinfo is None
            or token.expires_at <= self._clock()
        ):
            return None
        try:
            response = await self._http.get(
                _ORIGIN + target_ref,
                params={"api-version": version},
                headers={"Authorization": f"Bearer {token.token}", "Accept": "application/json"},
                timeout=self._timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or len(response.content) > _MAX_BYTES:
            return None
        try:
            body = json.loads(response.content)
        except ValueError:
            return None
        if (
            not isinstance(body, dict)
            or str(body.get("id", "")).casefold() != target_ref.casefold()
        ):
            return None
        return revision_digest(body)


__all__ = ["REVISION_API_VERSIONS", "AzureTargetRevisionReader", "revision_digest"]
