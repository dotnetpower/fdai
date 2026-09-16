"""Bounded JSON-file adapter for deployment operating model instances."""

from __future__ import annotations

import asyncio
import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)
from fdai.shared.providers.operating_model import (
    OperatingIntentSourceDocument,
    OperatingIntentSourceProvenance,
    OperatingModelSnapshot,
)


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
        raw = await asyncio.to_thread(
            _read_bounded_document, self._config.path, self._config.max_bytes
        )
        return operating_model_snapshot_from_mapping(raw)


class JsonOperatingIntentSourceProvider:
    """Load the deployment-owned operating-intent source, provenance included."""

    def __init__(self, *, config: JsonOperatingModelProviderConfig) -> None:
        self._config = config

    async def load(self) -> OperatingIntentSourceDocument:
        raw = await asyncio.to_thread(
            _read_bounded_document, self._config.path, self._config.max_bytes
        )
        return operating_intent_source_document_from_mapping(raw)


class _DuplicateJsonKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _read_bounded_document(path: Path, max_bytes: int) -> Mapping[str, object]:
    with path.open("rb") as stream:
        content_bytes = stream.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise ValueError("operating model file exceeds max_bytes")
    try:
        raw = normalize_json_value(
            json.loads(
                content_bytes.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
            ),
            path="operating_model",
        )
    except (
        UnicodeDecodeError,
        _DuplicateJsonKeyError,
        json.JSONDecodeError,
        RecursionError,
        OntologyInstanceValidationError,
    ) as exc:
        raise ValueError("operating model file MUST contain bounded canonical JSON") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("operating model document MUST be an object")
    return raw


_INTENT_SOURCE_MEMBERS = frozenset({"links", "objects", "provenance", "source_revision"})
_INTENT_PROVENANCE_MEMBERS = frozenset({"resolved_ref", "retrieved_at", "source_url"})
_INTENT_OBJECT_MEMBERS = frozenset({"id", "object_type", "properties"})
_INTENT_LINK_MEMBERS = frozenset({"from_id", "link_type", "properties", "to_id"})


def _array(value: Mapping[str, object], key: str) -> Sequence[object]:
    raw = value.get(key)
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueError(f"operating model {key} MUST be an array")
    return raw


def _reject_unknown_members(
    value: Mapping[str, object],
    *,
    allowed: frozenset[str],
    label: str,
) -> None:
    """Reject any member outside ``allowed`` so nothing accepted escapes the digest.

    The deployment-owned operating-intent binding advertises an exact
    *whole-document* pin. A parser that silently discarded unrecognized members
    would let the pinned digest stay constant while the file on disk changed, so
    the advertised pin would cover a lossy projection rather than the document an
    operator reviewed. Refusing the whole document is the only fail-closed answer:
    the runtime cannot know whether an unrecognized member was decoration or a
    future authority-bearing field it does not yet understand.
    """

    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise ValueError(
            f"operating intent source {label} carries unknown members {unknown!r}; the pinned "
            "whole-document digest MUST cover every accepted member"
        )


def operating_model_snapshot_from_mapping(
    raw: Mapping[str, object],
    *,
    strict_members: bool = False,
) -> OperatingModelSnapshot:
    """Parse one already bounded JSON mapping into a complete snapshot.

    ``strict_members`` stays off for the generic ``FDAI_OPERATING_MODEL_PATH``
    snapshot, whose format is deliberately tolerant of forward-compatible members
    and carries no pinned digest. Only the deployment-owned operating-intent source
    turns it on, because only that source advertises an exact whole-document pin.
    """

    objects = _array(raw, "objects")
    links = _array(raw, "links")
    return OperatingModelSnapshot(
        source_revision=_required_string(raw, "source_revision"),
        objects=tuple(_object_record(item, strict_members=strict_members) for item in objects),
        links=tuple(_link_record(item, strict_members=strict_members) for item in links),
    )


