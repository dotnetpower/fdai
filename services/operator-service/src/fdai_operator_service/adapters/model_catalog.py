"""Bounded, read-only Azure model configuration discovery for Settings."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

_LOGGER = logging.getLogger(__name__)
_ORIGIN = "https://management.azure.com"
_API_VERSION = "2024-10-01"
_MAX_BYTES = 4_194_304
_MAX_ROWS = 5_000


class ModelCatalogUnavailableError(RuntimeError):
    """A content-free discovery failure safe for logs and the Settings projection."""


class AzureModelCatalogReader:
    """Read only one configured account, with bounded pages and no automatic retries."""

    def __init__(
        self,
        *,
        subscription_id: str,
        endpoint: str,
        token_provider: Callable[[], Awaitable[str]],
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._subscription = str(UUID(subscription_id))
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("model catalog endpoint MUST be an HTTPS origin")
        self._hostname = parsed.hostname
        self._token_provider = token_provider
        self._transport = transport
        self._clock = clock
        self._lock = asyncio.Lock()
        self._cached: dict[str, object] | None = None
        self._expires_at = 0.0

    async def read(self, *, refresh: bool = False) -> Mapping[str, object]:
        """Return current catalog metadata or an explicit unavailable outcome."""
        try:
            async with asyncio.timeout(20):
                return await self._read_locked(refresh=refresh)
        except TimeoutError:
            return self._unavailable("catalog_deadline_exceeded")

    async def _read_locked(self, *, refresh: bool) -> Mapping[str, object]:
        async with self._lock:
            if not refresh and self._cached is not None and self._clock() < self._expires_at:
                return copy.deepcopy(self._cached)
            try:
                async with asyncio.timeout(18):
                    result = await self._discover()
            except (ModelCatalogUnavailableError, httpx.HTTPError, TimeoutError, ValueError) as exc:
                reason = (
                    str(exc)
                    if isinstance(exc, ModelCatalogUnavailableError)
                    else type(exc).__name__
                )
                result = self._unavailable(reason)
            self._cached = result
            self._expires_at = self._clock() + 60
            return copy.deepcopy(result)

    @staticmethod
    def _unavailable(reason: str) -> dict[str, object]:
        _LOGGER.warning("model_catalog_unavailable", extra={"reason": reason})
        return {
            "available": False,
            "source": "azure-management-catalog",
            "region": None,
            "models": [],
            "unavailable_reason": reason,
        }

    async def _discover(self) -> dict[str, object]:
        token = await self._token_provider()
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=10,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            root = f"/subscriptions/{self._subscription}"
            accounts = await self._rows(
                client, f"{root}/providers/Microsoft.CognitiveServices/accounts"
            )
            matching = [
                row
                for row in accounts
                if urlsplit(str(_mapping(row.get("properties")).get("endpoint", ""))).hostname
                == self._hostname
            ]
            if len(matching) != 1:
                raise ModelCatalogUnavailableError("configured_account_not_unique")
            account = matching[0]
            account_id = str(account.get("id", ""))
            if not re.fullmatch(
                re.escape(root)
                + r"/resourceGroups/[A-Za-z0-9_.()-]+"
                + r"/providers/Microsoft.CognitiveServices/accounts/[A-Za-z0-9-]+",
                account_id,
                flags=re.IGNORECASE,
            ):
                raise ModelCatalogUnavailableError("account_scope_mismatch")
            region = str(account.get("location", ""))
            if not re.fullmatch(r"[a-z0-9]+", region):
                raise ModelCatalogUnavailableError("account_region_invalid")
            models = await self._rows(client, f"{account_id}/models")
            deployments = await self._rows(client, f"{account_id}/deployments")
            usages = await self._rows(
                client, f"{root}/providers/Microsoft.CognitiveServices/locations/{region}/usages"
            )
        return {
            "available": True,
            "source": "azure-management-catalog",
            "region": region,
            "as_of": datetime.now(UTC).isoformat(),
            "models": _catalog_models(models, deployments, usages),
        }

    @staticmethod
    async def _rows(client: httpx.AsyncClient, path: str) -> list[dict[str, Any]]:
        url = f"{_ORIGIN}{path}?api-version={_API_VERSION}"
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_bytes = 0
        for _ in range(5):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "management.azure.com"
                or parsed.path != path
                or parsed.fragment
                or url in seen
            ):
                raise ModelCatalogUnavailableError("catalog_pagination_invalid")
            seen.add(url)
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise ModelCatalogUnavailableError(f"catalog_http_{response.status_code}")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_BYTES:
                        raise ModelCatalogUnavailableError("catalog_response_too_large")
                    body.extend(chunk)
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                raise ModelCatalogUnavailableError("catalog_response_invalid")
            if any(not isinstance(row, dict) for row in payload["value"]):
                raise ModelCatalogUnavailableError("catalog_row_invalid")
            rows.extend(payload["value"])
            if len(rows) > _MAX_ROWS:
                raise ModelCatalogUnavailableError("catalog_row_limit")
            next_link = payload.get("nextLink")
            if not next_link:
                return rows
            if not isinstance(next_link, str):
                raise ModelCatalogUnavailableError("catalog_pagination_invalid")
            url = next_link
        raise ModelCatalogUnavailableError("catalog_page_limit")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _catalog_models(
    models: list[dict[str, Any]],
    deployments: list[dict[str, Any]],
    usages: list[dict[str, Any]],
) -> list[dict[str, object]]:
    quota: dict[str, float] = {}
    for row in usages:
        name = _mapping(row.get("name")).get("value")
        used, limit = row.get("currentValue"), row.get("limit")
        if (
            isinstance(name, str)
            and isinstance(used, (int, float))
            and not isinstance(used, bool)
            and isinstance(limit, (int, float))
            and not isinstance(limit, bool)
            and math.isfinite(used)
            and math.isfinite(limit)
            and used >= 0
            and limit >= 0
        ):
            quota[name] = max(0, limit - used) * 1000
    deployed: dict[tuple[str, str], list[str]] = {}
    for row in deployments:
        properties = _mapping(row.get("properties"))
        model = _mapping(properties.get("model"))
        name = row.get("name")
        if (
            properties.get("provisioningState") == "Succeeded"
            and model.get("format") == "OpenAI"
            and isinstance(name, str)
        ):
            key = (str(model.get("name")), str(model.get("version")))
            deployed.setdefault(key, []).append(name)
    result: list[dict[str, object]] = []
    for model in models:
        family, version = model.get("name"), model.get("version")
        if (
            model.get("format") != "OpenAI"
            or not isinstance(family, str)
            or not isinstance(version, str)
        ):
            continue
        skus = [
            {"name": sku["name"], "available_tpm": quota.get(str(sku.get("usageName")), 0)}
            for sku in model.get("skus") or []
            if isinstance(sku, dict)
            and sku.get("name") in {"Standard", "GlobalStandard", "DataZoneStandard"}
        ]
        capacity = max((float(sku["available_tpm"]) for sku in skus), default=0)
        names = sorted(deployed.get((family, version), []))
        result.append(
            {
                "publisher": "OpenAI",
                "family": family,
                "version": version,
                "lifecycle": str(model.get("lifecycleStatus") or "unknown"),
                "skus": skus,
                "available_tpm": capacity,
                "deployments": names,
                "deployed": bool(names),
                "provisionable": capacity > 0,
                "selectable": bool(names) or capacity > 0,
                "status": "deployed"
                if names
                else "provisionable"
                if capacity > 0
                else "quota-unavailable",
            }
        )
    return sorted(result, key=lambda row: (str(row["family"]), str(row["version"])))
