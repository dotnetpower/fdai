"""``rego`` parser - reads Rego policy modules from a snapshot tree.

Second concrete parser plugin (after :class:`RuleYamlParser`). It walks
the snapshot tree **recursively** for ``*.rego`` modules and emits one
:class:`ParsedRule` per module. Each parsed mapping is deliberately
partial - enough to identify the module and route to the shipped Rego
file - and is stamped with ``resource_type: unknown`` when the source
does not declare one. Downstream normalization is a later stage's job;
this parser only reads what the source provides.

Metadata source (OPA convention): a policy MAY prepend a ``# METADATA``
comment block whose body is a YAML mapping. See
https://open-policy-agent.github.io/gatekeeper/website/docs/library and
the upstream OPA docs for the format. When present and well-formed, we
lift ``custom.resource_type`` (if any) into the parsed mapping;
otherwise we fall back to inferred metadata from the package
declaration (id from the package path, ``resource_type: unknown``).

Fail-closed contract (structural failures only):

- missing ``package`` declaration → :class:`ParseError`.
- a present-but-unparseable ``# METADATA`` block → :class:`ParseError`.
- unreadable file → :class:`ParseError`.

The parser deliberately does NOT verify that ``policies/vendored/...``
actually exists; the shipped catalog's referenced ``.rego`` files are
the loader's cross-check target, and vendored Rego from a fetched OSS
snapshot lives in the snapshot tree (not the repo) so the loader-side
resolver looks it up per-source, not here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fdai.rule_catalog.pipeline.parse.parser import (
    ParsedRule,
    ParseError,
    ParseReport,
    ParserName,
)

_REGO_GLOB = "*.rego"

# Rego identifier rules: letter or underscore, followed by [A-Za-z0-9_].
# Package paths are dot-separated identifiers. This is intentionally
# stricter than the full OPA grammar (no quoted string segments) -
# gatekeeper-library and every mainstream OSS policy tree uses plain
# identifiers, and a stricter match keeps error messages clear.
_PACKAGE_RE = re.compile(
    r"^\s*package\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*(?:#.*)?$",
    re.MULTILINE,
)

_METADATA_MARKER = "# METADATA"


class _MetadataError(Exception):
    """Structural failure inside a ``# METADATA`` comment block."""


@dataclass(frozen=True, slots=True)
class RegoParser:
    """Walks a snapshot tree of Rego modules and returns raw mappings.

    The parser is pure over the snapshot tree - it MUST NOT reach out
    to the network or touch state outside the given path. Two
    invocations against the same tree yield the same ordered tuple.
    """

    name: ParserName = ParserName.REGO

    def parse(self, snapshot_tree_root: Path) -> ParseReport:
        if not snapshot_tree_root.is_dir():
            raise ParseError(f"snapshot tree root MUST be a directory; got {snapshot_tree_root!r}")

        rules: list[ParsedRule] = []
        errors: list[str] = []

        # rglob → recursive walk; sorted by relative path so ordering
        # stays stable across platforms (matches RuleYamlParser).
        for path in sorted(snapshot_tree_root.rglob(_REGO_GLOB)):
            if not path.is_file():
                continue
            relative = path.relative_to(snapshot_tree_root)
            origin = relative.as_posix()

            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append(f"{origin}: unreadable: {exc}")
                continue

            package = _extract_package(text)
            if package is None:
                errors.append(f"{origin}: missing package declaration")
                continue

            try:
                metadata = _extract_metadata(text)
            except _MetadataError as exc:
                errors.append(f"{origin}: {exc}")
                continue
            except yaml.YAMLError as exc:
                errors.append(f"{origin}: invalid METADATA yaml: {exc}")
                continue

            resource_type = _resolve_resource_type(metadata)
            raw = {
                "id": package,
                "resource_type": resource_type,
                "check_logic": {
                    "kind": "rego",
                    "reference": f"policies/vendored/{origin}",
                },
            }
            rules.append(ParsedRule(origin=origin, raw=raw))

        if errors:
            preview = "; ".join(errors[:5])
            suffix = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
            raise ParseError(f"rego parse failed: {preview}{suffix}")

        return ParseReport(parser=ParserName.REGO, rules=tuple(rules))


def _extract_package(text: str) -> str | None:
    """Return the first ``package <path>`` declaration, or ``None``.

    A Rego module without a package declaration is malformed; the
    parser fails closed on ``None``.
    """
    match = _PACKAGE_RE.search(text)
    if match is None:
        return None
    return match.group(1)


def _extract_metadata(text: str) -> Mapping[str, Any] | None:
    """Read an OPA ``# METADATA`` YAML comment block, if present.

    Returns ``None`` when no ``# METADATA`` marker is found (the
    fallback path - id from package, resource_type unknown). Raises
    :class:`_MetadataError` on an empty block or non-mapping body, and
    lets ``yaml.YAMLError`` propagate on malformed YAML - both surface
    as ``ParseError`` in :meth:`RegoParser.parse`.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != _METADATA_MARKER:
            continue

        block: list[str] = []
        for follow in lines[index + 1 :]:
            stripped = follow.rstrip()
            if stripped.startswith("# "):
                block.append(stripped[2:])
            elif stripped == "#":
                block.append("")
            else:
                break

        if not block:
            raise _MetadataError("METADATA block is empty")

        data = yaml.safe_load("\n".join(block))
        if data is None:
            raise _MetadataError("METADATA block parsed to null")
        if not isinstance(data, Mapping):
            raise _MetadataError("METADATA body must be a YAML mapping")
        return data

    return None


def _resolve_resource_type(metadata: Mapping[str, Any] | None) -> str:
    """Lift ``custom.resource_type`` from OPA metadata, or fall back.

    A non-string / empty value falls back to ``"unknown"`` so the
    normalizer stage downstream can flag it consistently with the
    no-metadata path.
    """
    if metadata is None:
        return "unknown"
    custom = metadata.get("custom")
    if not isinstance(custom, Mapping):
        return "unknown"
    value = custom.get("resource_type")
    if isinstance(value, str) and value:
        return value
    return "unknown"
