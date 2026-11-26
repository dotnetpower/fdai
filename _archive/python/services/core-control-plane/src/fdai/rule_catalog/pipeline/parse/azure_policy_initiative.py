"""Parser for Azure Policy Set Definitions (initiatives).

This offline helper reads Azure Policy Set Definitions and emits profile intent
records. It is not registered in ``build_parser`` and no approved source
manifest selects it. The shipped collected profiles are reviewed static catalog
artifacts; this helper does not claim a reproducible collector path for them.

The helper emits source GUIDs only and does not join them to imported FDAI Rule
ids. A future automated profile refresh requires its own approved source
manifest, GUID-to-Rule compiler, and focused end-to-end test.
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

    Emits :class:`ParsedRule` containers whose ``raw`` mapping is an
    intermediate profile-intent shape, not the Rule schema. Callers must not
    pass these records to the Rule verifier.
    """

    @property
    def name(self) -> ParserName:
        # The helper predates a dedicated manifest parser id. It remains
        # unregistered until an approved profile-refresh design adds one.
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
