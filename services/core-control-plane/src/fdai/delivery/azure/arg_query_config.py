"""Configuration contract for the Azure Resource Graph query factory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from fdai.delivery.azure.arg_transport import (
    DEFAULT_ARG_REQUEST_BURST,
    DEFAULT_ARG_REQUESTS_PER_SECOND,
    DEFAULT_ARG_THROTTLE_MAX_DEFER_SECONDS,
)

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ARG_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_PAGE_SIZE: Final[int] = 1000
_DEFAULT_MAX_PAGES: Final[int] = 32
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_PROPS_BYTES: Final[int] = 64 * 1024
DEFAULT_RELATIONSHIP_MAPPING_ROOT: Final[Path] = Path(
    "rule-catalog/vocabulary/provider-relationship-mappings"
)


@dataclass(frozen=True, slots=True)
class AzureArgQueryFactoryConfig:
    """Configure bounded Azure Resource Graph query factory behavior."""

    subscription_scopes: tuple[str, ...]
    """Subscription or management-group ids the ARG query runs over."""

    arg_endpoint: str = _DEFAULT_ARG_ENDPOINT
    """Root URL for the ARM control plane."""

    arg_api_version: str = _DEFAULT_ARG_API_VERSION
    """Pinned ARG REST API version."""

    audience: str = _DEFAULT_AUDIENCE
    """OIDC audience requested from the injected workload identity."""

    page_size: int = _DEFAULT_PAGE_SIZE
    """ARG ``$top`` value, bounded by the API maximum of 1000."""

    max_pages: int = _DEFAULT_MAX_PAGES
    """Maximum number of pages fetched for one shard."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    """Per-request timeout applied to every page fetch."""

    max_props_bytes: int = _DEFAULT_MAX_PROPS_BYTES
    """Maximum serialized size of one untrusted property map."""

    relationship_mapping_root: Path = DEFAULT_RELATIONSHIP_MAPPING_ROOT
    """Reviewed provider relationship mapping catalog root."""

    requests_per_second: float = DEFAULT_ARG_REQUESTS_PER_SECOND
    """Sustained request budget shared by every shard."""

    requests_burst: int = DEFAULT_ARG_REQUEST_BURST
    """Requests allowed ahead of the sustained request budget."""

    throttle_max_defer_seconds: float = DEFAULT_ARG_THROTTLE_MAX_DEFER_SECONDS
    """Maximum reactive quota deferral for one attempt."""


__all__ = ["AzureArgQueryFactoryConfig", "DEFAULT_RELATIONSHIP_MAPPING_ROOT"]
