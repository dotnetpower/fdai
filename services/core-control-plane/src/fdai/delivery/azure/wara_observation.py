"""Bounded Azure Resource Graph observations for exact WARA evaluators."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.rule_catalog.schema.wara_assessment import WaraQueryCatalog, canonical_digest
from fdai.rule_catalog.schema.wara_evaluator_binding import (
    WaraEvaluatorBindingCatalog,
    WaraEvaluatorSemantics,
)
from fdai.shared.providers.wara_assessment import (
    WaraObservationError,
    WaraObservationReceipt,
    WaraReadPlan,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ARG_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_SUBSCRIPTION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_API_VERSION = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-preview)?$")
_ALLOWED_ARG_HOSTS = frozenset(
    {
        "management.azure.com",
        "management.azure.us",
        "management.chinacloudapi.cn",
        "management.microsoftazure.de",
    }
)
_ALLOWED_AUDIENCES = frozenset(f"https://{host}/.default" for host in _ALLOWED_ARG_HOSTS)


@dataclass(frozen=True, slots=True)
class AzureResourceGraphWaraConfig:
    """Static safety and transport bounds for WARA ARG observations."""

    endpoint: str = _DEFAULT_ARG_ENDPOINT
    api_version: str = _DEFAULT_ARG_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    maximum_pages: int = 4
    maximum_response_bytes: int = 1_000_000
    maximum_total_response_bytes: int = 2_000_000


class AzureResourceGraphWaraObservationProvider:
    """Execute reviewed WARA queries as read-only, exact-scope ARG observations."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        queries: WaraQueryCatalog,
        evaluator_bindings: WaraEvaluatorBindingCatalog,
        config: AzureResourceGraphWaraConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        resolved_config = config or AzureResourceGraphWaraConfig()
        endpoint = urlparse(resolved_config.endpoint)
        if (
            endpoint.scheme != "https"
            or endpoint.hostname not in _ALLOWED_ARG_HOSTS
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
            or endpoint.username is not None
            or endpoint.password is not None
        ):
            raise ValueError("WARA ARG endpoint MUST be an approved Azure management origin")
        if resolved_config.audience not in _ALLOWED_AUDIENCES:
            raise ValueError("WARA ARG audience MUST be an approved Azure management audience")
        if _API_VERSION.fullmatch(resolved_config.api_version) is None:
            raise ValueError("WARA ARG api_version MUST be a dated Azure API version")
        if resolved_config.maximum_pages < 1 or resolved_config.maximum_pages > 16:
            raise ValueError("WARA ARG maximum_pages MUST be between 1 and 16")
        if resolved_config.maximum_response_bytes < 1:
            raise ValueError("WARA ARG maximum_response_bytes MUST be positive")
        if resolved_config.maximum_total_response_bytes < resolved_config.maximum_response_bytes:
            raise ValueError("WARA ARG maximum_total_response_bytes MUST cover one response")
        if queries.source_revision != evaluator_bindings.source_revision:
            raise ValueError("WARA query and evaluator binding source revisions differ")
        query_by_key = {(query.aprl_guid, query.body_digest): query for query in queries.queries}
        if len(query_by_key) != len(queries.queries):
            raise ValueError("WARA query catalog contains duplicate exact query identities")

        self._identity = identity
        self._http = http_client
        self._queries = query_by_key
        self._bindings = evaluator_bindings
        self._config = resolved_config
        self._clock = clock or (lambda: datetime.now(UTC))

    async def observe(self, plan: WaraReadPlan) -> WaraObservationReceipt:
        """Return a complete deterministic receipt or fail closed without a verdict."""

        binding = self._bindings.resolve(plan.recommendation_id, plan.query_digest)
        if (
            binding is None
            or plan.evaluator_bindings_digest != self._bindings.overlay_digest
            or plan.evaluator_ref != binding.evaluator_ref
            or binding.semantics is not WaraEvaluatorSemantics.MATCHING_ROWS_FAILED
        ):
            raise WaraObservationError("WARA read plan has no exact reviewed evaluator binding")
        query_record = self._queries.get((plan.recommendation_id, plan.query_digest))
        if query_record is None:
            raise WaraObservationError("WARA read plan has no exact query body")

        subscriptions = _validate_exact_resource_scope(plan)
        scoped_query = _scope_query(
            query_record.decoded_body(),
            resource_ids=plan.resource_ids,
            maximum_rows=plan.maximum_rows,
        )
        try:
            async with asyncio.timeout(plan.timeout_seconds):
                rows = await self._fetch_rows(
                    plan=plan,
                    subscriptions=subscriptions,
                    query=scoped_query,
                )
        except TimeoutError as exc:
            raise WaraObservationError(
                "WARA ARG observation exceeded the read-plan deadline"
            ) from exc
        normalized_rows = _validate_and_normalize_rows(
            rows,
            resource_ids=plan.resource_ids,
            resource_id_column=binding.resource_id_column,
        )
        evidence_digest = canonical_digest(
            {
                "evaluator_bindings_digest": plan.evaluator_bindings_digest,
                "evaluator_ref": plan.evaluator_ref,
                "inventory_generation": plan.inventory_generation,
                "query_digest": plan.query_digest,
                "recommendation_id": plan.recommendation_id,
                "resource_ids": list(plan.resource_ids),
                "rows": normalized_rows,
                "semantics": binding.semantics.value,
                "workload_id": plan.workload_id,
            }
        )
        observed_at = self._clock()
        if observed_at.tzinfo is None:
            raise WaraObservationError("WARA observation clock MUST be timezone-aware")
        return WaraObservationReceipt(
            recommendation_id=plan.recommendation_id,
            query_digest=plan.query_digest,
            evaluator_ref=plan.evaluator_ref,
            evaluator_bindings_digest=plan.evaluator_bindings_digest,
            workload_id=plan.workload_id,
            resource_ids=plan.resource_ids,
            inventory_generation=plan.inventory_generation,
            observed_at=observed_at,
            recorded_at=observed_at,
            evidence_digest=evidence_digest,
            complete=True,
            truncated=False,
            conflicting=False,
            synthetic=False,
            satisfied=not normalized_rows,
        )

    async def _fetch_rows(
        self,
        *,
        plan: WaraReadPlan,
        subscriptions: tuple[str, ...],
        query: str,
    ) -> tuple[Mapping[str, Any], ...]:
        url = (
            f"{self._config.endpoint.rstrip('/')}"
            "/providers/Microsoft.ResourceGraph/resources"
            f"?api-version={self._config.api_version}"
        )
        try:
            token = await self._identity.get_token(self._config.audience)
        except Exception as exc:  # noqa: BLE001 - identity boundary fails closed
            raise WaraObservationError(
                f"WARA ARG identity request failed: {type(exc).__name__}"
            ) from exc
        if token.audience != self._config.audience or not token.token:
            raise WaraObservationError("WARA ARG identity returned an invalid audience token")

        rows: list[Mapping[str, Any]] = []
        skip_token: str | None = None
        seen_tokens: set[str] = set()
        total_bytes = 0
        for page in range(self._config.maximum_pages):
            options: dict[str, object] = {"$top": min(plan.maximum_rows + 1, 1000)}
            if skip_token is not None:
                options["$skipToken"] = skip_token
            body = {
                "subscriptions": list(subscriptions),
                "query": query,
                "options": options,
            }
            try:
                response = await self._http.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token.token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    content=json.dumps(body, sort_keys=True, separators=(",", ":")),
                    timeout=plan.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise WaraObservationError(
                    f"WARA ARG request failed on page {page}: {type(exc).__name__}"
                ) from exc
            if response.status_code >= 400:
                raise WaraObservationError(
                    f"WARA ARG returned HTTP {response.status_code} on page {page}"
                )
            response_bytes = len(response.content)
            if response_bytes > self._config.maximum_response_bytes:
                raise WaraObservationError("WARA ARG response exceeded the per-page byte bound")
            total_bytes += response_bytes
            if total_bytes > self._config.maximum_total_response_bytes:
                raise WaraObservationError("WARA ARG response exceeded the total byte bound")
            payload = _response_object(response, page)
            page_rows = payload.get("data")
            if not isinstance(page_rows, list):
                raise WaraObservationError(f"WARA ARG payload missing data array on page {page}")
            for row in page_rows:
                if not isinstance(row, Mapping):
                    raise WaraObservationError(
                        f"WARA ARG payload contained a non-object row on page {page}"
                    )
                rows.append(row)
            if len(rows) > plan.maximum_rows:
                raise WaraObservationError("WARA ARG result exceeded the read-plan row bound")

            next_token = payload.get("$skipToken")
            if not isinstance(next_token, str) or not next_token:
                if payload.get("resultTruncated") is True or _count_is_truncated(payload):
                    raise WaraObservationError(
                        "WARA ARG returned a truncated result without a continuation token"
                    )
                return tuple(rows)
            if next_token in seen_tokens:
                raise WaraObservationError("WARA ARG continuation token did not advance")
            seen_tokens.add(next_token)
            skip_token = next_token
        raise WaraObservationError("WARA ARG pagination exceeded the configured page bound")


