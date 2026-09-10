"""Read bounded configuration-drift observations from Azure Resource Graph."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
)
from fdai.core.detection.configuration_drift_codec import baseline_from_dict
from fdai.delivery.azure.arg_transport import fetch_arg_row_pages
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ARG_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_STORAGE_AUDIENCE: Final[str] = "https://storage.azure.com/"
_STORAGE_API_VERSION: Final[str] = "2025-05-05"
_MAX_BASELINE_BYTES: Final[int] = 16 * 1024 * 1024
_ATTRIBUTE_PATH = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_ID_CHARS = 4_096
_MAX_TEXT_CHARS = 512
_MAX_ATTRIBUTE_CHARS = 4_096
_ALLOWED_ARG_HOSTS = frozenset(
    {
        "management.azure.com",
        "management.azure.us",
        "management.chinacloudapi.cn",
        "management.microsoftazure.de",
    }
)
_ALLOWED_BLOB_HOST_SUFFIXES = (
    ".blob.core.windows.net",
    ".blob.core.usgovcloudapi.net",
    ".blob.core.chinacloudapi.cn",
    ".blob.core.cloudapi.de",
)


class AzureConfigurationObservationError(RuntimeError):
    """Report unavailable or malformed Azure configuration evidence."""


class AzureConfigurationBaselineError(RuntimeError):
    """Report unavailable or malformed deployment-owned baseline evidence."""


@dataclass(frozen=True, slots=True)
class AzureBlobConfigurationBaselineConfig:
    """Pin one immutable content-addressed baseline Blob."""

    blob_url: str
    expected_sha256: str
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        digest = self.expected_sha256.strip().lower()
        parsed = urlparse(self.blob_url)
        segments = tuple(segment for segment in parsed.path.split("/") if segment)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or not any(parsed.hostname.endswith(suffix) for suffix in _ALLOWED_BLOB_HOST_SUFFIXES)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or len(segments) != 3
            or segments[1] != "configuration-baselines"
            or segments[2] != f"{digest}.json"
        ):
            raise ValueError(
                "configuration baseline URL MUST identify one content-addressed Azure Blob"
            )
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("configuration baseline digest MUST be lowercase SHA-256")
        if self.request_timeout_seconds <= 0:
            raise ValueError("configuration baseline request timeout MUST be positive")
        object.__setattr__(self, "blob_url", self.blob_url.strip())
        object.__setattr__(self, "expected_sha256", digest)


@dataclass(frozen=True, slots=True)
class AzureBlobConfigurationBaselineSource:
    """Load one immutable baseline through Managed Identity and verify its bytes."""

    identity: WorkloadIdentity
    http_client: httpx.AsyncClient
    config: AzureBlobConfigurationBaselineConfig

    async def load(self) -> FrozenConfigurationBaseline:
        token = await self.identity.get_token(_STORAGE_AUDIENCE)
        headers = {
            "Authorization": f"Bearer {token.token}",
            "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
            "x-ms-version": _STORAGE_API_VERSION,
        }
        try:
            async with self.http_client.stream(
                "GET",
                self.config.blob_url,
                headers=headers,
                timeout=self.config.request_timeout_seconds,
            ) as response:
                if response.status_code != 200:
                    raise AzureConfigurationBaselineError(
                        f"configuration baseline storage returned HTTP {response.status_code}"
                    )
                metadata_digest = response.headers.get("x-ms-meta-fdai_sha256", "")
                if metadata_digest != self.config.expected_sha256:
                    raise AzureConfigurationBaselineError(
                        "configuration baseline Blob metadata digest mismatch"
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_BASELINE_BYTES:
                        raise AzureConfigurationBaselineError(
                            "configuration baseline Blob exceeds the allowed size"
                        )
        except httpx.HTTPError as exc:
            raise AzureConfigurationBaselineError(
                "configuration baseline storage request failed"
            ) from exc
        if not content:
            raise AzureConfigurationBaselineError("configuration baseline Blob is empty")
        if hashlib.sha256(content).hexdigest() != self.config.expected_sha256:
            raise AzureConfigurationBaselineError(
                "configuration baseline Blob content digest mismatch"
            )
        try:
            raw = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AzureConfigurationBaselineError(
                "configuration baseline Blob is not valid UTF-8 JSON"
            ) from exc
        if not isinstance(raw, Mapping):
            raise AzureConfigurationBaselineError(
                "configuration baseline Blob MUST contain one JSON object"
            )
        return baseline_from_dict(raw)


@dataclass(frozen=True, slots=True)
class AzureConfigurationObservationConfig:
    """Configure one exact, bounded Azure Resource Graph observation."""

    allowed_scope: str
    subscription_scopes: tuple[str, ...]
    attribute_paths: tuple[str, ...]
    arg_endpoint: str = _DEFAULT_ARG_ENDPOINT
    arg_api_version: str = _DEFAULT_ARG_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    page_size: int = 1_000
    max_pages: int = 32
    max_records: int = 100_000
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        for field_name, value in (
            ("allowed_scope", self.allowed_scope),
            ("arg_endpoint", self.arg_endpoint),
            ("arg_api_version", self.arg_api_version),
            ("audience", self.audience),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} MUST be non-empty")
        if not self.subscription_scopes:
            raise ValueError("subscription_scopes MUST be non-empty")
        if any(not item.strip() for item in self.subscription_scopes):
            raise ValueError("subscription_scopes MUST contain non-empty values")
        if len(self.subscription_scopes) != len(set(self.subscription_scopes)):
            raise ValueError("subscription_scopes MUST be unique")
        if not self.attribute_paths:
            raise ValueError("attribute_paths MUST be non-empty")
        if len(self.attribute_paths) > 64:
            raise ValueError("attribute_paths MUST contain at most 64 paths")
        if self.attribute_paths != tuple(sorted(self.attribute_paths)):
            raise ValueError("attribute_paths MUST be unique and ordered")
        if len(self.attribute_paths) != len(set(self.attribute_paths)):
            raise ValueError("attribute_paths MUST be unique and ordered")
        if any(_ATTRIBUTE_PATH.fullmatch(path) is None for path in self.attribute_paths):
            raise ValueError("attribute_paths contains an invalid path")
        if self.page_size < 1 or self.max_pages < 1 or self.max_records < 1:
            raise ValueError("Azure configuration observation bounds MUST be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")
        parsed_endpoint = urlparse(self.arg_endpoint)
        if (
            parsed_endpoint.scheme != "https"
            or parsed_endpoint.hostname not in _ALLOWED_ARG_HOSTS
            or parsed_endpoint.path not in {"", "/"}
            or parsed_endpoint.query
            or parsed_endpoint.fragment
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
        ):
            raise ValueError("arg_endpoint MUST be an approved Azure management HTTPS origin")


@dataclass(frozen=True, slots=True)
class AzureArgConfigurationObservationSource:
    """Observe selected scalar attributes inside one server-owned Azure scope."""

    identity: WorkloadIdentity
    http_client: httpx.AsyncClient
    config: AzureConfigurationObservationConfig
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def observe(self, *, scope: str) -> ConfigurationObservation:
        """Return a complete observation or fail without producing partial evidence."""

        if scope != self.config.allowed_scope:
            raise PermissionError("requested scope is outside the configured observation source")
        rows = await fetch_arg_row_pages(
            identity=self.identity,
            http_client=self.http_client,
            audience=self.config.audience,
            endpoint=self.config.arg_endpoint,
            api_version=self.config.arg_api_version,
            subscriptions=self.config.subscription_scopes,
            query=_query(self.config.attribute_paths),
            result_name="configuration-drift",
            page_size=self.config.page_size,
            max_pages=self.config.max_pages,
            timeout_seconds=self.config.timeout_seconds,
            error_type=AzureConfigurationObservationError,
            max_records=self.config.max_records,
        )
        resources = tuple(
            _resource(row, attribute_paths=self.config.attribute_paths) for row in rows
        )
        return ConfigurationObservation(
            scope=self.config.allowed_scope,
            observed_at=self.clock(),
            source="azure_resource_graph",
            completeness=EvidenceCompleteness.COMPLETE,
            resources=resources,
        )


def _query(attribute_paths: tuple[str, ...]) -> str:
    projections = ["id", "type", "name", "location"]
    for index, path in enumerate(attribute_paths):
        projections.append(f'attribute_{index}_presence=iff(isnull({path}), "missing", "present")')
        projections.append(f"attribute_{index}=tostring({path})")
    return "Resources | project " + ", ".join(projections) + " | order by id asc"


def _resource(
    row: Mapping[str, Any],
    *,
    attribute_paths: tuple[str, ...],
) -> ConfigurationResource:
    provider_id = _required_row_text(row, "id", max_chars=_MAX_ID_CHARS)
    name = _required_row_text(row, "name", max_chars=_MAX_TEXT_CHARS)
    resource_type = _required_row_text(row, "type", max_chars=_MAX_TEXT_CHARS)
    location = _location(row)
    attributes: dict[str, object] = {}
    unknown: set[str] = set()
    for index, path in enumerate(attribute_paths):
        presence = row.get(f"attribute_{index}_presence")
        if presence not in {"present", "missing"}:
            raise AzureConfigurationObservationError(
                f"ARG returned an invalid configuration presence marker for {path!r}"
            )
        if presence == "missing":
            unknown.add(path)
            continue
        value = row.get(f"attribute_{index}")
        if not isinstance(value, (str, bool, int, float)):
            raise AzureConfigurationObservationError(
                f"ARG returned a non-scalar configuration attribute for {path!r}"
            )
        if isinstance(value, str) and len(value) > _MAX_ATTRIBUTE_CHARS:
            raise AzureConfigurationObservationError(
                f"ARG returned an oversized configuration attribute for {path!r}"
            )
        attributes[path] = value
    identity_suffix = hashlib.sha256(provider_id.casefold().encode("utf-8")).hexdigest()[:16]
    return ConfigurationResource(
        local_name=f"{name}#{identity_suffix}",
        resource_type=resource_type,
        region=location,
        attributes=attributes,
        unknown_attributes=frozenset(unknown),
    )


def _required_row_text(
    row: Mapping[str, Any],
    field: str,
    *,
    max_chars: int,
) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AzureConfigurationObservationError(
            f"ARG configuration row is missing required field {field!r}"
        )
    normalized = value.strip()
    if len(normalized) > max_chars:
        raise AzureConfigurationObservationError(
            f"ARG configuration row field {field!r} exceeds {max_chars} characters"
        )
    return normalized


def _location(row: Mapping[str, Any]) -> str:
    value = row.get("location")
    if not isinstance(value, str):
        raise AzureConfigurationObservationError(
            "ARG configuration row is missing required field 'location'"
        )
    normalized = value.strip()
    if len(normalized) > _MAX_TEXT_CHARS:
        raise AzureConfigurationObservationError(
            f"ARG configuration row field 'location' exceeds {_MAX_TEXT_CHARS} characters"
        )
    return normalized or "global"


__all__ = [
    "AzureArgConfigurationObservationSource",
    "AzureBlobConfigurationBaselineConfig",
    "AzureBlobConfigurationBaselineSource",
    "AzureConfigurationBaselineError",
    "AzureConfigurationObservationConfig",
    "AzureConfigurationObservationError",
]
