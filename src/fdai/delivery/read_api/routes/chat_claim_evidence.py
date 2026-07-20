"""Collect bounded evidence entries from a chat view snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

from fdai.delivery.read_api.routes.chat_claim_models import EvidenceEntry
from fdai.delivery.read_api.routes.chat_claim_text import (
    ID_RE,
    NUMBER_RE,
    PERCENT_RE,
    anchors,
    decimal_value,
    normalize_claim_value,
    normalize_number,
    normalize_text,
    normalize_timestamp,
    optional_text,
    overlaps,
)

MAX_EVIDENCE_ENTRIES: Final = 512


def collect_evidence(view_context: Mapping[str, Any]) -> tuple[EvidenceEntry, ...]:
    entries: list[EvidenceEntry] = []
    for field in ("headline", "routeLabel", "purpose"):
        value = view_context.get(field)
        if isinstance(value, str) and value:
            append_entry(
                entries,
                ref=f"snapshot:{field}",
                path=f"/{field}",
                field=field,
                value=value,
                extra_anchors=(),
            )
    facts = view_context.get("facts")
    if isinstance(facts, Sequence) and not isinstance(facts, (str, bytes)):
        for index, fact in enumerate(facts):
            if not isinstance(fact, Mapping):
                continue
            field = optional_text(fact.get("key")) or f"fact_{index}"
            label = optional_text(fact.get("label"))
            raw_aliases = fact.get("aliases")
            aliases = (
                tuple(
                    alias.strip()
                    for alias in raw_aliases
                    if isinstance(alias, str) and alias.strip()
                )
                if isinstance(raw_aliases, Sequence) and not isinstance(raw_aliases, (str, bytes))
                else ()
            )
            append_entry(
                entries,
                ref=f"snapshot:fact:{field}",
                path=f"/facts/{index}/value",
                field=field,
                value=fact.get("value"),
                extra_anchors=(str(fact.get("group", "")),),
                aliases=tuple(dict.fromkeys((*(filter(None, (label,))), *aliases))),
            )
    records = view_context.get("records")
    if isinstance(records, Mapping):
        for collection, rows in records.items():
            if not isinstance(collection, str):
                continue
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            for row_index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    continue
                row_anchors = tuple(
                    str(row[key])
                    for key in ("name", "key", "link", "from", "to", "neighbor", "label")
                    if row.get(key) is not None
                    and isinstance(row.get(key), (str, int, float, bool))
                )
                for field, value in row.items():
                    if not isinstance(field, str):
                        continue
                    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                        for value_index, item in enumerate(value):
                            append_entry(
                                entries,
                                ref=(
                                    f"snapshot:record:{collection}:{row_index}:"
                                    f"{field}:{value_index}"
                                ),
                                path=f"/records/{collection}/{row_index}/{field}/{value_index}",
                                field=field,
                                value=item,
                                extra_anchors=(collection, *row_anchors),
                            )
                        continue
                    append_entry(
                        entries,
                        ref=f"snapshot:record:{collection}:{row_index}:{field}",
                        path=f"/records/{collection}/{row_index}/{field}",
                        field=field,
                        value=value,
                        extra_anchors=(collection, *row_anchors),
                    )
    explanations = view_context.get("explanations")
    if isinstance(explanations, Mapping):
        collect_nested_evidence(
            entries,
            explanations,
            ref_prefix="snapshot:explanations",
            path_prefix="/explanations",
        )
    _collect_server_evidence(entries, view_context)
    return tuple(entries)


def _collect_server_evidence(
    entries: list[EvidenceEntry],
    view_context: Mapping[str, Any],
) -> None:
    sources = (
        ("_tool_evidence", "result", "tool:result", "/_tool_evidence/result"),
        ("_agent_evidence", None, "agent", "/_agent_evidence"),
        ("_concept_evidence", "entries", "glossary:entries", "/_concept_evidence/entries"),
    )
    for context_key, child_key, ref_prefix, path_prefix in sources:
        source = view_context.get(context_key)
        if not isinstance(source, Mapping):
            continue
        value = source.get(child_key) if child_key is not None else source
        collect_nested_evidence(
            entries,
            value,
            ref_prefix=ref_prefix,
            path_prefix=path_prefix,
        )
    web = view_context.get("_web_evidence")
    if isinstance(web, Mapping) and web.get("status") == "matched":
        collect_nested_evidence(
            entries,
            web.get("snippets"),
            ref_prefix="web:snippets",
            path_prefix="/_web_evidence/snippets",
        )


def collect_nested_evidence(
    entries: list[EvidenceEntry],
    value: Any,
    *,
    ref_prefix: str,
    path_prefix: str,
) -> None:
    if len(entries) >= MAX_EVIDENCE_ENTRIES:
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                collect_nested_evidence(
                    entries,
                    item,
                    ref_prefix=f"{ref_prefix}:{key}",
                    path_prefix=f"{path_prefix}/{key}",
                )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            collect_nested_evidence(
                entries,
                item,
                ref_prefix=f"{ref_prefix}:{index}",
                path_prefix=f"{path_prefix}/{index}",
            )
        return
    append_entry(
        entries,
        ref=ref_prefix,
        path=path_prefix,
        field=ref_prefix.rsplit(":", 1)[-1],
        value=value,
        extra_anchors=(),
    )


def append_entry(
    entries: list[EvidenceEntry],
    *,
    ref: str,
    path: str,
    field: str,
    value: Any,
    extra_anchors: tuple[str, ...],
    aliases: tuple[str, ...] = (),
) -> None:
    if len(entries) >= MAX_EVIDENCE_ENTRIES:
        return
    if value is None or isinstance(value, (Mapping, Sequence)) and not isinstance(value, str):
        return
    if isinstance(value, bool):
        raw, kind, normalized = (
            ("true" if value else "false"),
            "boolean",
            ("true" if value else "false"),
        )
    elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        raw, kind = str(value), "number"
        normalized = normalize_number(raw) or raw
    elif isinstance(value, str):
        raw = value
        identifier = ID_RE.fullmatch(raw.strip())
        timestamp = normalize_timestamp(raw)
        percentage = PERCENT_RE.fullmatch(raw.strip())
        number_match = NUMBER_RE.fullmatch(raw.strip())
        if identifier is not None:
            kind, normalized = "id", raw.strip()
        elif timestamp is not None:
            kind, normalized = "timestamp", timestamp
        elif percentage is not None:
            kind = "percentage"
            normalized = normalize_claim_value("percentage", raw) or normalize_text(raw)
        elif number_match is not None:
            kind, normalized = "number", normalize_number(raw) or normalize_text(raw)
        else:
            kind, normalized = "text", normalize_text(raw)
    else:
        return
    entry_anchors = anchors(" ".join((field, *extra_anchors, raw if kind == "text" else "")))
    entries.append(EvidenceEntry(ref, path, field, kind, raw, normalized, entry_anchors, aliases))
    if kind == "text":
        _append_embedded_entries(entries, ref, path, field, raw, entry_anchors, aliases)
    if kind == "number" and is_ratio_field(field):
        ratio_value = decimal_value(raw)
        if ratio_value is not None and Decimal("0") <= ratio_value <= Decimal("1"):
            percent = normalize_number(str(ratio_value * 100))
            if percent is not None:
                entries.append(
                    EvidenceEntry(
                        f"{ref}:percent",
                        path,
                        field,
                        "percentage",
                        f"{percent}%",
                        percent,
                        entry_anchors,
                        aliases,
                    )
                )


def _append_embedded_entries(
    entries: list[EvidenceEntry],
    ref: str,
    path: str,
    field: str,
    raw: str,
    entry_anchors: tuple[str, ...],
    aliases: tuple[str, ...],
) -> None:
    occupied: list[tuple[int, int]] = []
    for index, match in enumerate(ID_RE.finditer(raw)):
        occupied.append((match.start(), match.end()))
        entries.append(
            EvidenceEntry(
                f"{ref}:id:{index}",
                path,
                field,
                "id",
                match.group(0),
                match.group(0),
                entry_anchors,
                aliases,
            )
        )
    for index, match in enumerate(PERCENT_RE.finditer(raw)):
        if overlaps(match.start(), match.end(), occupied):
            continue
        normalized = normalize_claim_value("percentage", match.group(0))
        if normalized is not None:
            occupied.append((match.start(), match.end()))
            entries.append(
                EvidenceEntry(
                    f"{ref}:percentage:{index}",
                    path,
                    field,
                    "percentage",
                    match.group(0),
                    normalized,
                    entry_anchors,
                    aliases,
                )
            )
    for index, match in enumerate(NUMBER_RE.finditer(raw)):
        if overlaps(match.start(), match.end(), occupied):
            continue
        normalized = normalize_number(match.group(0))
        if normalized is not None:
            entries.append(
                EvidenceEntry(
                    f"{ref}:number:{index}",
                    path,
                    field,
                    "number",
                    match.group(0),
                    normalized,
                    entry_anchors,
                    aliases,
                )
            )


def is_ratio_field(field: str) -> bool:
    lower = field.lower()
    return any(token in lower for token in ("rate", "ratio", "share", "confidence"))