def _validate_exact_resource_scope(plan: WaraReadPlan) -> tuple[str, ...]:
    expected_types = {item.casefold() for item in plan.provider_resource_types}
    subscriptions: set[str] = set()
    folded_ids: set[str] = set()
    for resource_id in plan.resource_ids:
        if len(resource_id) > 2048 or "'" in resource_id:
            raise WaraObservationError("WARA resource scope contains an invalid resource id")
        folded = resource_id.casefold()
        if folded in folded_ids:
            raise WaraObservationError("WARA resource scope contains case-equivalent duplicates")
        folded_ids.add(folded)
        segments = tuple(segment for segment in resource_id.strip("/").split("/") if segment)
        if (
            len(segments) < 8
            or segments[0].casefold() != "subscriptions"
            or _SUBSCRIPTION_ID.fullmatch(segments[1]) is None
        ):
            raise WaraObservationError("WARA resource scope requires exact ARM resource ids")
        try:
            provider_index = max(
                index for index, segment in enumerate(segments) if segment.casefold() == "providers"
            )
        except ValueError as exc:
            raise WaraObservationError(
                "WARA resource scope requires provider-qualified ARM ids"
            ) from exc
        provider_segments = segments[provider_index + 1 :]
        if len(provider_segments) < 3 or len(provider_segments) % 2 == 0:
            raise WaraObservationError("WARA resource scope has an invalid provider path")
        provider_type = "/".join((provider_segments[0], *provider_segments[1::2])).casefold()
        if provider_type not in expected_types:
            raise WaraObservationError(
                "WARA resource scope does not match the read-plan provider type"
            )
        subscriptions.add(segments[1])
    return tuple(sorted(subscriptions, key=str.casefold))


