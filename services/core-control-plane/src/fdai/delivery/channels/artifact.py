"""Normalize one verified presentation artifact for pure channel rendering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from fdai.shared.providers.channel_presentation import (
    MAX_PRESENTATION_FACTS,
    ChannelPresentationEnvelope,
    ChannelPresentationFact,
    ChannelPresentationSection,
)
from fdai.shared.providers.conversation_channel import OutboundResponse

_COMMON_BLOCK_KEYS = {
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


def normalize_channel_presentation(
    response: OutboundResponse,
    *,
    web_url: str | None = None,
) -> ChannelPresentationEnvelope:
    """Normalize durable response data once or retain canonical text fallback."""
    execution_authority = response.data.get("execution_authority", False)
    if execution_authority is not False:
        raise ValueError("channel presentation response MUST deny execution authority")
    authority_value = response.data.get("authority")
    authority = (
        authority_value.strip()
        if isinstance(authority_value, str) and authority_value.strip()
        else "no_execution_authority"
    )
    limitations = _text_tuple(response.data.get("limitations", ()), maximum=16)
    if web_url is not None and not _valid_web_url(web_url):
        raise ValueError("channel presentation Web URL MUST be HTTPS or same-origin relative")
    artifact = response.data.get("presentation_artifact")
    if artifact is None:
        version: Literal[1, 2] | None = None
        sections: tuple[ChannelPresentationSection, ...] = ()
        artifact_limitations: tuple[str, ...] = ()
        degraded = False
    else:
        try:
            version, sections, artifact_limitations = _normalize_artifact(
                artifact,
                response_refs=set(response.evidence_refs),
            )
            degraded = False
        except ValueError:
            version = None
            sections = ()
            artifact_limitations = ()
            degraded = True
    merged_limitations = tuple(dict.fromkeys((*limitations, *artifact_limitations)))
    return ChannelPresentationEnvelope(
        canonical_text=response.text,
        artifact_version=version,
        sections=sections,
        limitations=merged_limitations,
        evidence_refs=response.evidence_refs,
        authority=authority,
        unavailable=response.status in {"held", "unavailable"}
        or response.data.get("unavailable") is True,
        web_url=web_url,
        artifact_degraded=degraded,
    )


def _normalize_artifact(
    raw: object,
    *,
    response_refs: set[str],
) -> tuple[Literal[1, 2], tuple[ChannelPresentationSection, ...], tuple[str, ...]]:
    if not isinstance(raw, Mapping) or set(raw) != {
        "schema_version",
        "layout",
        "blocks",
        "evidence_refs",
    }:
        raise ValueError("channel presentation artifact shape is invalid")
    raw_version = raw.get("schema_version")
    if raw_version not in {1, 2} or raw.get("layout") != "stack":
        raise ValueError("channel presentation artifact version is unsupported")
    version: Literal[1, 2] = 1 if raw_version == 1 else 2
    artifact_refs = _refs(raw.get("evidence_refs"), response_refs)
    blocks = raw.get("blocks")
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 8:
        raise ValueError("channel presentation artifact blocks are invalid")
    sections: list[ChannelPresentationSection] = []
    limitations: list[str] = []
    fact_count = 0
    slots: set[str] = set()
    for raw_block in blocks:
        if not isinstance(raw_block, Mapping) or set(raw_block) != _COMMON_BLOCK_KEYS:
            raise ValueError("channel presentation block shape is invalid")
        slot_id = _text(raw_block.get("slot_id"), 64)
        kind = _text(raw_block.get("kind"), 64)
        title = _text(raw_block.get("title"), 512)
        if slot_id in slots:
            raise ValueError("channel presentation artifact repeats a slot")
        slots.add(slot_id)
        allowed = _V1_KINDS if version == 1 else _V2_KINDS
        if kind not in allowed:
            raise ValueError("channel presentation block kind is unsupported")
        _refs(raw_block.get("evidence_refs"), artifact_refs)
        data = raw_block.get("data")
        if not isinstance(data, Mapping):
            raise ValueError("channel presentation block data is invalid")
        if kind == "callout":
            limitations.extend(_callout_lines(data))
            continue
        description, facts = _block_facts(kind, data, version=version)
        fact_count += len(facts)
        if fact_count > MAX_PRESENTATION_FACTS:
            raise ValueError("channel presentation artifact exceeds the fact bound")
        sections.append(
            ChannelPresentationSection(
                kind=kind,
                title=title,
                facts=facts,
                description=description,
            )
        )
    return version, tuple(sections), tuple(dict.fromkeys(limitations))


def _block_facts(
    kind: str,
    data: Mapping[object, object],
    *,
    version: int,
) -> tuple[str | None, tuple[ChannelPresentationFact, ...]]:
    if kind in {"summary", "evidence"}:
        if set(data) != {"items"}:
            raise ValueError("channel presentation item block has invalid keys")
        return None, _label_value_facts(data.get("items"))
    if kind in {"table", "threshold_table", "list"}:
        return None, _table_facts(data)
    if kind in {"bar", "coverage"}:
        if version == 1:
            if set(data) != {"items"}:
                raise ValueError("channel presentation v1 chart has invalid keys")
            return None, _chart_facts(data.get("items"), coverage=False)
        if set(data) != {"description", "unit", "items", "exact_table"}:
            raise ValueError("channel presentation v2 chart has invalid keys")
        description = _text(data.get("description"), 1_024)
        _text(data.get("unit"), 64)
        _table_facts(_mapping(data.get("exact_table")))
        return description, _chart_facts(data.get("items"), coverage=kind == "coverage")
    if kind == "time_series":
        if set(data) != {"description", "metric", "unit", "points", "exact_table"}:
            raise ValueError("channel presentation time series has invalid keys")
        description = _text(data.get("description"), 1_024)
        _text(data.get("metric"), 512)
        _text(data.get("unit"), 64)
        _table_facts(_mapping(data.get("exact_table")))
        return description, _time_series_facts(data.get("points"))
    if kind == "comparison":
        if set(data) != {"description", "metric", "unit", "items", "exact_table"}:
            raise ValueError("channel presentation comparison has invalid keys")
        description = _text(data.get("description"), 1_024)
        _text(data.get("metric"), 512)
        _text(data.get("unit"), 64)
        _table_facts(_mapping(data.get("exact_table")))
        return description, _comparison_facts(data.get("items"))
    if kind == "timeline":
        if set(data) != {"description", "items", "exact_table"}:
            raise ValueError("channel presentation timeline has invalid keys")
        description = _text(data.get("description"), 1_024)
        _table_facts(_mapping(data.get("exact_table")))
        return description, _timeline_facts(data.get("items"))
    raise ValueError("channel presentation block kind is unsupported")


def _table_facts(data: Mapping[object, object]) -> tuple[ChannelPresentationFact, ...]:
    if set(data) != {"columns", "rows", "status_key"}:
        raise ValueError("channel presentation table has invalid keys")
    columns = data.get("columns")
    rows = data.get("rows")
    if not isinstance(columns, list) or not 1 <= len(columns) <= 6:
        raise ValueError("channel presentation table columns are invalid")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        raise ValueError("channel presentation table rows are invalid")
    parsed_columns: list[tuple[str, str]] = []
    for column in columns:
        if not isinstance(column, Mapping) or set(column) != {"key", "label"}:
            raise ValueError("channel presentation table column is invalid")
        parsed_columns.append((_text(column.get("key"), 64), _text(column.get("label"), 512)))
    expected_keys = {key for key, _label in parsed_columns}
    facts: list[ChannelPresentationFact] = []
    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping) or set(row) != expected_keys:
            raise ValueError("channel presentation table row is invalid")
        for key, label in parsed_columns:
            facts.append(
                ChannelPresentationFact(
                    label=f"{row_index}. {label}",
                    value=_text(row.get(key), 1_024),
                )
            )
    return tuple(facts)


def _label_value_facts(raw: object) -> tuple[ChannelPresentationFact, ...]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        raise ValueError("channel presentation facts are invalid")
    facts: list[ChannelPresentationFact] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) not in (
            {"label", "value"},
            {"label", "value", "tone"},
        ):
            raise ValueError("channel presentation fact is invalid")
        facts.append(
            ChannelPresentationFact(
                label=_text(item.get("label"), 512),
                value=_scalar_text(item.get("value")),
            )
        )
    return tuple(facts)


def _chart_facts(raw: object, *, coverage: bool) -> tuple[ChannelPresentationFact, ...]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        raise ValueError("channel presentation chart items are invalid")
    facts: list[ChannelPresentationFact] = []
    for item in raw:
        expected = (
            {"label", "value", "total", "tone"}
            if coverage
            else {
                "label",
                "value",
                "tone",
            }
        )
        if not isinstance(item, Mapping) or set(item) != expected:
            raise ValueError("channel presentation chart item is invalid")
        value = _number_text(item.get("value"))
        if coverage:
            value = f"{value} / {_number_text(item.get('total'))}"
        facts.append(
            ChannelPresentationFact(
                label=_text(item.get("label"), 512),
                value=value,
            )
        )
    return tuple(facts)


def _time_series_facts(raw: object) -> tuple[ChannelPresentationFact, ...]:
    if not isinstance(raw, list) or not 3 <= len(raw) <= 40:
        raise ValueError("channel presentation time-series points are invalid")
    facts: list[ChannelPresentationFact] = []
    for point in raw:
        if not isinstance(point, Mapping) or set(point) != {"timestamp", "value"}:
            raise ValueError("channel presentation time-series point is invalid")
        facts.append(
            ChannelPresentationFact(
                label=_text(point.get("timestamp"), 64),
                value=_number_text(point.get("value")),
            )
        )
    return tuple(facts)


def _comparison_facts(raw: object) -> tuple[ChannelPresentationFact, ...]:
    if not isinstance(raw, list) or not 2 <= len(raw) <= 5:
        raise ValueError("channel presentation comparison items are invalid")
    facts: list[ChannelPresentationFact] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"role", "label", "value"}:
            raise ValueError("channel presentation comparison item is invalid")
        _text(item.get("role"), 64)
        facts.append(
            ChannelPresentationFact(
                label=_text(item.get("label"), 512),
                value=_number_text(item.get("value")),
            )
        )
    return tuple(facts)


def _timeline_facts(raw: object) -> tuple[ChannelPresentationFact, ...]:
    if not isinstance(raw, list) or not 2 <= len(raw) <= 40:
        raise ValueError("channel presentation timeline items are invalid")
    facts: list[ChannelPresentationFact] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"timestamp", "label"}:
            raise ValueError("channel presentation timeline item is invalid")
        facts.append(
            ChannelPresentationFact(
                label=_text(item.get("timestamp"), 64),
                value=_text(item.get("label"), 1_024),
            )
        )
    return tuple(facts)


def _callout_lines(data: Mapping[object, object]) -> tuple[str, ...]:
    if set(data) != {"tone", "lines"}:
        raise ValueError("channel presentation callout has invalid keys")
    _text(data.get("tone"), 64)
    return _text_tuple(data.get("lines"), maximum=16)


def _refs(raw: object, allowed: set[str]) -> set[str]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        raise ValueError("channel presentation evidence refs are invalid")
    refs = {_text(item, 1_024) for item in raw}
    if len(refs) != len(raw) or not refs.issubset(allowed):
        raise ValueError("channel presentation evidence refs are unbound")
    return refs


def _text_tuple(raw: object, *, maximum: int) -> tuple[str, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, str) or len(raw) > maximum:
        raise ValueError("channel presentation text sequence is invalid")
    values = tuple(_text(item, 1_024) for item in raw)
    if len(values) != len(set(values)):
        raise ValueError("channel presentation text sequence contains duplicates")
    return values


def _mapping(raw: object) -> Mapping[object, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("channel presentation nested mapping is invalid")
    return raw


def _text(raw: object, maximum: int) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > maximum:
        raise ValueError("channel presentation text is invalid")
    if any(ord(character) < 32 and character not in {"\n", "\t"} for character in raw):
        raise ValueError("channel presentation text contains control characters")
    return raw


def _scalar_text(raw: object) -> str:
    if isinstance(raw, str):
        return _text(raw, 1_024)
    return _number_text(raw)


def _number_text(raw: object) -> str:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError("channel presentation numeric value is invalid")
    if raw != raw or raw in {float("inf"), float("-inf")}:
        raise ValueError("channel presentation numeric value MUST be finite")
    return str(raw)


def _valid_web_url(value: str) -> bool:
    return value.startswith("/") or value.startswith("https://")


__all__ = ["normalize_channel_presentation"]
