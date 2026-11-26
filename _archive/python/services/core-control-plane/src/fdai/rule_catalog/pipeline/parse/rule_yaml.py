"""``rule-yaml`` parser - the seed-source parser.

Reads every ``*.yaml`` file under the snapshot tree (non-recursive on
the tree root - matches the on-disk layout of the shipped catalog
under ``rule-catalog/catalog/``), fails closed on malformed YAML, and
returns one :class:`ParsedRule` per file. The loader downstream
validates the mappings against the ``rule/1.0.0`` JSON Schema and
cross-refs; this parser does NOT.

This parser is the closing half of the seed loop: point the collector
at the shipped catalog (``fdai-p1-seed`` manifest) and this
parser hands the same YAMLs back - proving fetch → snapshot → parse
round-trips without loss.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from fdai.rule_catalog.pipeline.parse.parser import (
    ParsedRule,
    ParseError,
    ParseReport,
    ParserName,
)

_RULE_YAML_GLOB = "*.yaml"


@dataclass(frozen=True, slots=True)
class RuleYamlParser:
    """Consumes a snapshot tree of already-normalized rule YAMLs."""

    name: ParserName = ParserName.RULE_YAML

    def parse(self, snapshot_tree_root: Path) -> ParseReport:
        if not snapshot_tree_root.is_dir():
            raise ParseError(f"snapshot tree root MUST be a directory; got {snapshot_tree_root!r}")

        rules: list[ParsedRule] = []
        errors: list[str] = []
        # Sorted glob → deterministic ordering; the collector's hash and
        # the parser's output order stay stable across platforms.
        for path in sorted(snapshot_tree_root.glob(_RULE_YAML_GLOB)):
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh)
            except yaml.YAMLError as exc:
                errors.append(f"{path.name}: invalid YAML: {exc}")
                continue
            if not isinstance(raw, Mapping):
                errors.append(f"{path.name}: top-level must be a mapping")
                continue
            rules.append(
                ParsedRule(
                    origin=path.name,
                    raw=dict(raw),
                )
            )

        if errors:
            preview = "; ".join(errors[:5])
            suffix = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
            raise ParseError(f"rule-yaml parse failed: {preview}{suffix}")

        return ParseReport(parser=ParserName.RULE_YAML, rules=tuple(rules))
