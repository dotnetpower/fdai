"""Normalize verified semantic terminal data for pure channel rendering."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from fdai_operator_service.families.conversation.contracts import JsonObject

MAX_PRESENTATION_FACTS = 256
MAX_PRESENTATION_TEXT_CHARS = 16_000
_BLOCK_KEYS = {
    "slot_id",
    "kind",
    "title",
    "emphasis",
    "collapsed",
    "evidence_refs",
    "data",
}
_V1_KINDS = frozenset(
    {"summary", "callout", "table", "threshold_table", "list", "coverage", "bar", "evidence"}
)
_V2_KINDS = _V1_KINDS | {"time_series", "comparison", "timeline"}


@dataclass(frozen=True, slots=True)
class PresentationCapabilities:
    """Declare one provider renderer's bounded output surface."""

    profile_id: str
    max_text_chars: int
    max_serialized_bytes: int
    max_blocks: int
    max_block_text_chars: int
    max_fields: int
    max_actions: int

    def __post_init__(self) -> None:
        _text(self.profile_id, 128)
        if not 256 <= self.max_text_chars <= MAX_PRESENTATION_TEXT_CHARS:
            raise ValueError("presentation max_text_chars is outside the bounded range")
        if not 1_024 <= self.max_serialized_bytes <= 128_000:
            raise ValueError("presentation max_serialized_bytes is outside the bounded range")
        for name, value, maximum in (
            ("max_blocks", self.max_blocks, 64),
            ("max_block_text_chars", self.max_block_text_chars, 16_000),
            ("max_fields", self.max_fields, MAX_PRESENTATION_FACTS),
            ("max_actions", self.max_actions, 16),
        ):
            if not 0 <= value <= maximum:
                raise ValueError(f"presentation {name} is outside the bounded range")


@dataclass(frozen=True, slots=True)
class PresentationFact:
    """Retain one exact label/value fact from a validated artifact."""

    label: str
    value: str

    def __post_init__(self) -> None:
        _text(self.label, 512)
        _text(self.value, 1_024)


@dataclass(frozen=True, slots=True)
class PresentationSection:
    """Retain one normalized semantic artifact block."""

    kind: str
    title: str
    facts: tuple[PresentationFact, ...]
    description: str | None = None


@dataclass(frozen=True, slots=True)
class PresentationEnvelope:
    """Carry canonical facts and mandatory no-authority context."""

    canonical_text: str
    artifact_version: Literal[1, 2] | None
    sections: tuple[PresentationSection, ...]
    limitations: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    authority: str
    unavailable: bool
    web_url: str | None = None
    artifact_degraded: bool = False
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _text(self.canonical_text, MAX_PRESENTATION_TEXT_CHARS)
        _text(self.authority, 256)
        if self.execution_authority:
            raise ValueError("channel presentation MUST NOT grant execution authority")
        if len(self.sections) > 8 or len(self.limitations) > 16 or len(self.evidence_refs) > 16:
            raise ValueError("channel presentation exceeds a bounded collection")
        for limitation in self.limitations:
            _text(limitation, 1_024)
        for evidence_ref in self.evidence_refs:
            _text(evidence_ref, 1_024)
        if self.web_url is not None and not (
            self.web_url.startswith("/") or self.web_url.startswith("https://")
        ):
            raise ValueError("channel presentation Web URL MUST be HTTPS or same-origin relative")


@dataclass(frozen=True, slots=True)
class PresentationPayload:
    """Return one pure provider payload and its degradation metadata."""

    body: JsonObject
    fallback_text: str
    degraded_to_text: bool
    omitted_visuals: int = 0


class PresentationRenderError(ValueError):
    """Mandatory channel content cannot fit the configured provider profile."""


