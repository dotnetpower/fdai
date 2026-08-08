"""Bounded JSON-file adapter for deployment operating model instances."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)
from fdai.shared.providers.operating_model import OperatingModelSnapshot


@dataclass(frozen=True, slots=True)
class JsonOperatingModelProviderConfig:
    path: Path
    max_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_bytes < 1:
            raise ValueError("operating model max_bytes MUST be >= 1")


class JsonOperatingModelProvider:
    def __init__(self, *, config: JsonOperatingModelProviderConfig) -> None:
        self._config = config

    async def load(self) -> OperatingModelSnapshot:
        content = await asyncio.to_thread(self._read)
        try:
            raw = normalize_json_value(json.loads(content), path="operating_model")
        except (json.JSONDecodeError, RecursionError, OntologyInstanceValidationError) as exc:
            raise ValueError("operating model file MUST contain bounded canonical JSON") from exc
        if not isinstance(raw, Mapping):
            raise ValueError("operating model document MUST be an object")
        objects = _array(raw, "objects")
        links = _array(raw, "links")
        return OperatingModelSnapshot(
            source_revision=_required_string(raw, "source_revision"),
            objects=tuple(_object_record(item) for item in objects),
            links=tuple(_link_record(item) for item in links),
        )

    def _read(self) -> str:
        path = self._config.path
        if path.stat().st_size > self._config.max_bytes:
            raise ValueError("operating model file exceeds max_bytes")
        return path.read_text(encoding="utf-8")


def _array(value: Mapping[str, object], key: str) -> Sequence[object]:
    raw = value.get(key)
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueError(f"operating model {key} MUST be an array")
    return raw


def _required_string(value: Mapping[str, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"operating model {key} MUST be non-empty")
    return raw


def _object_record(raw: object) -> OntologyObjectRecord:
    if not isinstance(raw, Mapping):
        raise ValueError("operating model object entries MUST be objects")
    properties = raw.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError("operating model object properties MUST be an object")
    return OntologyObjectRecord(
        id=_required_string(raw, "id"),
        object_type=_required_string(raw, "object_type"),
        properties=dict(properties),
    )


def _link_record(raw: object) -> OntologyLinkRecord:
    if not isinstance(raw, Mapping):
        raise ValueError("operating model link entries MUST be objects")
    properties = raw.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError("operating model link properties MUST be an object")
    return OntologyLinkRecord(
        link_type=_required_string(raw, "link_type"),
        from_id=_required_string(raw, "from_id"),
        to_id=_required_string(raw, "to_id"),
        properties=dict(properties),
    )


__all__ = ["JsonOperatingModelProvider", "JsonOperatingModelProviderConfig"]
