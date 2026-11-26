"""Semantic InterfaceType catalog boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.interface_type import (
    InterfaceTypeCatalogError,
    load_interface_implementation_catalog,
    load_interface_type_catalog,
)
from fdai.rule_catalog.schema.ontology_provenance import ontology_content_hash
from fdai.shared.contracts.models import (
    OntologyInterfaceType,
    OntologyObjectType,
    PropertyDecl,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry


def _interface_raw() -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": "1.0.0",
        "name": "Identifiable",
        "version": "1.0.0",
        "properties": {"id": {"type": "string", "required": True}},
        "extends": [],
        "provenance": {
            "source_url": "https://github.com/dotnetpower/fdai",
            "resolved_ref": "interface-type:Identifiable@1.0.0",
            "content_hash": "sha256:" + ("0" * 64),
            "license": "MIT",
            "retrieved_at": "2026-08-10T00:00:00Z",
        },
    }
    model = OntologyInterfaceType.model_validate(raw)
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = ontology_content_hash(model)
    return raw


def _resource() -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type="string", required=True)},
    )


def test_interface_catalog_loads_declaration_and_binding(tmp_path: Path) -> None:
    declaration_root = tmp_path / "interface-types"
    implementation_root = tmp_path / "interface-implementations"
    declaration_root.mkdir()
    implementation_root.mkdir()
    (declaration_root / "Identifiable.yaml").write_text(
        yaml.safe_dump(_interface_raw(), sort_keys=False),
        encoding="utf-8",
    )
    (implementation_root / "Identifiable.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "interface": "Identifiable",
                "object_types": ["Resource"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    registry = PackageResourceSchemaRegistry()

    interfaces = load_interface_type_catalog(declaration_root, schema_registry=registry)
    bindings = load_interface_implementation_catalog(
        implementation_root,
        schema_registry=registry,
        interfaces=interfaces,
        object_types=(_resource(),),
    )

    assert interfaces[0].name == "Identifiable"
    assert bindings[0].object_type == "Resource"
    assert bindings[0].interfaces == ("Identifiable",)


def test_interface_binding_rejects_unknown_object_type(tmp_path: Path) -> None:
    implementation_root = tmp_path / "interface-implementations"
    implementation_root.mkdir()
    (implementation_root / "Identifiable.yaml").write_text(
        "schema_version: 1.0.0\ninterface: Identifiable\nobject_types: [Missing]\n",
        encoding="utf-8",
    )
    interface = OntologyInterfaceType.model_validate(_interface_raw())

    with pytest.raises(InterfaceTypeCatalogError, match="unknown ObjectType 'Missing'"):
        load_interface_implementation_catalog(
            implementation_root,
            schema_registry=PackageResourceSchemaRegistry(),
            interfaces=(interface,),
            object_types=(_resource(),),
        )
