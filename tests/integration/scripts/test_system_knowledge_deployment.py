from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
PREPARE = ROOT / "scripts/deployment/system_knowledge/prepare_deployment.py"
GUARD = ROOT / "scripts/deployment/system_knowledge/guard_plan.py"
MATERIALIZE = ROOT / "scripts/deployment/azure/materialize_system_knowledge_secret.py"
IMAGE = "ghcr.io/example/fdai-system-knowledge-service@sha256:" + ("a" * 64)
PREFIX = "module.system_knowledge_service[0]."


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _profile() -> str:
    return json.dumps(
        {
            "service_name": "fdai-knowledge-dev",
            "bot_name": "fdai-knowledge-bot-dev",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "team_ids": ["team-example"],
            "channel_ids": ["channel-example"],
            "allowed_service_urls": ["https://smba.trafficmanager.net/example"],
            "jwks_url": "https://login.example.com/keys",
        }
    )


def _outgoing_profile() -> str:
    return json.dumps(
        {
            "transport": "outgoing_webhook",
            "service_name": "fdai-knowledge-dev",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "team_ids": ["team-example"],
            "channel_ids": ["channel-example"],
        }
    )


def _platform_outputs() -> dict[str, object]:
    def value(item: str) -> dict[str, str]:
        return {"value": item}

    return {
        "resource_group_name": value("rg-example"),
        "container_app_environment_id": value(
            "/subscriptions/00000000-0000-0000-0000-000000000001/"
            "resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/example"
        ),
        "container_registry_name": value("crexample"),
        "container_registry_login_server": value("crexample.azurecr.io"),
        "key_vault_uri": value("https://kv-example.vault.azure.net/"),
        "document_storage_account_name": value("stexample"),
    }


def _after(value: dict[str, object], address: str) -> dict[str, object]:
    return {"address": address, "change": {"actions": ["create"], "after": value}}


def _plan() -> dict[str, object]:
    environment = [
        {"name": name, "value": "value"}
        for name in sorted(
            {
                "FDAI_EXECUTION_VENUE",
                "FDAI_SYSTEM_KNOWLEDGE_CLAIM_CONTAINER_URL",
                "FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID",
                "FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID",
                "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT",
                "RUNTIME_ENV",
            }
        )
    ]
    resources = [
        _after({}, PREFIX + "azurerm_user_assigned_identity.service"),
        _after(
            {"container_access_type": "private"},
            PREFIX + "azurerm_storage_container.claims",
        ),
        *[
            _after(
                {"role_definition_name": role},
                PREFIX + f"azurerm_role_assignment.{name}",
            )
            for name, role in (
                ("acr_pull", "AcrPull"),
                ("claim_writer", "Storage Blob Data Contributor"),
                ("principal_map_reader", "Key Vault Secrets User"),
            )
        ],
        _after(
            {
                "name": "fdai-knowledge-dev",
                "identity": [{"identity_ids": ["identity-id"]}],
                "template": [
                    {
                        "min_replicas": 1,
                        "max_replicas": 1,
                        "container": [
                            {
                                "name": "system-knowledge-service",
                                "image": IMAGE,
                                "env": environment,
                            }
                        ],
                    }
                ],
            },
            PREFIX + "module.container_app.azurerm_container_app.service",
        ),
        _after(
            {
                "microsoft_app_type": "UserAssignedMSI",
                "microsoft_app_id": "00000000-0000-0000-0000-000000000003",
                "microsoft_app_msi_id": "/subscriptions/example/identities/knowledge",
                "sku": "F0",
                "local_authentication_enabled": False,
                "public_network_access_enabled": True,
                "endpoint": "https://example.com/api/teams/messages",
            },
            PREFIX + "azurerm_bot_service_azure_bot.service",
        ),
        _after({}, PREFIX + "azurerm_bot_channel_ms_teams.service"),
        _after(
            {
                "input": {
                    "execution_authority": False,
                    "replica_ceiling": 1,
                    "teams_transport": "bot_framework",
                }
            },
            PREFIX + "terraform_data.authority_contract",
        ),
    ]
    return {"resource_changes": resources}


def test_prepare_inputs_binds_platform_profile_and_secret_digests() -> None:
    prepare = _module(PREPARE, "prepare_system_knowledge")
    tfvars, context = prepare.build_inputs(
        platform_outputs=_platform_outputs(),
        teams_profile_json=_profile(),
        principal_map_json='{"aad-example":"principal-example"}',
        subscription_id="00000000-0000-0000-0000-000000000001",
        region="koreacentral",
        environment="dev",
        image_ref=IMAGE,
        previous_image_ref=IMAGE,
        source_revision="b" * 40,
        transition="enable",
    )

    assert tfvars["enabled"] is True
    assert tfvars["scaling"]["max_replicas"] == 1
    assert tfvars["platform"]["claim_storage_blob_endpoint"] == (
        "https://stexample.blob.core.windows.net/"
    )
    assert context["context_digest"].startswith("sha256:")
    assert "team-example" not in json.dumps(context)


