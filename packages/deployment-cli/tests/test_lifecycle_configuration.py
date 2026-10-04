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
            "x-fdai-axis": "Deployment environment",
            "x-fdai-owner": "customer",
        },
        "replicas": {
            "default": 1,
            "x-fdai-axis": "Release channel subscription",
            "x-fdai-owner": "customer",
        },
        "model_capacity": {
            "default": {"kind": "paygo"},
            "x-fdai-axis": "Model diversity policy",
            "x-fdai-owner": "customer",
        },
    }


def test_release_configuration_schema_rejects_unannotated_key() -> None:
    schema = _schema()
    schema["replicas"] = {"default": 1, "x-fdai-axis": "Deployment environment"}

    with pytest.raises(ConfigurationValidationError) as exc_info:
        validate_release_configuration_schema(schema)

    assert exc_info.value.code == "unannotated_configuration_key"
    assert exc_info.value.path == ("replicas",)


@pytest.mark.parametrize(
    "axis",
    [
        "Action lifecycle",
        "Approval profile",
        "Authorization policy",
        "ApprovalProfile",
        "promotion-kind",
        "Promotion kind",
        "executor-identity",
        "human-identity",
        "kill-switch",
        "unknown configuration axis",
    ],
)
def test_release_configuration_schema_rejects_non_configuration_axes(axis: str) -> None:
    schema = _schema()
    schema["approval_profile"] = {
        "default": "single-operator-production",
        "x-fdai-axis": axis,
        "x-fdai-owner": "installation-governance",
    }

    with pytest.raises(ConfigurationValidationError) as exc_info:
        validate_release_configuration_schema(schema)

    assert exc_info.value.code == "unsupported_configuration_axis"
    assert exc_info.value.path == ("approval_profile",)


@pytest.mark.parametrize(
    "axis",
    [
        "Deployment environment",
        "deploymentEnvironment",
        "product_surface_profile",
        "release-channel-subscription",
        "Model diversity policy",
        "optional package preference",
    ],
)
def test_release_configuration_schema_accepts_known_non_authority_axes(axis: str) -> None:
    schema = _schema()
    schema["region"]["x-fdai-axis"] = axis

    validate_release_configuration_schema(schema)


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


def test_layer_resolution_rejects_duplicate_identical_override_ranges() -> None:
    with pytest.raises(ConfigurationValidationError) as exc_info:
        resolve_configuration_layers(
            release_version="1.5.2",
            configuration_schema=_schema(),
            environment_config={"region": "koreacentral"},
            entity_overrides=[
                {"versions": ">=1.5.0 <2.0.0", "values": {"replicas": 2}},
                {"versions": ">=1.5.0 <2.0.0", "values": {"replicas": 4}},
            ],
        )

    assert exc_info.value.code == "duplicate_override_range"
    assert exc_info.value.path == ("entity_overrides", "1", "versions")


