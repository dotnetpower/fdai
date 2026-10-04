from __future__ import annotations

import pytest

from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    resolve_configuration_layers,
    validate_configuration_package_for_signing,
    validate_release_configuration_schema,
)


def _schema() -> dict[str, object]:
    return {
        "region": {
            "default": "eastus",
            "x-fdai-axis": "environment",
            "x-fdai-owner": "customer",
        },
        "replicas": {
            "default": 1,
            "x-fdai-axis": "lifecycle",
            "x-fdai-owner": "customer",
        },
        "model_capacity": {
            "default": {"kind": "paygo"},
            "x-fdai-axis": "environment",
            "x-fdai-owner": "customer",
        },
    }


def test_release_configuration_schema_rejects_unannotated_key() -> None:
    schema = _schema()
    schema["replicas"] = {"default": 1, "x-fdai-axis": "lifecycle"}

    with pytest.raises(ConfigurationValidationError) as exc_info:
        validate_release_configuration_schema(schema)

    assert exc_info.value.code == "unannotated_configuration_key"
    assert exc_info.value.path == ("replicas",)


def test_release_configuration_schema_rejects_authority_axis_key() -> None:
    schema = _schema()
    schema["approval_profile"] = {
        "default": "single-operator-production",
        "x-fdai-axis": "approval-profile",
        "x-fdai-owner": "installation-governance",
    }

    with pytest.raises(ConfigurationValidationError) as exc_info:
        validate_release_configuration_schema(schema)

    assert exc_info.value.code == "authority_axis_configuration_key"
    assert exc_info.value.path == ("approval_profile",)


def test_layer_resolution_uses_most_specific_matching_version_range() -> None:
    result = resolve_configuration_layers(
        release_version="1.5.2",
        configuration_schema=_schema(),
        environment_config={"region": "koreacentral", "model_capacity": {"kind": "ptu"}},
        entity_overrides=[
            {"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}},
            {"versions": ">=1.5.0 <1.6.0", "values": {"replicas": 4}},
        ],
    )

    assert result.version_range == ">=1.5.0 <1.6.0"
    assert result.values == {
        "region": "koreacentral",
        "replicas": 4,
        "model_capacity": {"kind": "ptu"},
    }


def test_layer_resolution_requires_matching_override_block() -> None:
    with pytest.raises(ConfigurationValidationError) as exc_info:
        resolve_configuration_layers(
            release_version="2.0.0",
            configuration_schema=_schema(),
            environment_config={"region": "koreacentral"},
            entity_overrides=[
                {"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}},
            ],
        )

    assert exc_info.value.code == "missing_matching_override_block"
    assert exc_info.value.path == ("entity_overrides",)


def test_package_rejects_literal_secret_values_before_signing() -> None:
    package = {
        "environment_config": {
            "integrations": {
                "itsm": {
                    "credential_ref": "literal-secret-value",
                }
            }
        },
        "entity_overrides": [],
    }

    with pytest.raises(ConfigurationValidationError) as exc_info:
        validate_configuration_package_for_signing(package)

    assert exc_info.value.code == "literal_secret_value"
    assert exc_info.value.path == ("environment_config", "integrations", "itsm", "credential_ref")


def test_package_allows_key_vault_secret_references_before_signing() -> None:
    validate_configuration_package_for_signing(
        {
            "environment_config": {
                "integrations": {
                    "itsm": {
                        "credential_ref": "kv://integration-secrets/itsm-token",
                    }
                }
            },
            "entity_overrides": [
                {
                    "versions": ">=1.5.0 <2.0.0",
                    "values": {"api_key_ref": {"key_vault_secret": "example-token"}},
                }
            ],
        }
    )
