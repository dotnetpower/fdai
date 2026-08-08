"""Tests for the ObjectType codegen (module + CLI)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.codegen.new_object_type import (
    ObjectTypeSpec,
    PropertySpec,
    render_object_type_yaml,
)
from fdai.rule_catalog.codegen.new_object_type_cli import main as cli_main
from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry


def _load_yaml(text: str) -> dict:
    return yaml.safe_load(text)


def test_render_produces_loader_valid_yaml() -> None:
    spec = ObjectTypeSpec(
        name="Widget",
        key="id",
        properties=(
            PropertySpec(name="id", type="string", required=True),
            PropertySpec(name="label", type="string"),
        ),
    )
    text = render_object_type_yaml(spec)
    doc = _load_yaml(text)
    # Round-trip through the loader as an extra safety layer.
    model = load_object_type_from_mapping(doc, schema_registry=PackageResourceSchemaRegistry())
    assert model.name == "Widget"
    assert model.key == "id"
    assert set(model.properties.keys()) == {"id", "label"}


def test_render_emits_access_scope_and_purpose_binding() -> None:
    spec = ObjectTypeSpec(
        name="Sensitive",
        key="id",
        properties=(
            PropertySpec(name="id", type="string", required=True),
            PropertySpec(
                name="secret",
                type="string",
                access_scope="owner",
                purpose_binding=("audit-review",),
            ),
        ),
    )
    doc = _load_yaml(render_object_type_yaml(spec))
    assert doc["properties"]["secret"]["access_scope"] == "owner"
    assert doc["properties"]["secret"]["purpose_binding"] == ["audit-review"]
    # Default (reader) scope MUST NOT be emitted - keep the YAML tidy.
    assert "access_scope" not in doc["properties"]["id"]


def test_spec_rejects_non_pascalcase_name() -> None:
    with pytest.raises(ValueError, match="PascalCase"):
        ObjectTypeSpec(
            name="lowerBad",
            key="id",
            properties=(PropertySpec(name="id", type="string", required=True),),
        )


def test_spec_rejects_key_not_in_properties() -> None:
    with pytest.raises(ValueError, match="MUST name a declared property"):
        ObjectTypeSpec(
            name="Ok",
            key="missing",
            properties=(PropertySpec(name="id", type="string", required=True),),
        )


def test_spec_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="not in"):
        ObjectTypeSpec(
            name="Ok",
            key="id",
            properties=(PropertySpec(name="id", type="bogus", required=True),),
        )


def test_spec_rejects_empty_properties() -> None:
    with pytest.raises(ValueError, match="at least one property"):
        ObjectTypeSpec(name="Empty", key="id", properties=())


def test_cli_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(
        [
            "--name",
            "Widget",
            "--key",
            "id",
            "--property",
            "id:string:required=true",
            "--property",
            "label:string",
            "--description",
            "One widget.",
        ]
    )
    assert rc == 0
    text = capsys.readouterr().out
    doc = _load_yaml(text)
    assert doc["name"] == "Widget"
    assert doc["description"] == "One widget."
    assert doc["properties"]["id"]["required"] is True


def test_cli_writes_to_file(tmp_path: Path) -> None:
    out = tmp_path / "Widget.yaml"
    cli_main(
        [
            "--name",
            "Widget",
            "--key",
            "id",
            "--property",
            "id:string:required=true",
            "--out",
            str(out),
        ]
    )
    assert out.is_file()
    doc = _load_yaml(out.read_text())
    assert doc["name"] == "Widget"


def test_cli_refuses_to_overwrite_without_flag(tmp_path: Path) -> None:
    out = tmp_path / "Widget.yaml"
    out.write_text("existing")
    with pytest.raises(SystemExit, match="already exists"):
        cli_main(
            [
                "--name",
                "Widget",
                "--key",
                "id",
                "--property",
                "id:string:required=true",
                "--out",
                str(out),
            ]
        )


def test_cli_overwrite_flag_allows_replacement(tmp_path: Path) -> None:
    out = tmp_path / "Widget.yaml"
    out.write_text("existing")
    cli_main(
        [
            "--name",
            "Widget",
            "--key",
            "id",
            "--property",
            "id:string:required=true",
            "--out",
            str(out),
            "--overwrite",
        ]
    )
    doc = _load_yaml(out.read_text())
    assert doc["name"] == "Widget"


def test_cli_parses_purpose_binding_csv() -> None:
    """Regression: purpose-binding=a,b splits on comma without commas leaking into names."""
    from fdai.rule_catalog.codegen.new_object_type_cli import _parse_property

    spec = _parse_property("field:string:purpose-binding=audit-review,incident-response")
    assert spec.purpose_binding == ("audit-review", "incident-response")


def test_cli_rejects_unknown_property_attribute() -> None:
    import argparse

    from fdai.rule_catalog.codegen.new_object_type_cli import _parse_property

    with pytest.raises(argparse.ArgumentTypeError, match="unknown attribute"):
        _parse_property("field:string:unknown=1")
