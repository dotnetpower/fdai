"""Bounded Azure Activity Log deployment history for exact inventory targets."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

import httpx

from fdai.shared.providers.observation import (
    DeploymentHistoryError,
    DeploymentHistoryResult,
    DeploymentRecord,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT = "https://management.azure.com"
_DEFAULT_AUDIENCE = "https://management.azure.com/.default"
_DEFAULT_API_VERSION = "2015-04-01"
_ALLOWED_HOSTS = frozenset(
    {
        "management.azure.com",
        "management.azure.us",
        "management.usgovcloudapi.net",
        "management.chinacloudapi.cn",
        "management.microsoftazure.de",
    }
)
_AUDIENCE_BY_HOST = {host: f"https://{host}/.default" for host in _ALLOWED_HOSTS}
_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)
_SUBSCRIPTION_PATH = re.compile(
    r"^/subscriptions/(?P<subscription>[0-9a-f]{8}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)",
    re.IGNORECASE,
)
_SUCCESS_STATUSES = frozenset({"succeeded", "success"})
_MUTATION_SUFFIXES = ("/action", "/delete", "/write")
_MAX_WINDOW_SECONDS = 31 * 86_400
_MAX_PAGE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 16 * 1024 * 1024


class AzureResourceIdentityError(RuntimeError):
    """A neutral resource ref cannot be resolved safely to an Azure identity."""


@dataclass(frozen=True, slots=True)
class AzureResolvedResourceIdentity:
    """Exact provider identity and inventory generation for one neutral resource."""

    provider_resource_id: str
    inventory_generation: str

    def __post_init__(self) -> None:
        if not self.provider_resource_id.strip() or not self.inventory_generation.strip():
            raise ValueError("Azure resolved resource identity fields MUST be non-empty")


class AzureResourceIdentityResolver(Protocol):
    """Resolve one server-owned neutral resource ref to an exact ARM id."""

    async def resolve(
        self,
        resource_ref: str,
        *,
        at: datetime | None = None,
    ) -> AzureResolvedResourceIdentity | None: ...


@dataclass(frozen=True, slots=True)
class AzureDeploymentHistoryConfig:
    """Static Azure endpoint and response bounds."""

    endpoint: str = _DEFAULT_ENDPOINT
    audience: str = _DEFAULT_AUDIENCE
    api_version: str = _DEFAULT_API_VERSION
    timeout_seconds: float = 15.0
    maximum_pages: int = 4
    maximum_records: int = 100
    maximum_response_bytes: int = 1_000_000
    maximum_total_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        endpoint = urlparse(self.endpoint)
        if (
            endpoint.scheme != "https"
            or endpoint.hostname not in _ALLOWED_HOSTS
            or endpoint.port not in {None, 443}
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
            or endpoint.username is not None
            or endpoint.password is not None
        ):
            raise ValueError("deployment history endpoint MUST be an approved Azure origin")
        if self.audience != _AUDIENCE_BY_HOST[endpoint.hostname]:
            raise ValueError("deployment history audience MUST match the Azure endpoint cloud")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", self.api_version):
            raise ValueError("deployment history api_version MUST be a dated Azure API version")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("deployment history timeout_seconds MUST be in [0.1, 30]")
        if not 1 <= self.maximum_pages <= 16:
            raise ValueError("deployment history maximum_pages MUST be in [1, 16]")
        if not 1 <= self.maximum_records <= 1_000:
            raise ValueError("deployment history maximum_records MUST be in [1, 1000]")
        if not 1 <= self.maximum_response_bytes <= _MAX_PAGE_BYTES:
            raise ValueError("deployment history per-page byte bound is invalid")
        if not (
            self.maximum_response_bytes <= self.maximum_total_response_bytes <= _MAX_TOTAL_BYTES
        ):
            raise ValueError("deployment history total byte bound is invalid")


class AzureActivityDeploymentHistoryProvider:
    """Read successful Azure control-plane mutations for one exact inventory target."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        resource_identities: AzureResourceIdentityResolver,
        http_client: httpx.AsyncClient,
        config: AzureDeploymentHistoryConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._identity = identity
        self._resource_identities = resource_identities
        self._http = http_client
        self._config = config or AzureDeploymentHistoryConfig()
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def query_deployments(
        self,
        *,
        window: str,
        resource_ref: str | None = None,
    ) -> DeploymentHistoryResult:
        return await self._query_deployments(
            window=window,
            resource_ref=resource_ref,
            until=None,
        )

    async def query_deployments_until(
        self,
        *,
        window: str,
        resource_ref: str | None,
        until: datetime,
    ) -> DeploymentHistoryResult:
        """Return deployment history at one explicit incident cutoff."""

        return await self._query_deployments(
            window=window,
            resource_ref=resource_ref,
            until=until,
        )

    async def _query_deployments(
        self,
        *,
        window: str,
        resource_ref: str | None,
        until: datetime | None,
    ) -> DeploymentHistoryResult:
        """Return bounded successful mutations or raise on incomplete evidence."""

        if resource_ref is None or not resource_ref.strip() or len(resource_ref) > 1_024:
            raise DeploymentHistoryError("deployment history requires one exact resource ref")
        duration = _parse_window(window)
        current_time = self._clock()
        if current_time.tzinfo is None:
            raise DeploymentHistoryError("deployment history clock MUST be timezone-aware")
        observed_at = current_time if until is None else until
        if observed_at.tzinfo is None:
            raise DeploymentHistoryError("deployment history cutoff MUST be timezone-aware")
        if observed_at > current_time:
            raise DeploymentHistoryError("deployment history cutoff MUST NOT be in the future")
        try:
            resolved = await self._resource_identities.resolve(
                resource_ref,
                at=observed_at if until is not None else None,
            )
        except AzureResourceIdentityError as exc:
            raise DeploymentHistoryError("deployment resource identity is unavailable") from exc
        if resolved is None:
            raise DeploymentHistoryError("deployment resource identity is unavailable")
        provider_id = _validate_arm_id(resolved.provider_resource_id)
        subscription_id = _subscription_id(provider_id)
        lower = observed_at - duration
        rows = await self._fetch_activity_rows(
            provider_id=provider_id,
            subscription_id=subscription_id,
            lower=lower,
            upper=observed_at,
        )
        records = _deployment_records(
            rows,
            provider_id=provider_id,
            resource_ref=resource_ref,
            inventory_generation=resolved.inventory_generation,
            lower=lower,
            upper=observed_at,
            maximum_records=self._config.maximum_records,
        )
        return DeploymentHistoryResult(records=records, window=window.strip().upper())

    async def _fetch_activity_rows(
        self,
        *,
        provider_id: str,
        subscription_id: str,
        lower: datetime,
        upper: datetime,
    ) -> tuple[Mapping[str, Any], ...]:
        path = (
            f"/subscriptions/{subscription_id}/"
            "providers/Microsoft.Insights/eventtypes/management/values"
        )
        first_url = f"{self._config.endpoint.rstrip('/')}{path}"
        filter_value = (
            f"eventTimestamp ge '{_azure_time(lower)}' and "
            f"eventTimestamp le '{_azure_time(upper)}' and "
            f"resourceUri eq '{_odata_literal(provider_id)}'"
        )
        try:
            token = await self._identity.get_token(self._config.audience)
        except Exception as exc:  # noqa: BLE001 - identity boundary fails closed
            raise DeploymentHistoryError(
                f"deployment history identity failed: {type(exc).__name__}"
            ) from exc
        if token.audience != self._config.audience or not token.token:
            raise DeploymentHistoryError("deployment history identity returned an invalid token")

        rows: list[Mapping[str, Any]] = []
        total_bytes = 0
        skip_token: str | None = None
        seen_tokens: set[str] = set()
        for _ in range(self._config.maximum_pages):
            params = {"api-version": self._config.api_version, "$filter": filter_value}
            if skip_token is not None:
                params["$skiptoken"] = skip_token
            try:
                response = await self._http.get(
                    first_url,
                    params=params,
                    headers={
                        "Authorization": "Bearer " + token.token,
                        "Accept": "application/json",
                    },
                    timeout=self._config.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise DeploymentHistoryError(
                    f"deployment history request failed: {type(exc).__name__}"
                ) from exc
            if response.status_code != 200:
                raise DeploymentHistoryError(
                    f"deployment history returned HTTP {response.status_code}"
                )
            response_bytes = len(response.content)
            if response_bytes > self._config.maximum_response_bytes:
                raise DeploymentHistoryError(
                    "deployment history response exceeded the per-page byte bound"
                )
            total_bytes += response_bytes
            if total_bytes > self._config.maximum_total_response_bytes:
                raise DeploymentHistoryError(
                    "deployment history response exceeded the total byte bound"
                )
            payload = _response_object(response)
            values = payload.get("value")
            if not isinstance(values, list):
                raise DeploymentHistoryError("deployment history payload has no value array")
            for value in values:
                if not isinstance(value, Mapping):
                    raise DeploymentHistoryError(
                        "deployment history payload contains a non-object record"
                    )
                rows.append(value)
                if len(rows) > self._config.maximum_records:
                    raise DeploymentHistoryError(
                        "deployment history exceeded the configured record bound"
                    )
            continuation = payload.get("nextLink")
            if not isinstance(continuation, str) or not continuation:
                return tuple(rows)
            skip_token = _continuation_token(
                continuation,
                endpoint=self._config.endpoint,
                path=path,
                filter_value=filter_value,
                api_version=self._config.api_version,
            )
            if skip_token in seen_tokens:
                raise DeploymentHistoryError("deployment history continuation did not advance")
            seen_tokens.add(skip_token)
        raise DeploymentHistoryError("deployment history exceeded the page bound")


def _deployment_records(
    rows: tuple[Mapping[str, Any], ...],
    *,
    provider_id: str,
    resource_ref: str,
    inventory_generation: str,
    lower: datetime,
    upper: datetime,
    maximum_records: int,
) -> tuple[DeploymentRecord, ...]:
    records: dict[str, DeploymentRecord] = {}
    for row in rows:
        row_resource = _text(row.get("resourceId"), maximum=2_048)
        if row_resource is None or row_resource.casefold() != provider_id.casefold():
            raise DeploymentHistoryError("deployment history returned an out-of-scope record")
        timestamp = _timestamp(row.get("eventTimestamp"))
        if timestamp < lower or timestamp > upper:
            raise DeploymentHistoryError("deployment history returned an out-of-window record")
        category = _nested_value(row.get("category"), maximum=64)
        operation = _nested_value(row.get("operationName"), maximum=512)
        status = _nested_value(row.get("status"), maximum=64)
        if (
            category.casefold() != "administrative"
            or status.casefold() not in _SUCCESS_STATUSES
            or not _is_mutation(operation)
        ):
            continue
        event_id = _text(row.get("eventDataId"), maximum=256)
        if event_id is None:
            raise DeploymentHistoryError("deployment history mutation has no event identity")
        deployment_ref = f"azure-activity:{event_id}"
        caller = _text(row.get("caller"), maximum=1_024)
        author = (
            "principal:sha256:"
            + hashlib.sha256(f"fdai.azure.activity.caller.v1\0{caller}".encode()).hexdigest()[:24]
            if caller is not None
            else "principal:unknown"
        )
        evidence_digest = hashlib.sha256(
            json.dumps(
                {
                    "event_id": event_id,
                    "inventory_generation": inventory_generation,
                    "operation": operation,
                    "provider_id": provider_id.casefold(),
                    "resource_ref": resource_ref,
                    "status": status.casefold(),
                    "timestamp": timestamp.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        record = DeploymentRecord(
            deployment_ref=deployment_ref,
            timestamp=timestamp.astimezone(UTC).isoformat(),
            author=author,
            resource_refs=(resource_ref,),
            status=status.casefold(),
            metadata={
                "cause_domain": "infrastructure",
                "evidence_digest": f"sha256:{evidence_digest}",
                "inventory_generation": inventory_generation,
                "operation": operation,
                "provider": "azure_activity_log",
            },
        )
        existing = records.get(deployment_ref)
        if existing is not None and existing != record:
            raise DeploymentHistoryError("deployment history contains a conflicting event identity")
        records[deployment_ref] = record
    if len(records) > maximum_records:
        raise DeploymentHistoryError("deployment history exceeded the configured record bound")
    return tuple(sorted(records.values(), key=lambda item: (item.timestamp, item.deployment_ref)))


def _parse_window(value: str) -> timedelta:
    normalized = value.strip().upper()
    match = _DURATION.fullmatch(normalized)
    if match is None or not any(match.groupdict().values()):
        raise DeploymentHistoryError("deployment history window MUST be an ISO 8601 duration")
    seconds = (
        int(match.group("days") or 0) * 86_400
        + int(match.group("hours") or 0) * 3_600
        + int(match.group("minutes") or 0) * 60
        + float(match.group("seconds") or 0)
    )
    if seconds <= 0 or seconds > _MAX_WINDOW_SECONDS:
        raise DeploymentHistoryError(
            "deployment history window MUST be greater than zero and at most P31D"
        )
    return timedelta(seconds=seconds)


def _validate_arm_id(value: str) -> str:
    normalized = value.strip()
    if (
        len(normalized) > 2_048
        or not normalized.startswith("/")
        or any(ord(character) < 32 for character in normalized)
    ):
        raise DeploymentHistoryError("deployment resource identity is not a bounded ARM id")
    _subscription_id(normalized)
    return normalized


def _subscription_id(provider_id: str) -> str:
    match = _SUBSCRIPTION_PATH.match(provider_id)
    if match is None:
        raise DeploymentHistoryError("deployment resource identity has no subscription scope")
    return match.group("subscription").casefold()


def _continuation_token(
    url: str,
    *,
    endpoint: str,
    path: str,
    filter_value: str,
    api_version: str,
) -> str:
    parsed = urlparse(url)
    expected = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected.hostname
        or parsed.port not in {None, 443}
        or parsed.path.casefold() != path.casefold()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise DeploymentHistoryError("deployment history continuation escaped its Azure scope")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not set(query).issubset({"$filter", "$skiptoken", "api-version"}):
        raise DeploymentHistoryError("deployment history continuation has unexpected parameters")
    if query.get("$filter", [filter_value]) != [filter_value]:
        raise DeploymentHistoryError("deployment history continuation changed its resource filter")
    if query.get("api-version", [api_version]) != [api_version]:
        raise DeploymentHistoryError("deployment history continuation changed its API version")
    tokens = query.get("$skiptoken")
    if tokens is None or len(tokens) != 1 or not tokens[0] or len(tokens[0]) > 4_096:
        raise DeploymentHistoryError("deployment history continuation has no bounded token")
    return tokens[0]


def _response_object(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise DeploymentHistoryError("deployment history response is not JSON") from exc
    if not isinstance(payload, Mapping):
        raise DeploymentHistoryError("deployment history response is not an object")
    return payload


def _timestamp(value: object) -> datetime:
    text = _text(value, maximum=64)
    if text is None:
        raise DeploymentHistoryError("deployment history record has no timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeploymentHistoryError("deployment history timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise DeploymentHistoryError("deployment history timestamp MUST be timezone-aware")
    return parsed


def _nested_value(value: object, *, maximum: int) -> str:
    if isinstance(value, Mapping):
        value = value.get("value")
    text = _text(value, maximum=maximum)
    return text or ""


def _text(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise DeploymentHistoryError("deployment history text field exceeded its bound")
    return normalized


def _is_mutation(operation: str) -> bool:
    normalized = operation.casefold().rstrip("/")
    return normalized.endswith(_MUTATION_SUFFIXES)


def _odata_literal(value: str) -> str:
    return value.replace("'", "''")


def _azure_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "AzureActivityDeploymentHistoryProvider",
    "AzureDeploymentHistoryConfig",
    "AzureResolvedResourceIdentity",
    "AzureResourceIdentityError",
    "AzureResourceIdentityResolver",
]