def operating_intent_source_document_from_mapping(
    raw: Mapping[str, object],
) -> OperatingIntentSourceDocument:
    """Parse one deployment-owned operating-intent source document.

    Unlike the generic operating-model file, this format MUST carry a ``provenance``
    block so the runtime binding can verify exact revision and provenance before
    projecting any of the six operating-intent ObjectTypes.

    Parsing is strict at every level - top-level document, provenance block, object
    entries, and link entries - so the parsed document is a faithful representation
    of the accepted file. That is what makes
    ``operating_intent_source_document_digest`` a genuine whole-document pin rather
    than a digest of the subset this parser happens to recognize.
    """

    _reject_unknown_members(raw, allowed=_INTENT_SOURCE_MEMBERS, label="document")
    return OperatingIntentSourceDocument(
        snapshot=operating_model_snapshot_from_mapping(raw, strict_members=True),
        provenance=_provenance(raw),
    )


def _provenance(raw: Mapping[str, object]) -> OperatingIntentSourceProvenance:
    value = raw.get("provenance")
    if not isinstance(value, Mapping):
        raise ValueError("operating intent source provenance MUST be an object")
    _reject_unknown_members(value, allowed=_INTENT_PROVENANCE_MEMBERS, label="provenance")
    retrieved_at_raw = value.get("retrieved_at")
    if not isinstance(retrieved_at_raw, str) or not retrieved_at_raw.strip():
        raise ValueError("operating intent source provenance.retrieved_at MUST be non-empty")
    try:
        retrieved_at = datetime.fromisoformat(retrieved_at_raw)
    except ValueError as exc:
        raise ValueError(
            "operating intent source provenance.retrieved_at MUST be an RFC 3339 timestamp"
        ) from exc
    return OperatingIntentSourceProvenance(
        source_url=_required_string(value, "source_url"),
        resolved_ref=_required_string(value, "resolved_ref"),
        retrieved_at=retrieved_at,
    )


def _required_string(value: Mapping[str, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"operating model {key} MUST be non-empty")
    return raw


def _object_record(raw: object, *, strict_members: bool = False) -> OntologyObjectRecord:
    if not isinstance(raw, Mapping):
        raise ValueError("operating model object entries MUST be objects")
    if strict_members:
        _reject_unknown_members(raw, allowed=_INTENT_OBJECT_MEMBERS, label="object entry")
    properties = raw.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError("operating model object properties MUST be an object")
    object_type = _required_string(raw, "object_type")
    _validate_operating_aliases(properties, object_type=object_type)
    return OntologyObjectRecord(
        id=_required_string(raw, "id"),
        object_type=object_type,
        properties=dict(properties),
    )


def _validate_operating_aliases(
    properties: Mapping[str, object],
    *,
    object_type: str,
) -> None:
    aliases = properties.get("aliases")
    if aliases is None or object_type not in {"BusinessService", "Workload"}:
        return
    if not isinstance(aliases, Sequence) or isinstance(aliases, (str, bytes)):
        raise ValueError("operating model logical target aliases MUST be an array")
    if not 1 <= len(aliases) <= 32:
        raise ValueError("operating model logical target aliases MUST contain 1-32 values")
    normalized: list[str] = []
    for alias in aliases:
        if (
            not isinstance(alias, str)
            or not alias.strip()
            or alias != alias.strip()
            or len(alias) > 256
            or unicodedata.normalize("NFC", alias) != alias
            or any(unicodedata.category(character) in {"Cc", "Cf"} for character in alias)
        ):
            raise ValueError(
                "operating model logical target aliases MUST be trimmed NFC text up to 256 chars"
            )
        normalized.append(alias.casefold())
    if len(normalized) != len(set(normalized)):
        raise ValueError("operating model logical target aliases MUST be case-insensitively unique")


def _link_record(raw: object, *, strict_members: bool = False) -> OntologyLinkRecord:
    if not isinstance(raw, Mapping):
        raise ValueError("operating model link entries MUST be objects")
    if strict_members:
        _reject_unknown_members(raw, allowed=_INTENT_LINK_MEMBERS, label="link entry")
    properties = raw.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError("operating model link properties MUST be an object")
    return OntologyLinkRecord(
        link_type=_required_string(raw, "link_type"),
        from_id=_required_string(raw, "from_id"),
        to_id=_required_string(raw, "to_id"),
        properties=dict(properties),
    )


__all__ = [
    "JsonOperatingIntentSourceProvider",
    "JsonOperatingModelProvider",
    "JsonOperatingModelProviderConfig",
    "OperatingIntentSourceDocument",
    "OperatingIntentSourceProvenance",
    "operating_intent_source_document_from_mapping",
    "operating_model_snapshot_from_mapping",
]
