"""Tests for :mod:`fdai.core.ontology_explorer`."""

from __future__ import annotations

from pathlib import Path

from fdai.core.ontology_explorer import render_ontology_mermaid
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import (
    load_object_type_catalog,
    load_object_type_from_mapping,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
OBJECT_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
LINK_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def test_shipped_ontology_renders_mermaid() -> None:
    objects = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=_registry())
    links = load_link_type_catalog(
        LINK_TYPES_ROOT, schema_registry=_registry(), object_types=objects
    )
    rendered = render_ontology_mermaid(objects, links)
    assert rendered.object_type_count == len(objects)
    assert rendered.link_type_count == len(links)
    assert rendered.mermaid.startswith("classDiagram\n")
    # Every ObjectType surfaces as a `class`; every LinkType surfaces
    # once as a labelled edge.
    for ot in objects:
        assert f"class {ot.name} {{" in rendered.mermaid
    for link in links:
        assert f": {link.name}" in rendered.mermaid


def test_render_is_deterministic() -> None:
    objects = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=_registry())
    links = load_link_type_catalog(
        LINK_TYPES_ROOT, schema_registry=_registry(), object_types=objects
    )
    first = render_ontology_mermaid(objects, links)
    second = render_ontology_mermaid(objects, links)
    assert first.mermaid == second.mermaid


def test_render_without_properties_is_slim() -> None:
    objects = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=_registry())
    links = load_link_type_catalog(
        LINK_TYPES_ROOT, schema_registry=_registry(), object_types=objects
    )
    with_props = render_ontology_mermaid(objects, links, include_properties=True)
    slim = render_ontology_mermaid(objects, links, include_properties=False)
    assert len(slim.mermaid) < len(with_props.mermaid)
    # Slim MUST still list every ObjectType and every edge.
    for ot in objects:
        assert f"class {ot.name} {{" in slim.mermaid


def test_property_limit_truncates_and_marks_remainder() -> None:
    fat = load_object_type_from_mapping(
        {
            "schema_version": "1.0.0",
            "name": "Fat",
            "version": "1.0.0",
            "key": "id",
            "properties": {
                "id": {"type": "string", "required": True},
                "a": {"type": "string"},
                "b": {"type": "string"},
                "c": {"type": "string"},
                "d": {"type": "string"},
                "e": {"type": "string"},
                "f": {"type": "string"},
                "g": {"type": "string"},
                "h": {"type": "string"},
                "i": {"type": "string"},
            },
        },
        schema_registry=_registry(),
    )
    rendered = render_ontology_mermaid([fat], [], property_limit=3)
    # 3 shown, 10 total => "... 7 more" marker.
    assert "+... 7 more" in rendered.mermaid


def test_dangling_link_type_is_dropped_but_others_survive(tmp_path: Path) -> None:
    """A LinkType pointing at a missing ObjectType is silently dropped by the renderer."""
    objects = load_object_type_catalog(OBJECT_TYPES_ROOT, schema_registry=_registry())
    real_links = load_link_type_catalog(
        LINK_TYPES_ROOT, schema_registry=_registry(), object_types=objects
    )

    # Fabricate a dangling link via the pydantic model directly (bypasses
    # the loader's cross-check on purpose - the renderer MUST NOT blow up
    # if the caller hands it a partial graph).
    from fdai.shared.contracts.models import LinkCardinality, OntologyLinkType

    dangling = OntologyLinkType(
        schema_version="1.0.0",
        name="ghost_link",
        version="1.0.0",
        from_type="Resource",
        to_type="NotAThing",
        cardinality=LinkCardinality.MANY_TO_ONE,
    )
    rendered = render_ontology_mermaid(objects, list(real_links) + [dangling])
    assert "ghost_link" not in rendered.mermaid
    # But every real link stays in.
    for link in real_links:
        assert f": {link.name}" in rendered.mermaid