def test_layer_resolution_validates_nonmatching_override_blocks() -> None:
    with pytest.raises(ConfigurationValidationError) as exc_info:
        resolve_configuration_layers(
            release_version="1.5.2",
            configuration_schema=_schema(),
            environment_config={"region": "koreacentral"},
            sealed_keys={"model_capacity"},
            entity_overrides=[
                {"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}},
                {
                    "versions": ">=2.0.0 <3.0.0",
                    "values": {"model_capacity": {"kind": "ptu"}},
                },
            ],
        )

    assert exc_info.value.code == "sealed_configuration_key"
    assert exc_info.value.path == ("entity_overrides", "1", "values", "model_capacity")


@pytest.mark.parametrize(
    ("package", "path"),
    [
        ({"client_secret": {"value": "hunter2"}}, ("client_secret",)),
        ({"password": ["hunter2"]}, ("password",)),
        ({"password": 123456}, ("password",)),
        ({"credentials": "hunter2"}, ("credentials",)),
        ({"clientSecret": "hunter2"}, ("clientSecret",)),
        ({"accessToken": "hunter2"}, ("accessToken",)),
        ({"db_passwd": "hunter2"}, ("db_passwd",)),
        ({"connection_string": "Server=x;Password=hunter2"}, ("connection_string",)),
        ({"env": [{"name": "DB_PASSWORD", "value": "hunter2"}]}, ("env", "0", "value")),
        ({"password": {"key_vault_secret": "hunter2"}}, ("password",)),
        ({"tokens": ("hunter2",)}, ("tokens",)),
        ({"APIKey": "hunter2"}, ("APIKey",)),
        ({"APIToken": "hunter2"}, ("APIToken",)),
        ({"DBPassword": "hunter2"}, ("DBPassword",)),
        ({"JWTSecret": "hunter2"}, ("JWTSecret",)),
        ({"apikey": "hunter2"}, ("apikey",)),
        ({"dbpassword": "hunter2"}, ("dbpassword",)),
        ({"clientsecret": "hunter2"}, ("clientsecret",)),
        ({"accesstoken": "hunter2"}, ("accesstoken",)),
        ({"connectionstring": "Server=x"}, ("connectionstring",)),
        ({"account_key": "hunter2"}, ("account_key",)),
        ({"storageAccountKey": "hunter2"}, ("storageAccountKey",)),
        ({"primary_key": "hunter2"}, ("primary_key",)),
        ({"subscription_key": "hunter2"}, ("subscription_key",)),
        ({"sas": "hunter2"}, ("sas",)),
        ({"passphrase": "hunter2"}, ("passphrase",)),
        ({"env": [{"key": "DB_PASSWORD", "value": "hunter2"}]}, ("env", "0", "value")),
        ({"env": [{"Name": "DB_PASSWORD", "Value": "hunter2"}]}, ("env", "0", "Value")),
        ({"privatekey": "hunter2"}, ("privatekey",)),
        ({"encryption_key": "hunter2"}, ("encryption_key",)),
        ({"masterKey": "hunter2"}, ("masterKey",)),
        ({"authorization": "hunter2"}, ("authorization",)),
        ({"pass_word": "hunter2"}, ("pass_word",)),
        ({"access_token": 123}, ("access_token",)),
        (
            {"env": [{"name": "SAFE_VALUE", "key": "DB_PASSWORD", "value": "hunter2"}]},
            ("env", "0", "value"),
        ),
        (
            {
                "env": [
                    {
                        "key": "DB_PASSWORD",
                        "value": "kv://secret-vault/db-password",
                        "Value": "hunter2",
                    }
                ]
            },
            ("env", "0", "Value"),
        ),
        ({"password_id": "hunter2"}, ("password_id",)),
        ({"client_secret_url": "hunter2"}, ("client_secret_url",)),
        ({"api_key_version": "hunter2"}, ("api_key_version",)),
        ({"client_secret_name": "hunter2"}, ("client_secret_name",)),
        ({"password_type": "hunter2"}, ("password_type",)),
        ({"secret_kind": "hunter2"}, ("secret_kind",)),
        (
            {"sasUrl": "https://acct.blob.core.windows.net/c?sv=1&sig=hunter2"},
            ("sasUrl",),
        ),
        (
            {"sas_uri": "https://acct.blob.core.windows.net/c?sv=1&sig=hunter2"},
            ("sas_uri",),
        ),
        (
            {"storage_sas_url": "https://acct.blob.core.windows.net/c?sv=1&sig=hunter2"},
            ("storage_sas_url",),
        ),
        ({"token_url": "https://u:hunter2@x.example/"}, ("token_url",)),
        (
            {"env": [{"name": "CLIENT_SECRET_ID", "value": "hunter2"}]},
            ("env", "0", "value"),
        ),
        (
            {
                "env": [
                    {
                        "name": "SAS_URL",
                        "value": "https://acct.blob.core.windows.net/c?sv=1&sig=hunter2",
                    }
                ]
            },
            ("env", "0", "value"),
        ),
        ({"client_secret_id": "/subscriptions/x/rg?sig=abc"}, ("client_secret_id",)),
        ({"client_secret_id": "/subscriptions/x/hunter2"}, ("client_secret_id",)),
        (
            {"api_key_id": "/subscriptions/a/Server=x;AccountKey=abc=="},
            ("api_key_id",),
        ),
        (
            {"client_secret_id": "https://myvault.vault.azure.net/secrets/name/hunter2"},
            ("client_secret_id",),
        ),
        ({"password_column": "hunter2"}, ("password_column",)),
        ({"secret_column": "hunter2"}, ("secret_column",)),
        ({"token_type": "ghp_123456789012345678901234567890123456"}, ("token_type",)),
        ({"credential_kind": "hunter2"}, ("credential_kind",)),
        ({"dbpassword_type": "hunter2"}, ("dbpassword_type",)),
        ({"dbpassword_type": "Summer2024Pass"}, ("dbpassword_type",)),
        ({"clientsecret_kind": "hunter2"}, ("clientsecret_kind",)),
        ({"apikey_type": "hunter2"}, ("apikey_type",)),
        ({"accesstoken_version": "hunter2"}, ("accesstoken_version",)),
        ({"authorization_type": "hunter2"}, ("authorization_type",)),
        ({"privatekey_kind": "hunter2"}, ("privatekey_kind",)),
        ({"connectionstring_type": "hunter2"}, ("connectionstring_type",)),
        ({"dbpassword_name": "hunter2"}, ("dbpassword_name",)),
        ({"clientsecret_name": "hunter2"}, ("clientsecret_name",)),
        ({"apikey_name": "hunter2"}, ("apikey_name",)),
        ({"credential_column": "hunter2"}, ("credential_column",)),
        ({"api_key_column": "id"}, ("api_key_column",)),
        ({"access_tokens_column": "id"}, ("access_tokens_column",)),
        ({"authorization_column": "id"}, ("authorization_column",)),
        ({"primary_key_column": "id"}, ("primary_key_column",)),
        ({"account_key_name": "hunter2"}, ("account_key_name",)),
        (
            {"subscription_key_name": "0123456789abcdef0123456789abcdef"},
            ("subscription_key_name",),
        ),
        ({"storage_sas_type": "hunter2"}, ("storage_sas_type",)),
        ({"db_pwd_column": "hunter2"}, ("db_pwd_column",)),
        (
            {"primary_key_id": "00000000-0000-0000-0000-000000000000"},
            ("primary_key_id",),
        ),
        ({"http_authorization_type": "hunter2"}, ("http_authorization_type",)),
        (
            {"env": [{"name": "ACCOUNT_KEY_NAME", "value": "hunter2"}]},
            ("env", "0", "value"),
        ),
    ],
)
def test_package_rejects_literal_secret_values_before_signing(
    package: dict[str, object], path: tuple[str, ...]
) -> None:
    with pytest.raises(ConfigurationValidationError) as exc_info:
        validate_configuration_package_for_signing(package)

    assert exc_info.value.code == "literal_secret_value"
    assert exc_info.value.path == path


@pytest.mark.parametrize(
    "key",
    [
        "pass\u200bword",
        "\u0440\u0430ssword",
        "\uff50\uff41\uff53\uff53\uff57\uff4f\uff52\uff44",
    ],
)
def test_package_rejects_non_ascii_configuration_keys(key: str) -> None:
    with pytest.raises(ConfigurationValidationError) as exc_info:
        validate_configuration_package_for_signing({key: "hunter2"})

    assert exc_info.value.code == "invalid_configuration_key"
    assert exc_info.value.path == (key,)


def test_package_allows_design_environment_secret_reference_names() -> None:
    validate_configuration_package_for_signing(
        {
            "environment_config": {
                "region": "koreacentral",
                "data_residency": {"processing_scope": "geography"},
                "network": {"profile": "private-endpoints-only"},
                "model_bindings": {
                    "primary": {
                        "provider": "azure-openai",
                        "deployment_type": "ProvisionedManaged",
                        "capacity": {"kind": "ptu", "units": 100},
                        "endpoint_ref": "model-primary",
                    }
                },
                "integrations": {
                    "itsm": {
                        "endpoint_ref": "itsm-primary",
                        "credential_ref": "itsm-token",
                    }
                },
            },
            "entity_overrides": [],
        }
    )


def test_package_allows_reference_metadata_and_numeric_token_counters() -> None:
    validate_configuration_package_for_signing(
        {
            "max_tokens": 4096,
            "tokens_per_minute": 100,
            "passwordless": True,
            "secret_name": "itsm-token",
            "key_vault_secret_name": "itsm-token",
            "token_endpoint": "https://x.example",
            "login_token_endpoint": "https://login.example.com/oauth2/token",
            "credential_kind": "managed-identity",
            "token_type": "Bearer",
            "api_version": "2024-01-01",
            "api_key_version": "2024-01-01",
            "resource_id": (
                "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg"
                "/providers/FDAI/type/name"
            ),
            "secret_id": "https://vault-name.vault.azure.net/secrets/itsm-token/"
            "00000000000000000000000000000000",
        }
    )


def test_package_allows_key_vault_secret_references_before_signing() -> None:
    validate_configuration_package_for_signing(
        {
            "environment_config": {
                "integrations": {
                    "itsm": {
                        "credential_ref": "kv://integration-vault/itsm-token",
                    }
                }
            },
            "entity_overrides": [
                {
                    "versions": ">=1.5.0 <2.0.0",
                    "values": {"api_key_ref": {"key_vault_secret": "model-vault/example-token"}},
                }
            ],
        }
    )