def test_prepare_inputs_supports_outgoing_bootstrap_and_hmac_enable() -> None:
    prepare = _module(PREPARE, "prepare_system_knowledge_outgoing")
    common = {
        "platform_outputs": _platform_outputs(),
        "teams_profile_json": _outgoing_profile(),
        "principal_map_json": '{"aad-example":"principal-example"}',
        "subscription_id": "00000000-0000-0000-0000-000000000001",
        "region": "koreacentral",
        "environment": "dev",
        "image_ref": IMAGE,
        "previous_image_ref": IMAGE,
        "source_revision": "b" * 40,
    }

    bootstrap, bootstrap_context = prepare.build_inputs(
        **common,
        transition="bootstrap",
    )
    enabled, enabled_context = prepare.build_inputs(
        **common,
        transition="enable",
        outgoing_hmac_secret=base64.b64encode(b"k" * 32).decode(),
    )

    assert bootstrap["enabled"] is True
    assert bootstrap["teams"]["transport"] == "outgoing_webhook"
    assert bootstrap["teams"]["outgoing_hmac_secret_id"] is None
    assert enabled["teams"]["outgoing_hmac_secret_id"].endswith(
        "/secrets/fdai-system-knowledge-outgoing-hmac"
    )
    assert bootstrap_context["outgoing_hmac_digest"] is None
    assert enabled_context["outgoing_hmac_digest"].startswith("sha256:")
    assert "a2tra" not in json.dumps(enabled)


def test_plan_guard_accepts_exact_boundary_and_rejects_executor_env() -> None:
    guard = _module(GUARD, "guard_system_knowledge")
    plan = _plan()
    guard.validate_plan(plan, transition="enable", image_ref=IMAGE)

    container = next(
        entry
        for entry in plan["resource_changes"]
        if entry["address"].endswith("azurerm_container_app.service")
    )
    container["change"]["after"]["template"][0]["container"][0]["env"].append(
        {"name": "FDAI_ISOLATED_EXECUTOR_DEPLOYED", "value": "1"}
    )
    with pytest.raises(guard.SystemKnowledgePlanError, match="read-only"):
        guard.validate_plan(plan, transition="enable", image_ref=IMAGE)


def test_plan_guard_accepts_outgoing_bootstrap_without_bot_resources() -> None:
    guard = _module(GUARD, "guard_system_knowledge_outgoing")
    plan = _plan()
    plan["resource_changes"] = [
        entry for entry in plan["resource_changes"] if "azurerm_bot_" not in entry["address"]
    ]
    container = next(
        entry
        for entry in plan["resource_changes"]
        if entry["address"].endswith("azurerm_container_app.service")
    )
    environment = container["change"]["after"]["template"][0]["container"][0]["env"]
    container["change"]["after"]["template"][0]["container"][0]["env"] = [
        item
        for item in environment
        if item["name"]
        not in {
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID",
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID",
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL",
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON",
        }
    ]
    authority = next(
        entry
        for entry in plan["resource_changes"]
        if entry["address"].endswith("terraform_data.authority_contract")
    )
    authority["change"]["after"]["input"]["teams_transport"] = "outgoing_webhook"

    guard.validate_plan(
        plan,
        transition="bootstrap",
        image_ref=IMAGE,
        transport="outgoing_webhook",
    )


def test_secret_materializer_validates_and_reads_back() -> None:
    materializer = _module(MATERIALIZE, "materialize_system_knowledge")
    principal_map = materializer.validate_principal_map('{"aad-example":"principal-example"}')
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "secret"})
        return httpx.Response(200, json={"value": principal_map})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        materializer.materialize(
            vault_uri="https://kv-example.vault.azure.net",
            principal_map=principal_map,
            access_token="header.payload.signature",
            transport=client,
        )

    assert calls == ["PUT", "GET"]


def test_secret_materializer_validates_outgoing_hmac_and_reads_back() -> None:
    materializer = _module(MATERIALIZE, "materialize_system_knowledge_outgoing")
    hmac_secret = materializer.validate_outgoing_hmac(base64.b64encode(b"k" * 32).decode())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "secret"})
        return httpx.Response(200, json={"value": hmac_secret})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        materializer.materialize_outgoing_hmac(
            vault_uri="https://kv-example.vault.azure.net",
            hmac_secret=hmac_secret,
            access_token="header.payload.signature",
            transport=client,
        )