def _scope_query(
    query: str,
    *,
    resource_ids: tuple[str, ...],
    maximum_rows: int,
) -> str:
    scope = json.dumps(
        [resource_id.casefold() for resource_id in resource_ids],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return (
        f"let _fdai_wara_scope = dynamic({scope});\n"
        f"{query.rstrip()}\n"
        "| where set_has_element(_fdai_wara_scope, tolower(tostring(id)))\n"
        f"| take {maximum_rows + 1}"
    )


def _response_object(response: httpx.Response, page: int) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise WaraObservationError(f"WARA ARG returned non-JSON on page {page}") from exc
    if not isinstance(payload, Mapping):
        raise WaraObservationError(f"WARA ARG payload was not an object on page {page}")
    return payload


def _validate_and_normalize_rows(
    rows: tuple[Mapping[str, Any], ...],
    *,
    resource_ids: tuple[str, ...],
    resource_id_column: str,
) -> list[object]:
    admitted_ids = {resource_id.casefold() for resource_id in resource_ids}
    normalized: list[object] = []
    for row in rows:
        resource_id = row.get(resource_id_column)
        if not isinstance(resource_id, str) or resource_id.casefold() not in admitted_ids:
            raise WaraObservationError("WARA ARG returned a row outside the exact resource scope")
        normalized.append(json.loads(json.dumps(row, sort_keys=True, separators=(",", ":"))))
    return sorted(
        normalized,
        key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")),
    )


def _count_is_truncated(payload: Mapping[str, Any]) -> bool:
    count = payload.get("count")
    total = payload.get("totalRecords")
    return (
        isinstance(count, int)
        and not isinstance(count, bool)
        and isinstance(total, int)
        and not isinstance(total, bool)
        and count < total
    )


__all__ = [
    "AzureResourceGraphWaraConfig",
    "AzureResourceGraphWaraObservationProvider",
]
