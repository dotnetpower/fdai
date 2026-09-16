"""Bounded Microsoft Graph person lookup for stewardship drafts."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from fdai_service_contracts import (
    ReportingLineManagerObservation,
    ReportingLineManagerStatus,
    ReportingLineResolvedIdentity,
    ResolvedStewardIdentity,
    StewardKind,
)

_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class GraphPersonDirectory:
    """Resolve exactly one enabled user or group and abstain on ambiguity."""

    def __init__(
        self,
        *,
        credential: AsyncTokenCredential,
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


class GraphReportingLineDirectory:
    """Resolve one active user and read their current manager without mutation."""

    def __init__(
        self,
        *,
        credential: AsyncTokenCredential,
        client: httpx.AsyncClient,
        base_url: str = "https://graph.microsoft.com/v1.0",
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("Graph base URL MUST be an HTTPS origin with a path")
        self._credential = credential
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def resolve(self, display_name: str) -> ReportingLineResolvedIdentity | None:
        normalized = display_name.strip()
        if len(normalized) < 2 or len(normalized) > 128:
            return None
        token = await self._credential.get_token(_GRAPH_SCOPE)
        escaped = normalized.replace("'", "''")
        response = await self._client.get(
            f"{self._base_url}/users",
            params={
                "$select": "id,displayName,accountEnabled",
                "$filter": f"displayName eq '{escaped}'",
                "$top": "2",
            },
            headers={"Authorization": f"Bearer {token.token}"},
        )
        response.raise_for_status()
        payload = response.json()
        values = payload.get("value") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            raise RuntimeError("Microsoft Graph user response has no value array")
        matches = [
            item
            for item in values
            if isinstance(item, dict)
            and item.get("displayName") == normalized
            and item.get("accountEnabled") is True
            and isinstance(item.get("id"), str)
            and item["id"]
        ]
        if len(matches) != 1:
            return None
        return ReportingLineResolvedIdentity(oid=str(matches[0]["id"]))

    async def manager_for(self, subject_oid: str) -> ReportingLineManagerObservation:
        normalized = subject_oid.strip()
        if (
            not normalized
            or len(normalized) > 256
            or any(char not in "0123456789abcdefABCDEF-" for char in normalized)
        ):
            return ReportingLineManagerObservation(status=ReportingLineManagerStatus.UNAVAILABLE)
        token = await self._credential.get_token(_GRAPH_SCOPE)
        response = await self._client.get(
            f"{self._base_url}/users/{normalized}/manager",
            params={"$select": "id"},
            headers={"Authorization": f"Bearer {token.token}"},
        )
        if response.status_code == 404:
            return ReportingLineManagerObservation(status=ReportingLineManagerStatus.NOT_FOUND)
        response.raise_for_status()
        payload = response.json()
        manager_oid = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(manager_oid, str) or not manager_oid:
            raise RuntimeError("Microsoft Graph manager response has no exact id")
        return ReportingLineManagerObservation(
            status=ReportingLineManagerStatus.RESOLVED,
            manager_oid=manager_oid,
        )


__all__ = ["GraphPersonDirectory", "GraphReportingLineDirectory"]
