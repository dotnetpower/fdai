"""Pinned Korean reader-text overlays and build-time coverage validation."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

LOCALIZATION_SOURCE = Path("rule-catalog/guidance/azure-wara/reader-text-ko.json")
_OFFICIAL_NAME_ONLY = {
    "API Management Premium",
    "Application Gateway v2",
    "Azure Backup",
    "Azure Files",
    "Azure Linux VM Agent",
    "Azure Monitor",
    "Azure SQL",
    "Key Vault",
    "Microsoft Azure",
    "Recovery Services vault",
    "Standard Load Balancer",
    "Standard Virtual WAN",
    "Stream Analytics StandardV2",
    "VM Insights",
    "Virtual Network",
    "Windows VSS",
}
_OFFICIAL_PHRASES = (
    "Azure Backup",
    "Azure VM",
    "Microsoft.Compute/virtualMachines",
    "Recovery Services vault",
    "Windows VSS",
)
_ENGLISH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "use",
    "used",
    "using",
    "with",
}
_READER_FIELDS = {
    "title",
    "summary",
    "benefits",
    "rationale",
    "applicability",
    "configuration",
    "implementation_steps",
    "verification_steps",
    "cautions",
    "diagram",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate key in WARA Korean reader-text source: {key}")
        result[key] = value
    return result


def load_reader_text(
    path: Path, *, framework_revision: str, framework_digest: str
) -> dict[str, dict[str, Any]]:
    source = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if source.get("schema_version") != "1.0.0":
        raise ValueError("Unsupported WARA Korean reader-text schema")
    if (
        source.get("framework_revision") != framework_revision
        or source.get("framework_digest") != framework_digest
    ):
        raise ValueError("Korean reader text does not match the pinned WARA source")
    entries = source.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("Korean reader text must contain an entry map")
    return entries


def apply_reader_text(entry: dict[str, Any], source_entries: dict[str, dict[str, Any]]) -> None:
    record = source_entries.get(entry["recommendation_id"])
    if record is None:
        return
    if (
        record.get("source_revision") != entry["source_revision"]
        or record.get("source_digest") != entry["source_digest"]
    ):
        raise ValueError(f"Korean reader text source pin drift for {entry['recommendation_id']}")
    content = record.get("content")
    if not isinstance(content, dict):
        raise ValueError(f"Korean reader text is malformed for {entry['recommendation_id']}")
    unexpected = set(content) - _READER_FIELDS
    if unexpected:
        raise ValueError(
            "Korean reader text cannot change source identity or machine fields: "
            + ", ".join(sorted(unexpected))
        )
    if "diagram" in content:
        diagram = content["diagram"]
        if not isinstance(diagram, dict) or (
            diagram.get("id") != entry["diagram"]["id"]
            or diagram.get("kind") != entry["diagram"]["kind"]
        ):
            raise ValueError(
                "Korean reader text cannot change diagram identity for "
                f"{entry['recommendation_id']}"
            )
    localized_content = dict(content)
    for field in ("title", "summary", "benefits"):
        if field not in content:
            continue
        translation = content[field]
        if not isinstance(translation, dict) or translation.get("en") != entry[field]["en"]:
            raise ValueError(
                f"Korean reader text English source drift for {entry['recommendation_id']}:{field}"
            )
        localized_content[field] = {**entry[field], "ko": translation.get("ko")}
    entry.update(localized_content)


def reader_text_gaps(
    entries: list[dict[str, Any]], expected_ids: set[str] | None = None
) -> list[tuple[str, str]]:
    gaps: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        recommendation_id = entry.get("recommendation_id", "<unknown>")
        seen.add(recommendation_id)
        _collect_gaps(entry, recommendation_id, (), gaps)
    if expected_ids is not None:
        gaps.extend(
            (recommendation_id, "$entry") for recommendation_id in sorted(expected_ids - seen)
        )
    return gaps


def assert_korean_reader_text(entries: list[dict[str, Any]], expected_ids: set[str]) -> None:
    gaps = reader_text_gaps(entries, expected_ids)
    if not gaps:
        return
    sample = ", ".join(f"{guid}:{path}" for guid, path in gaps[:8])
    raise ValueError(
        "WARA Korean reader-text coverage is incomplete: "
        f"{len(gaps)} fields across {len({guid for guid, _ in gaps})} recommendations; "
        f"first gaps: {sample}"
    )


def _collect_gaps(
    value: Any,
    recommendation_id: str,
    path: tuple[str, ...],
    gaps: list[tuple[str, str]],
) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("en"), str):
            if path[:1] == ("sources",) and path[-1:] == ("label",):
                return
            english = value["en"].strip()
            korean = value.get("ko")
            if (
                not isinstance(korean, str)
                or not korean.strip()
                or _is_english_wrapper(english, korean.strip())
            ):
                gaps.append((recommendation_id, ".".join(path)))
            return
        for key, child in value.items():
            _collect_gaps(child, recommendation_id, (*path, key), gaps)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_gaps(child, recommendation_id, (*path, str(index)), gaps)


def _is_english_wrapper(english: str, korean: str) -> bool:
    if not english or korean == english:
        return english not in _OFFICIAL_NAME_ONLY and not _is_acronym(english)
    english_projection = _compact(english)
    korean_projection = _compact(_without_hangul(korean))
    if (
        english_projection
        and english_projection == korean_projection
        and english not in _OFFICIAL_NAME_ONLY
        and not _is_acronym(english)
    ):
        return True
    source_words = {
        word
        for word in re.findall(r"[a-z0-9]+", _without_official_phrases(english).casefold())
        if len(word) > 2 and word not in _ENGLISH_STOP_WORDS
    }
    remaining_english = set(re.findall(r"[a-z0-9]+", _without_official_phrases(korean).casefold()))
    if len(source_words) >= 4:
        retained = len(source_words & remaining_english)
        if retained / len(source_words) >= 0.75:
            return True
    letters = [character for character in korean if character.isalpha()]
    hangul = sum(unicodedata.name(character, "").startswith("HANGUL ") for character in letters)
    return len(letters) >= 24 and hangul / len(letters) < 0.15


def _is_acronym(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*", value.strip()))


def _compact(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _without_hangul(value: str) -> str:
    return "".join(
        character
        for character in value
        if not unicodedata.name(character, "").startswith("HANGUL ")
    )


def _without_official_phrases(value: str) -> str:
    pattern = "|".join(re.escape(phrase) for phrase in _OFFICIAL_PHRASES)
    return re.sub(pattern, "", value, flags=re.IGNORECASE)
