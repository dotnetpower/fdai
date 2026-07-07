"""Parser Protocol + dispatcher.

The Protocol is intentionally minimal:

    snapshot_tree_root: Path  →  ParseReport(rules=(ParsedRule, ...))

A ``ParsedRule`` carries the raw mapping (untyped-yet) plus its
``origin`` (a source-relative path). The loader downstream stamps a
``provenance`` block from the source manifest, so parsers do not
duplicate that responsibility.

Design rules:

- **Parsers are pure functions over the snapshot tree**; they MUST NOT
  reach out to the network or touch state outside the given tree.
- **Parsers only surface structural failures** - unreadable file, wrong
  YAML/JSON shape, top-level mismatch. Semantic errors (unknown
  ActionType, missing Rego file) are the loader's authority.
- **Parsers are deterministic**: two invocations against the same
  snapshot MUST yield the same ordered ``rules`` tuple so the caller
  can hash the output for reproducibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class ParserName(StrEnum):
    """Every parser id the manifest schema accepts.

    Keep aligned with
    ``src/fdai/rule_catalog/schema/source_manifest.schema.json``
    ``parser`` enum; ``build_parser`` fails fast on any value not
    listed here.
    """

    RULE_YAML = "rule-yaml"
    REGO = "rego"
    AZURE_POLICY_JSON = "azure-policy-json"
    CHECKOV_YAML = "checkov-yaml"
    KUBE_BENCH = "kube-bench"
    GATEKEEPER_TEMPLATES = "gatekeeper-templates"


class ParseError(RuntimeError):
    """Structural parse failure - bad YAML, wrong top-level shape, etc."""


class ParserNotImplementedError(NotImplementedError):
    """A manifest referenced a parser id that has no built-in adapter yet.

    Distinct from :class:`ParseError` so a caller can distinguish
    "this snapshot is bad" from "this parser has not been built".
    """


@dataclass(frozen=True, slots=True)
class ParsedRule:
    """One raw rule mapping produced by a parser.

    ``raw`` is deliberately untyped: it is the input the loader
    (``rule_catalog/schema/rule.py``) validates against the shipped
    JSON Schema. ``origin`` is snapshot-relative so a downstream error
    message points at the source file, not a temp path.
    """

    origin: str
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ParseReport:
    """Aggregate of one parser invocation."""

    parser: ParserName
    rules: tuple[ParsedRule, ...] = field(default_factory=tuple)

    @property
    def rule_count(self) -> int:
        return len(self.rules)


@runtime_checkable
class Parser(Protocol):
    """Every parser satisfies this signature."""

    @property
    def name(self) -> ParserName:
        """Parser id - matches the ``parser`` field on the source manifest."""
        ...

    def parse(self, snapshot_tree_root: Path) -> ParseReport:
        """Read the snapshot tree; return the parsed rules.

        Implementations MUST fail closed with :class:`ParseError` on any
        structural mismatch; they MUST NOT attempt to "repair" the
        source.
        """
        ...


def build_parser(name: ParserName | str) -> Parser:
    """Return the built-in parser for ``name``.

    Unknown names raise :class:`ParseError` (typed as a bad manifest,
    not a missing feature). Known-but-not-yet-implemented parsers raise
    :class:`ParserNotImplementedError`.
    """
    # Local imports break the module-level cycle
    # (parser plugins import the Protocol from this module).
    from fdai.rule_catalog.pipeline.parse.azure_policy_json import AzurePolicyJsonParser
    from fdai.rule_catalog.pipeline.parse.kube_bench import KubeBenchParser
    from fdai.rule_catalog.pipeline.parse.rego_parser import RegoParser
    from fdai.rule_catalog.pipeline.parse.rule_yaml import RuleYamlParser

    if isinstance(name, str):
        try:
            resolved = ParserName(name)
        except ValueError as exc:
            valid = ", ".join(sorted(p.value for p in ParserName))
            raise ParseError(f"unknown parser {name!r}; valid parsers: {valid}") from exc
    else:
        resolved = name

    if resolved is ParserName.RULE_YAML:
        return RuleYamlParser()
    if resolved is ParserName.REGO:
        return RegoParser()
    if resolved is ParserName.AZURE_POLICY_JSON:
        return AzurePolicyJsonParser()
    if resolved is ParserName.KUBE_BENCH:
        return KubeBenchParser()

    raise ParserNotImplementedError(
        f"parser {resolved.value!r} is declared in the manifest schema but "
        "has no built-in adapter yet"
    )
