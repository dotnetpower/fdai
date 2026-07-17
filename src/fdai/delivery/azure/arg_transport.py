"""Authenticated, bounded Azure Resource Graph HTTP pagination."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.workload_identity import WorkloadIdentity


async def fetch_arg_pages(
    *,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    audience: str,
    endpoint: str,
    api_version: str,
    subscriptions: tuple[str, ...],
    query: str,
    resource_type: str,
    page_size: int,
    max_pages: int,
    timeout_seconds: float,
    error_type: type[RuntimeError],
    map_row: Callable[[Mapping[str, Any]], ResourceRecord | None],
    project_links: Callable[[Mapping[str, Any], ResourceRecord], tuple[LinkRecord, ...]],
) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
    """Fetch all pages for one shard without silently accepting a partial result."""
    url = (
        f"{endpoint.rstrip('/')}"
        "/providers/Microsoft.ResourceGraph/resources"
        f"?api-version={api_version}"
    )
    token = await identity.get_token(audience)
    headers = {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    collected: list[ResourceRecord] = []
    collected_links: list[LinkRecord] = []
    skip_token: str | None = None

    for page in range(max_pages):
        body: dict[str, Any] = {
            "subscriptions": list(subscriptions),
            "query": query,
            "options": {"$top": page_size},
        }
        if skip_token is not None:
            body["options"]["$skipToken"] = skip_token

        try:
            response = await http_client.post(
                url,
                headers=headers,
                content=json.dumps(body),
                timeout=timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise error_type(
                f"ARG request failed for {resource_type!r} (page {page}): {exc}"
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise error_type(
                f"ARG returned HTTP {response.status_code} for {resource_type!r} "
                f"(page {page}): {snippet!r}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise error_type(f"ARG returned non-JSON for {resource_type!r} (page {page})") from exc

        data = payload.get("data")
        if not isinstance(data, list):
            raise error_type(
                f"ARG payload missing 'data' array for {resource_type!r} (page {page})"
            )

        for row in data:
            if not isinstance(row, Mapping):
                continue
            record = map_row(row)
            if record is not None:
                collected.append(record)
                collected_links.extend(project_links(row, record))

        next_token = payload.get("$skipToken")
        if not isinstance(next_token, str) or not next_token:
            break
        skip_token = next_token
    else:
        raise error_type(
            f"ARG pagination cap ({max_pages}) exceeded for {resource_type!r}; "
            "narrow the query or raise max_pages via config"
        )

    return tuple(collected), tuple(collected_links)
