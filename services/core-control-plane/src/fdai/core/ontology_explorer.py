"""Ontology explorer - render the loaded ObjectType / LinkType catalog
into a Mermaid graph.

Deterministic: given the same ObjectType + LinkType tuples the render
is byte-identical, so a fork's PR that adds a new ObjectType shows a
diffable change to the rendered graph. No I/O; the caller loads the
catalogs (see :mod:`fdai.rule_catalog.schema.object_type` +
:mod:`fdai.rule_catalog.schema.link_type`) and hands them in.

Mermaid was picked because:
- GitHub renders it inline in Markdown, so the exported ``.md`` is
  reviewable without a separate viewer.
- Every ObjectType / LinkType concept fits ``classDiagram`` naturally
  (class = ObjectType, association = LinkType, cardinality is native).
- No JavaScript at render time; the SPA does not need a heavy graph
  library, just a Mermaid `<div>` that the browser mounts on demand.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
)

_CARDINALITY_LEFT: dict[LinkCardinality, str] = {
    LinkCardinality.ONE_TO_ONE: '"1"',
    LinkCardinality.ONE_TO_MANY: '"1"',
    LinkCardinality.MANY_TO_ONE: '"*"',
    LinkCardinality.MANY_TO_MANY: '"*"',
}

_CARDINALITY_RIGHT: dict[LinkCardinality, str] = {
    LinkCardinality.ONE_TO_ONE: '"1"',
    LinkCardinality.ONE_TO_MANY: '"*"',
    LinkCardinality.MANY_TO_ONE: '"1"',
    LinkCardinality.MANY_TO_MANY: '"*"',
}


@dataclass(frozen=True, slots=True)
class OntologyGraphRender:
    """Mermaid text + a small manifest of node/edge counts."""

    mermaid: str
    object_type_count: int
    link_type_count: int


def render_ontology_mermaid(
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    *,
    include_properties: bool = True,
    property_limit: int = 8,
) -> OntologyGraphRender:
    """Return a Mermaid ``classDiagram`` for the ontology.

    ``include_properties=False`` produces a slim graph suitable for a
    sidebar preview. When ``True`` (default), each ObjectType lists up
    to ``property_limit`` properties with type + required marker; the
    limit keeps a 100-property object from blowing out the diagram.
    """
    if property_limit < 1:
        raise ValueError("property_limit MUST be >= 1")

    known_types = {ot.name for ot in object_types}
    lines: list[str] = ["classDiagram"]

    for ot in _sorted_by_name(object_types):
        lines.append(f"    class {ot.name} {{")
        if include_properties:
            prop_lines = _property_lines(ot, property_limit)
            lines.extend(f"        {line}" for line in prop_lines)
        lines.append("    }")

    for link in _sorted_by_name(link_types):
        if link.from_type not in known_types or link.to_type not in known_types:
            # Silently drop dangling references; the loader is the
            # authoritative gate against typos. The renderer stays
            # tolerant so a partial catalog (e.g. tests) still draws.
            continue
        lines.append(_edge_line(link))

    return OntologyGraphRender(
        mermaid="\n".join(lines) + "\n",
        object_type_count=len(object_types),
        link_type_count=len(link_types),
    )


def _property_lines(ot: OntologyObjectType, limit: int) -> list[str]:
    """Emit ``+<name>: <type>[!]`` lines, deterministically ordered."""
    all_props = sorted(ot.properties.items())
    shown = all_props[:limit]
    lines = [f"+{name}: {decl.type.value}{'!' if decl.required else ''}" for name, decl in shown]
    remaining = len(all_props) - len(shown)
    if remaining > 0:
        lines.append(f"+... {remaining} more")
    return lines


def _edge_line(link: OntologyLinkType) -> str:
    left = _CARDINALITY_LEFT[link.cardinality]
    right = _CARDINALITY_RIGHT[link.cardinality]
    return f"    {link.from_type} {left} --> {right} {link.to_type} : {link.name}"


def _sorted_by_name(items: Iterable[Any]) -> list[Any]:
    return sorted(items, key=lambda x: x.name)


__all__ = ["OntologyGraphRender", "render_ontology_mermaid"]
