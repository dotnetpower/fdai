"""The customer template exercises pure validators, not a signer or Hub import."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    resolve_configuration_layers,
    validate_configuration_package_for_signing,
    validate_release_configuration_schema,
)

_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _ROOT / "config/lifecycle-configuration-template"
_INSTALLATION = _TEMPLATE / "installations/example-installation"


def _mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict) and all(isinstance(key, str) for key in value)
    return value


def _resolve(version: str) -> dict[str, object]:
    return resolve_configuration_layers(
        release_version=version,
        configuration_schema=_mapping(_TEMPLATE / "release-schema.yaml"),
        environment_config=_mapping(_INSTALLATION / "environment.yaml"),
        entity_overrides=_mapping(_INSTALLATION / "entities/core.yaml")["overrides"],
        sealed_keys=_mapping(_INSTALLATION / "sealed.yaml"),
    ).values


def test_customer_template_has_only_the_declared_yaml_inputs() -> None:
    assert {path.relative_to(_TEMPLATE).as_posix() for path in _TEMPLATE.rglob("*.yaml")} == {
        "release-schema.yaml",
        "installations/example-installation/installation.yaml",
        "installations/example-installation/environment.yaml",
        "installations/example-installation/sealed.yaml",
        "installations/example-installation/entities/core.yaml",
    }
    assert not list(_TEMPLATE.rglob("*.pem"))
    assert not (_TEMPLATE / ".github").exists()


def test_customer_template_uses_annotated_non_authority_configuration() -> None:
    schema = _mapping(_TEMPLATE / "release-schema.yaml")
    validate_release_configuration_schema(schema)
    assert all(entry["x-fdai-owner"] == "customer" for entry in schema.values())
    installation = _mapping(_INSTALLATION / "installation.yaml")
    assert installation["channel"] == "DEV"
    assert installation["entities"] == ["core"]


def test_customer_template_resolves_the_most_specific_release_layer() -> None:
    values = _resolve("1.5.2")
    assert values["replicas"] == 3
    assert values["region"] == "<azure-region>"
    assert values["credential_ref"] == "kv://example-vault/example-token"
    assert _resolve("1.4.0")["replicas"] == 2


def test_customer_template_does_not_cover_a_new_major_version() -> None:
    with pytest.raises(ConfigurationValidationError) as error:
        _resolve("2.0.0")
    assert error.value.code == "missing_matching_override_block"


@pytest.mark.parametrize("axis", ["approval-profile", "standing-authority", "action-lifecycle"])
def test_customer_template_cannot_add_an_authority_axis(axis: str) -> None:
    schema = _mapping(_TEMPLATE / "release-schema.yaml")
    schema["unsafe"] = {"x-fdai-axis": axis, "x-fdai-owner": "customer", "default": "value"}
    with pytest.raises(ConfigurationValidationError) as error:
        validate_release_configuration_schema(schema)
    assert error.value.code == "unsupported_configuration_axis"


def test_customer_template_keeps_identifiers_out_of_readable_configuration() -> None:
    sealed = _mapping(_INSTALLATION / "sealed.yaml")
    assert (
        sealed["tenant_id"] == sealed["subscription_id"] == "00000000-0000-0000-0000-000000000000"
    )
    assert sealed["resource_group"] == "<resource-group>"
    assert set(sealed["endpoints"].values()) == {
        "https://model-primary.example.com",
        "https://model-secondary.example.com",
    }
    assert set(sealed).isdisjoint(_resolve("1.5.2"))
    schema = _mapping(_TEMPLATE / "release-schema.yaml")
    environment = _mapping(_INSTALLATION / "environment.yaml")
    environment["tenant_id"] = sealed["tenant_id"]
    with pytest.raises(ConfigurationValidationError) as error:
        resolve_configuration_layers(
            release_version="1.5.2",
            configuration_schema={**schema, "tenant_id": schema["region"]},
            environment_config=environment,
            entity_overrides=_mapping(_INSTALLATION / "entities/core.yaml")["overrides"],
            sealed_keys=sealed,
        )
    assert error.value.code == "sealed_configuration_key"


def test_customer_template_allows_only_secret_references_before_signing() -> None:
    candidate = {
        "installation": _mapping(_INSTALLATION / "installation.yaml"),
        "environment": _mapping(_INSTALLATION / "environment.yaml"),
        "sealed_input": _mapping(_INSTALLATION / "sealed.yaml"),
        "entities": {"core": _mapping(_INSTALLATION / "entities/core.yaml")},
    }
    validate_configuration_package_for_signing(candidate)
    candidate["environment"]["api_key"] = "example-literal-value"
    with pytest.raises(ConfigurationValidationError) as error:
        validate_configuration_package_for_signing(candidate)
    assert error.value.code == "literal_secret_value"


def test_customer_key_runbook_keeps_unimplemented_publication_explicit() -> None:
    assert (_TEMPLATE / "README.md").is_file()
    for suffix in ("", "-ko"):
        runbook = _ROOT / f"docs/runbooks/lifecycle-configuration-key-onboarding{suffix}.md"
        assert runbook.is_file()
        assert "tests/integration/test_lifecycle_configuration_template.py" in runbook.read_text()
