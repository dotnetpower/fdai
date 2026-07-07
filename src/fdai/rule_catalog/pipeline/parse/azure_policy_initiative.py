"""Parser for Azure Policy Set Definitions (initiatives).

Design: an initiative is a curated bundle of Azure Policy definitions
that maps 1:1 onto an FDAI :class:`~fdai.core.rule_catalog_profiles.Profile`.
The parser walks a snapshot tree of `policySetDefinitions/**/*.json`
and, for each initiative, emits a mapping shaped like the FDAI
``profile`` schema. The compile step (in the collector CLI) resolves
the initiative's ``policyDefinitionId`` GUIDs against the imported
``azure-builtin/`` rule tree; a GUID with no imported counterpart is
silently dropped (the initiative may reference a preview / non-public
definition that upstream Azure/azure-policy does not ship).

Output rule ids are the imported FDAI ids (from
``rule-catalog/collected/azure-builtin/**/*.yaml``); the parser itself
does NOT read the imported rules - the compile step does. This keeps
the parser pure over its own snapshot.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from .parser import ParsedRule, ParseError, ParseReport, ParserName

_DEFINITION_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"/providers/Microsoft\.Authorization/policyDefinitions/(?P<guid>[0-9a-f-]+)$",
    re.I,
)


class AzurePolicyInitiativeParser:
    """Parser plugin id ``azure-policy-initiative``.

    Emits :class:`ParsedRule` entries whose ``raw`` mapping is the
    ``profile`` shape (schema id ``profile/1.0.0``), NOT the rule shape.
    That is intentional: the collector CLI writes these under
    ``rule-catalog/profiles/collected/`` after joining them with the
    imported ``azure-builtin`` GUID -> id map.
    """

    @property
    def name(self) -> ParserName:
        # Reuse the azure-policy-json id - the same source repo ships
        # both trees. The compile step distinguishes by the shape of
        # each ParsedRule.raw (`policyDefinitions` field present).
        return ParserName.AZURE_POLICY_JSON

    def parse(self, snapshot_tree_root: Path) -> ParseReport:
        if not snapshot_tree_root.is_dir():
            raise ParseError(
                f"snapshot root does not exist or is not a directory: {snapshot_tree_root}"
            )
        rules: list[ParsedRule] = []
        for path in sorted(snapshot_tree_root.rglob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ParseError(f"{path}: not valid JSON: {exc}") from exc
            if not isinstance(doc, Mapping) or "properties" not in doc:
                continue
            props = doc.get("properties") or {}
            if "policyDefinitions" not in props:
                # Not an initiative - skip.
                continue
            raw = _to_profile_intent(doc, origin=path.relative_to(snapshot_tree_root))
            if raw is None:
                continue
            rules.append(ParsedRule(origin=str(path.relative_to(snapshot_tree_root)), raw=raw))
        return ParseReport(parser=ParserName.AZURE_POLICY_JSON, rules=tuple(rules))


def _to_profile_intent(doc: Mapping[str, Any], *, origin: Path) -> Mapping[str, Any] | None:
    props = doc.get("properties") or {}
    if props.get("policyType") not in ("BuiltIn", "Static", "Custom"):
        return None
    display_name = props.get("displayName")
    if not isinstance(display_name, str) or not display_name:
        return None
    metadata = props.get("metadata") or {}
    category = str(metadata.get("category") or "General")
    version = str(props.get("version") or metadata.get("version") or "1.0.0")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        version = "1.0.0"

    definitions = props.get("policyDefinitions") or []
    guids: list[str] = []
    for entry in definitions:
        if not isinstance(entry, Mapping):
            continue
        raw_id = entry.get("policyDefinitionId") or ""
        m = _DEFINITION_ID_RE.match(str(raw_id))
        if m:
            guids.append(m.group("guid").lower())

    slug = _slugify(display_name)
    profile_id = f"compliance.{_slugify(category)}.{slug}"[:120]
    return {
        "kind": "azure-policy-initiative",
        "profile_id": profile_id,
        "profile_title": display_name,
        "profile_description": props.get("description") or "",
        "category": category,
        "version": version,
        "policy_definition_guids": guids,
        "origin_repo_path": origin.as_posix(),
    }


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug or "profile"


__all__ = ["AzurePolicyInitiativeParser"]