def normalize_terminal_presentation(
    terminal: Mapping[str, object],
    *,
    web_url: str | None = None,
) -> PresentationEnvelope:
    """Validate semantic terminal data and fail closed on malformed visual artifacts."""
    if terminal.get("execution_authority", False) is not False:
        raise ValueError("channel terminal data MUST deny execution authority")
    answer = _text(terminal.get("answer"), MAX_PRESENTATION_TEXT_CHARS)
    status = _text(terminal.get("status"), 64)
    verification = _mapping(terminal.get("verification"))
    evidence_refs = _text_tuple(verification.get("evidence_refs"), maximum=16, allow_empty=True)
    authority_raw = verification.get("authority")
    authority = (
        _text(authority_raw, 256)
        if isinstance(authority_raw, str) and authority_raw.strip()
        else "no_execution_authority"
    )
    artifact = terminal.get("presentation_artifact")
    if artifact is None:
        version: Literal[1, 2] | None = None
        sections: tuple[PresentationSection, ...] = ()
        limitations: tuple[str, ...] = ()
        degraded = False
    else:
        try:
            version, sections, limitations = _normalize_artifact(
                artifact,
                response_refs=set(evidence_refs),
            )
            degraded = False
        except ValueError:
            version = None
            sections = ()
            limitations = ()
            degraded = True
    return PresentationEnvelope(
        canonical_text=answer,
        artifact_version=version,
        sections=sections,
        limitations=limitations,
        evidence_refs=evidence_refs,
        authority=authority,
        unavailable=status != "answered",
        web_url=web_url,
        artifact_degraded=degraded,
    )


def build_fallback_text(
    envelope: PresentationEnvelope,
    capabilities: PresentationCapabilities,
) -> tuple[str, bool]:
    """Preserve mandatory safety context while truncating canonical prose only."""
    sections: list[str] = []
    if envelope.limitations:
        sections.append("Limitations:\n" + "\n".join(f"- {item}" for item in envelope.limitations))
    evidence = "\n".join(f"- {item}" for item in envelope.evidence_refs) or "- none recorded"
    sections.append("Evidence:\n" + evidence)
    sections.append(f"Authority: {envelope.authority}\nExecution authority: none")
    if envelope.unavailable:
        sections.append("Availability: unavailable")
    if envelope.web_url is not None:
        sections.append(f"Web: {envelope.web_url}")
    mandatory = "\n\n".join(sections)
    available = capabilities.max_text_chars - len(mandatory) - 2
    if available < 1:
        raise PresentationRenderError("mandatory channel presentation text exceeds the limit")
    canonical = envelope.canonical_text
    degraded = envelope.artifact_degraded
    if len(canonical) > available:
        marker = "\n[CHANNEL TEXT TRUNCATED]"
        if available <= len(marker):
            raise PresentationRenderError("channel cannot retain canonical and mandatory text")
        canonical = canonical[: available - len(marker)].rstrip() + marker
        degraded = True
    return canonical + "\n\n" + mandatory, degraded


