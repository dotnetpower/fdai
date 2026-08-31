"""Assemble and verify adaptive schema-v3 presentation artifacts.

The artifact binds layout metadata to the complete render-affecting payload.
It exposes only bounded input categories and never prompt or memory content.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal, cast

from fdai_operator_service.families.conversation.contracts import JsonObject

PresentationLayout = Literal["operational_brief", "markdown_document"]
PresentationInputKind = Literal[
    "incident_projection",
    "operator_locale",
    "presentation_context",
    "verified_semantic_result",
]

_LAYOUTS = frozenset({"operational_brief", "markdown_document"})
_INPUT_ORDER = (
    "verified_semantic_result",
    "presentation_context",
    "incident_projection",
    "operator_locale",
)
_INPUT_KINDS = frozenset(_INPUT_ORDER)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def assemble_presentation_artifact_v3(
    *,
    layout: PresentationLayout,
    blocks: Sequence[JsonObject],
    evidence_refs: Sequence[str],
    locale: str,
    input_kinds: Sequence[PresentationInputKind],
) -> JsonObject:
    """Return one digest-bound adaptive artifact from already verified blocks."""

    if layout not in _LAYOUTS:
        raise ValueError("presentation layout is unsupported")
    if not blocks or len(blocks) > 8:
        raise ValueError("presentation artifact blocks are outside the bounded range")
    ordered_inputs = [kind for kind in _INPUT_ORDER if kind in input_kinds]
    if (
        not ordered_inputs
        or len(ordered_inputs) != len(set(input_kinds))
        or any(kind not in _INPUT_KINDS for kind in input_kinds)
    ):
        raise ValueError("presentation assembly input kinds are invalid")
    korean = locale.casefold().startswith("ko")
    label = (
        "동적으로 조립된 운영 브리프"
        if korean and layout == "operational_brief"
        else "동적으로 조립된 Markdown"
        if korean
        else "Dynamically assembled operational brief"
        if layout == "operational_brief"
        else "Dynamically assembled Markdown"
    )
    artifact = cast(
        JsonObject,
        {
            "schema_version": 3,
            "layout": layout,
            "evidence_refs": list(evidence_refs),
            "blocks": list(blocks),
            "assembly": {
                "mode": "dynamic",
                "label": label,
                "section_count": len(blocks),
                "input_kinds": ordered_inputs,
            },
        },
    )
    assembly = cast(dict[str, object], artifact["assembly"])
    assembly["digest"] = _artifact_digest(artifact)
    return artifact


def verify_presentation_artifact_v3(artifact: Mapping[str, object]) -> None:
    """Reject malformed or modified schema-v3 assembly metadata."""

    if artifact.get("schema_version") != 3 or artifact.get("layout") not in _LAYOUTS:
        raise ValueError("presentation artifact v3 identity is invalid")
    blocks = artifact.get("blocks")
    assembly = artifact.get("assembly")
    if not isinstance(blocks, list) or not isinstance(assembly, Mapping):
        raise ValueError("presentation artifact v3 assembly is missing")
    if set(assembly) != {"mode", "label", "section_count", "input_kinds", "digest"}:
        raise ValueError("presentation artifact v3 assembly shape is invalid")
    label = assembly.get("label")
    input_kinds = assembly.get("input_kinds")
    digest = assembly.get("digest")
    if (
        assembly.get("mode") != "dynamic"
        or not isinstance(label, str)
        or not 1 <= len(label) <= 128
        or assembly.get("section_count") != len(blocks)
        or not isinstance(input_kinds, list)
        or not input_kinds
        or len(input_kinds) > len(_INPUT_ORDER)
        or any(not isinstance(kind, str) or kind not in _INPUT_KINDS for kind in input_kinds)
        or input_kinds != [kind for kind in _INPUT_ORDER if kind in input_kinds]
        or len(input_kinds) != len(set(input_kinds))
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or digest != _artifact_digest(artifact)
    ):
        raise ValueError("presentation artifact v3 assembly is invalid")


def _artifact_digest(artifact: Mapping[str, object]) -> str:
    assembly = artifact.get("assembly")
    if not isinstance(assembly, Mapping):
        raise ValueError("presentation artifact assembly is missing")
    material = {
        **artifact,
        "assembly": {key: value for key, value in assembly.items() if key != "digest"},
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "PresentationInputKind",
    "PresentationLayout",
    "assemble_presentation_artifact_v3",
    "verify_presentation_artifact_v3",
]
