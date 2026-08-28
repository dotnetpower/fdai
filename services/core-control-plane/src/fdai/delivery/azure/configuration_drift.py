"""Read bounded configuration-drift observations from Azure Resource Graph."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
)
from fdai.delivery.azure.arg_transport import fetch_arg_row_pages
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ARG_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_ATTRIBUTE_PATH = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$")
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


class AzureConfigurationObservationError(RuntimeError):
    """Report unavailable or malformed Azure configuration evidence."""


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
        projections.append(f"attribute_{index}_present=isnotnull({path})")
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
        present = row.get(f"attribute_{index}_present")
        if not isinstance(present, bool):
            raise AzureConfigurationObservationError(
                f"ARG returned an invalid configuration presence marker for {path!r}"
            )
        if not present:
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
    "AzureConfigurationObservationConfig",
    "AzureConfigurationObservationError",
]