def serialized_size(body: Mapping[str, object]) -> int:
    """Return deterministic strict JSON bytes for one renderer payload."""
    return len(
        json.dumps(
            body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )


def _normalize_artifact(
    raw: object,
    *,
    response_refs: set[str],
) -> tuple[Literal[1, 2], tuple[PresentationSection, ...], tuple[str, ...]]:
    artifact = _mapping(raw)
    if set(artifact) != {"schema_version", "layout", "blocks", "evidence_refs"}:
        raise ValueError("presentation artifact shape is invalid")
    raw_version = artifact.get("schema_version")
    if raw_version not in {1, 2} or artifact.get("layout") != "stack":
        raise ValueError("presentation artifact version is unsupported")
    version: Literal[1, 2] = 1 if raw_version == 1 else 2
    artifact_refs = _refs(artifact.get("evidence_refs"), response_refs)
    blocks = artifact.get("blocks")
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 8:
        raise ValueError("presentation artifact blocks are invalid")
    sections: list[PresentationSection] = []
    limitations: list[str] = []
    slots: set[str] = set()
    fact_count = 0
    for raw_block in blocks:
        block = _mapping(raw_block)
        if set(block) != _BLOCK_KEYS:
            raise ValueError("presentation block shape is invalid")
        slot_id = _text(block.get("slot_id"), 64)
        kind = _text(block.get("kind"), 64)
        title = _text(block.get("title"), 512)
        if slot_id in slots or kind not in (_V1_KINDS if version == 1 else _V2_KINDS):
            raise ValueError("presentation block identity is invalid")
        slots.add(slot_id)
        _refs(block.get("evidence_refs"), artifact_refs)
        data = _mapping(block.get("data"))
        if kind == "callout":
            limitations.extend(_callout_lines(data))
            continue
        description, facts = _block_facts(kind, data, version=version)
        fact_count += len(facts)
        if fact_count > MAX_PRESENTATION_FACTS:
            raise ValueError("presentation artifact exceeds the fact bound")
        sections.append(PresentationSection(kind, title, facts, description))
    return version, tuple(sections), tuple(dict.fromkeys(limitations))


def _block_facts(
    kind: str,
    data: Mapping[object, object],
    *,
    version: int,
) -> tuple[str | None, tuple[PresentationFact, ...]]:
    if kind in {"summary", "evidence"}:
        if set(data) != {"items"}:
            raise ValueError("item block has invalid keys")
        return None, _label_value_facts(data.get("items"))
    if kind in {"table", "threshold_table", "list"}:
        return None, _table_facts(data)
    if kind in {"bar", "coverage"}:
        if version == 1:
            if set(data) != {"items"}:
                raise ValueError("v1 chart has invalid keys")
            return None, _chart_facts(data.get("items"), coverage=False)
        if set(data) != {"description", "unit", "items", "exact_table"}:
            raise ValueError("v2 chart has invalid keys")
        description = _text(data.get("description"), 1_024)
        _text(data.get("unit"), 64)
        _table_facts(_mapping(data.get("exact_table")))
        return description, _chart_facts(data.get("items"), coverage=kind == "coverage")
    if kind == "time_series":
        if set(data) != {"description", "metric", "unit", "points", "exact_table"}:
            raise ValueError("time-series block has invalid keys")
        description = _text(data.get("description"), 1_024)
        _text(data.get("metric"), 512)
        _text(data.get("unit"), 64)
        _table_facts(_mapping(data.get("exact_table")))
        return description, _point_facts(data.get("points"), minimum=3)
    if kind == "comparison":
        if set(data) != {"description", "metric", "unit", "items", "exact_table"}:
            raise ValueError("comparison block has invalid keys")
        description = _text(data.get("description"), 1_024)
        _text(data.get("metric"), 512)
        _text(data.get("unit"), 64)
        _table_facts(_mapping(data.get("exact_table")))
        return description, _comparison_facts(data.get("items"))
    if kind == "timeline":
        if set(data) != {"description", "items", "exact_table"}:
            raise ValueError("timeline block has invalid keys")
        description = _text(data.get("description"), 1_024)
        _table_facts(_mapping(data.get("exact_table")))
        return description, _point_facts(data.get("items"), minimum=2, label_key="label")
    raise ValueError("presentation block kind is unsupported")


def _table_facts(data: Mapping[object, object]) -> tuple[PresentationFact, ...]:
    if set(data) != {"columns", "rows", "status_key"}:
        raise ValueError("presentation table has invalid keys")
    columns = data.get("columns")
    rows = data.get("rows")
    if not isinstance(columns, list) or not 1 <= len(columns) <= 6:
        raise ValueError("presentation table columns are invalid")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        raise ValueError("presentation table rows are invalid")
    parsed = [
        (_text(_mapping(column).get("key"), 64), _text(_mapping(column).get("label"), 512))
        for column in columns
        if set(_mapping(column)) == {"key", "label"}
    ]
    if len(parsed) != len(columns):
        raise ValueError("presentation table column shape is invalid")
    expected = {key for key, _label in parsed}
    facts: list[PresentationFact] = []
    for row_index, raw_row in enumerate(rows, start=1):
        row = _mapping(raw_row)
        if set(row) != expected:
            raise ValueError("presentation table row is invalid")
        facts.extend(
            PresentationFact(f"{row_index}. {label}", _text(row.get(key), 1_024))
            for key, label in parsed
        )
    return tuple(facts)


def _label_value_facts(raw: object) -> tuple[PresentationFact, ...]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        raise ValueError("presentation facts are invalid")
    facts: list[PresentationFact] = []
    for raw_item in raw:
        item = _mapping(raw_item)
        if set(item) not in ({"label", "value"}, {"label", "value", "tone"}):
            raise ValueError("presentation fact shape is invalid")
        facts.append(PresentationFact(_text(item.get("label"), 512), _scalar(item.get("value"))))
    return tuple(facts)


def _chart_facts(raw: object, *, coverage: bool) -> tuple[PresentationFact, ...]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        raise ValueError("presentation chart items are invalid")
    facts: list[PresentationFact] = []
    for raw_item in raw:
        item = _mapping(raw_item)
        expected = {"label", "value", "total", "tone"} if coverage else {"label", "value", "tone"}
        if set(item) != expected:
            raise ValueError("presentation chart item shape is invalid")
        value = _number(item.get("value"))
        if coverage:
            value = f"{value} / {_number(item.get('total'))}"
        facts.append(PresentationFact(_text(item.get("label"), 512), value))
    return tuple(facts)


def _point_facts(
    raw: object,
    *,
    minimum: int,
    label_key: str = "value",
) -> tuple[PresentationFact, ...]:
    if not isinstance(raw, list) or not minimum <= len(raw) <= 40:
        raise ValueError("presentation ordered items are invalid")
    expected = {"timestamp", label_key}
    facts: list[PresentationFact] = []
    for raw_item in raw:
        item = _mapping(raw_item)
        if set(item) != expected:
            raise ValueError("presentation ordered item shape is invalid")
        value = (
            _text(item.get(label_key), 1_024)
            if label_key == "label"
            else _number(item.get(label_key))
        )
        facts.append(PresentationFact(_text(item.get("timestamp"), 64), value))
    return tuple(facts)


def _comparison_facts(raw: object) -> tuple[PresentationFact, ...]:
    if not isinstance(raw, list) or not 2 <= len(raw) <= 5:
        raise ValueError("presentation comparison items are invalid")
    facts: list[PresentationFact] = []
    for raw_item in raw:
        item = _mapping(raw_item)
        if set(item) != {"role", "label", "value"}:
            raise ValueError("presentation comparison item shape is invalid")
        _text(item.get("role"), 64)
        facts.append(PresentationFact(_text(item.get("label"), 512), _number(item.get("value"))))
    return tuple(facts)


def _callout_lines(data: Mapping[object, object]) -> tuple[str, ...]:
    if set(data) != {"tone", "lines"}:
        raise ValueError("presentation callout has invalid keys")
    _text(data.get("tone"), 64)
    return _text_tuple(data.get("lines"), maximum=16)


def _refs(raw: object, allowed: set[str]) -> set[str]:
    refs = set(_text_tuple(raw, maximum=16))
    if not refs or len(refs) != len(cast_sequence(raw)) or not refs.issubset(allowed):
        raise ValueError("presentation evidence refs are unbound")
    return refs


def _text_tuple(raw: object, *, maximum: int, allow_empty: bool = False) -> tuple[str, ...]:
    values = cast_sequence(raw)
    if len(values) > maximum or (not allow_empty and not values):
        raise ValueError("presentation text sequence is invalid")
    parsed = tuple(_text(item, 1_024) for item in values)
    if len(parsed) != len(set(parsed)):
        raise ValueError("presentation text sequence contains duplicates")
    return parsed


def cast_sequence(raw: object) -> Sequence[object]:
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ValueError("presentation sequence is invalid")
    return raw


def _mapping(raw: object) -> Mapping[object, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("presentation mapping is invalid")
    return raw


def _text(raw: object, maximum: int) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > maximum:
        raise ValueError("presentation text is invalid")
    if any(ord(character) < 32 and character not in {"\n", "\t"} for character in raw):
        raise ValueError("presentation text contains control characters")
    return raw


def _scalar(raw: object) -> str:
    return _text(raw, 1_024) if isinstance(raw, str) else _number(raw)


def _number(raw: object) -> str:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError("presentation numeric value is invalid")
    if raw != raw or raw in {float("inf"), float("-inf")}:
        raise ValueError("presentation numeric value MUST be finite")
    return str(raw)


__all__ = [
    "PresentationCapabilities",
    "PresentationEnvelope",
    "PresentationFact",
    "PresentationPayload",
    "PresentationRenderError",
    "PresentationSection",
    "build_fallback_text",
    "normalize_terminal_presentation",
    "serialized_size",
]
