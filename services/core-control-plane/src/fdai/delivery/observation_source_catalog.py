"""Load the customer-agnostic observation source registry."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from fdai_service_contracts import ObservationDomain

from fdai.delivery.observation_campaign import ObservationSourceSpec

_MAX_CATALOG_BYTES = 256_000
_CATALOG_KEYS = frozenset({"version", "max_concurrency", "sources"})
_SOURCE_KEYS = frozenset(
    {
        "id",
        "domain",
        "owner_agent",
        "interval_seconds",
        "lookback_seconds",
        "timeout_seconds",
        "max_targets",
        "max_results",
        "max_output_bytes",
        "required",
    }
)


@dataclass(frozen=True, slots=True)
class ObservationSourceCatalog:
    """Hold one immutable source registry and its content digest."""

    version: int
    max_concurrency: int
    sources: tuple[ObservationSourceSpec, ...]
    digest: str


def load_observation_source_catalog(path: Path) -> ObservationSourceCatalog:
    """Load a bounded YAML registry without accepting executable query text."""
    raw_bytes = path.read_bytes()
    if not raw_bytes or len(raw_bytes) > _MAX_CATALOG_BYTES:
        raise ValueError("observation source catalog MUST be bounded non-empty content")
    payload = yaml.safe_load(raw_bytes)
    if not isinstance(payload, Mapping):
        raise ValueError("observation source catalog MUST be an object")
    _require_exact_keys(payload, allowed=_CATALOG_KEYS, field="catalog")
    version = _integer(payload.get("version"), "version")
    if version != 1:
        raise ValueError("observation source catalog version MUST be 1")
    max_concurrency = _integer(payload.get("max_concurrency"), "max_concurrency")
    if not 1 <= max_concurrency <= 4:
        raise ValueError("observation source max_concurrency MUST be in [1, 4]")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
        raise ValueError("observation source catalog sources MUST be an array")
    sources = tuple(_source(item) for item in raw_sources)
    if not sources:
        raise ValueError("observation source catalog MUST contain at least one source")
    if len({source.source_id for source in sources}) != len(sources):
        raise ValueError("observation source catalog ids MUST be unique")
    if set(ObservationDomain) != {source.domain for source in sources}:
        raise ValueError("observation source catalog MUST cover every observation domain")
    return ObservationSourceCatalog(
        version=version,
        max_concurrency=max_concurrency,
        sources=sources,
        digest="sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def _source(value: object) -> ObservationSourceSpec:
    if not isinstance(value, Mapping):
        raise ValueError("observation source entry MUST be an object")
    _require_exact_keys(value, allowed=_SOURCE_KEYS, field="source entry")
    required = value.get("required", True)
    if not isinstance(required, bool):
        raise ValueError("observation source required MUST be boolean")
    try:
        domain = ObservationDomain(_text(value.get("domain"), "domain"))
    except ValueError as exc:
        raise ValueError("observation source domain is unsupported") from exc
    return ObservationSourceSpec(
        source_id=_text(value.get("id"), "id"),
        domain=domain,
        owner_agent=_text(value.get("owner_agent"), "owner_agent"),  # type: ignore[arg-type]
        interval_seconds=_integer(value.get("interval_seconds"), "interval_seconds"),
        lookback_seconds=_integer(value.get("lookback_seconds"), "lookback_seconds"),
        timeout_seconds=_number(value.get("timeout_seconds"), "timeout_seconds"),
        max_targets=_integer(value.get("max_targets"), "max_targets"),
        max_results=_integer(value.get("max_results"), "max_results"),
        max_output_bytes=_integer(value.get("max_output_bytes"), "max_output_bytes"),
        required=required,
    )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"observation source {field} MUST be non-empty text")
    return value.strip()


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"observation source {field} MUST be an integer")
    return value


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"observation source {field} MUST be numeric")
    return float(value)


def _require_exact_keys(
    value: Mapping[object, object],
    *,
    allowed: frozenset[str],
    field: str,
) -> None:
    keys = set(value)
    if not all(isinstance(key, str) for key in keys) or keys - allowed:
        raise ValueError(f"observation source {field} contains unsupported fields")
    missing = allowed - keys
    if field == "source entry":
        missing -= {"required"}
    if missing:
        raise ValueError(f"observation source {field} is missing required fields")


__all__ = ["ObservationSourceCatalog", "load_observation_source_catalog"]
