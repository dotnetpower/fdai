"""Bounded Microsoft Graph person lookup for stewardship drafts."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts import ResolvedStewardIdentity, StewardKind

_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class GraphPersonDirectory:
    """Resolve exactly one enabled user or group and abstain on ambiguity."""

    def __init__(
        self,
        *,
        credential: ManagedIdentityCredential,
        client: httpx.AsyncClient,
        base_url: str = "https://graph.microsoft.com/v1.0",
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("Graph base URL MUST be an HTTPS origin with a path")
        self._credential = credential
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def resolve(self, display_name: str) -> ResolvedStewardIdentity | None:
        normalized = display_name.strip()
        if len(normalized) < 2 or len(normalized) > 128:
            return None
        token = await self._credential.get_token(_GRAPH_SCOPE)
        escaped = normalized.replace("'", "''")
        headers = {"Authorization": f"Bearer {token.token}"}
        matches: list[ResolvedStewardIdentity] = []
        for resource, kind, select in (
            ("users", StewardKind.USER, "id,displayName,accountEnabled"),
            ("groups", StewardKind.GROUP, "id,displayName"),
        ):
            response = await self._client.get(
                f"{self._base_url}/{resource}",
                params={
                    "$select": select,
                    "$filter": f"displayName eq '{escaped}'",
                    "$top": "2",
                },
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            values = payload.get("value") if isinstance(payload, dict) else None
            if not isinstance(values, list):
                raise RuntimeError("Microsoft Graph directory response has no value array")
            for value in values:
                if not isinstance(value, dict):
                    continue
                if kind is StewardKind.USER and value.get("accountEnabled") is not True:
                    continue
                oid = value.get("id")
                if isinstance(oid, str) and oid and value.get("displayName") == normalized:
                    matches.append(ResolvedStewardIdentity(oid=oid, kind=kind))
        return matches[0] if len(matches) == 1 else None
