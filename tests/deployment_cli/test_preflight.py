"""CLI adapter tests for deterministic deployment preflight."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from fdai.deployment_cli.cli import main
from fdai.deployment_cli.preflight import (
    PreflightInputError,
    load_terraform_plan_resource_types,
    run_azure_live_preflight,
    run_static_preflight,
)
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

_GENERATED_AT = "2026-07-17T00:00:00Z"
_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"


class _StaticIdentity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",  # noqa: S106 - deterministic fake
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _write_input(path: Path, *, mode: str = "shadow", blocked: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.preflight-input.v1",
                "scope": "resource-group-equivalent:example",
                "mode": mode,
                "generated_at": _GENERATED_AT,
                "resource_types": ["compute.disk", "compute.vm"],
                "egress_hosts": ["packages.example.com"],
                "policy": {
                    "denied_resource_types": ["compute.disk"] if blocked else [],
                    "blocked_egress_hosts": ["packages.example.com"] if blocked else [],
                    "policy_source": "policy:approved-resource-types",
                    "firewall_source": "network-policy:approved-egress",
                },
            }
        ),
        encoding="utf-8",
    )


async def test_shadow_blockers_require_review_and_are_byte_stable(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    _write_input(path)

    first = await run_static_preflight(path)
    second = await run_static_preflight(path)

    assert first.exit_code == 2
    assert first.report.verdict.value == "blocked"
    assert first.report.blocks_deploy is False
    assert first.to_json() == second.to_json()


async def test_enforced_blocker_uses_exit_code_three(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    _write_input(path, mode="enforce")

    result = await run_static_preflight(path)

    assert result.exit_code == 3
    assert result.report.blocks_deploy is True


async def test_clear_input_uses_exit_code_zero(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    _write_input(path, blocked=False)

    result = await run_static_preflight(path)

    assert result.exit_code == 0
    assert result.report.findings == ()


async def test_invalid_input_is_incomplete_not_clear(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(PreflightInputError, match="invalid"):
        await run_static_preflight(path)


def test_cli_preflight_emits_stable_json_and_review_exit(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    _write_input(path)
    stdout = io.StringIO()

    exit_code = main(
        ["deploy", "preflight", "--input", str(path), "--output", "json"],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 2
    assert payload["schema_version"] == "fdai.deployment-cli.preflight.v1"
    assert payload["report"]["verdict"] == "blocked"


def test_plan_conversion_selects_only_created_managed_resources(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "terraform_version": "1.12.0",
                "resource_changes": [
                    {
                        "address": "azurerm_managed_disk.example",
                        "mode": "managed",
                        "type": "azurerm_managed_disk",
                        "change": {"actions": ["create"], "after": {"name": "ignored"}},
                    },
                    {
                        "mode": "managed",
                        "type": "azurerm_linux_virtual_machine",
                        "change": {"actions": ["delete", "create"]},
                    },
                    {
                        "mode": "managed",
                        "type": "azurerm_resource_group",
                        "change": {"actions": ["no-op"]},
                    },
                    {
                        "mode": "data",
                        "type": "azurerm_client_config",
                        "change": {"actions": ["read"]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    resource_types = load_terraform_plan_resource_types(
        path,
        resource_type_map={
            "azurerm_managed_disk": "compute.disk",
            "azurerm_linux_virtual_machine": "compute.vm",
        },
    )

    assert resource_types == ("compute.disk", "compute.vm")


def test_plan_conversion_fails_closed_on_unmapped_created_type(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "resource_changes": [
                    {
                        "mode": "managed",
                        "type": "azurerm_unknown",
                        "change": {"actions": ["create"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PreflightInputError, match="mapping is missing"):
        load_terraform_plan_resource_types(path, resource_type_map={})


def test_plan_conversion_ignores_builtin_terraform_metadata(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "resource_changes": [
                    {
                        "mode": "managed",
                        "type": "terraform_data",
                        "change": {"actions": ["create"]},
                    },
                    {
                        "mode": "managed",
                        "type": "azurerm_managed_disk",
                        "change": {"actions": ["create"]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    resource_types = load_terraform_plan_resource_types(
        path,
        resource_type_map={"azurerm_managed_disk": "compute.disk"},
    )

    assert resource_types == ("compute.disk",)


def test_cli_plan_preflight_merges_plan_types_without_exposing_addresses(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.json"
    _write_input(input_path, blocked=False)
    request = json.loads(input_path.read_text(encoding="utf-8"))
    request["terraform_resource_type_map"] = {
        "azurerm_managed_disk": "compute.disk",
    }
    request["policy"]["denied_resource_types"] = ["compute.disk"]
    input_path.write_text(json.dumps(request), encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "resource_changes": [
                    {
                        "address": "module.private.azurerm_managed_disk.sensitive_name",
                        "mode": "managed",
                        "type": "azurerm_managed_disk",
                        "change": {"actions": ["create"], "after": {"name": "sensitive"}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()

    exit_code = main(
        [
            "deploy",
            "preflight",
            "--input",
            str(input_path),
            "--terraform-plan",
            str(plan_path),
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    assert exit_code == 2
    assert "sensitive" not in stdout.getvalue()
    assert json.loads(stdout.getvalue())["report"]["verdict"] == "blocked"


async def test_live_preflight_composes_policy_and_quota_without_exposing_target(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.json"
    _write_input(input_path, blocked=False)
    request = json.loads(input_path.read_text(encoding="utf-8"))
    request["resource_types"] = ["compute.disk"]
    request["azure_live"] = {
        "required_categories": [
            "policy_guardrail",
            "quota_capacity",
            "identity_rbac",
            "secret_config",
        ],
        "resource_group": "example-group",
        "arm_resource_type_map": {"compute.disk": "Microsoft.Compute/disks"},
        "quota_checks": [{"quota_name": "cores", "required": 2}],
        "identity_rbac": {
            "executor_principal_id": "executor-principal",
            "event_role_definition_id": "event-role",
            "secret_role_definition_id": "secret-role",
        },
        "key_vault": {
            "vault_endpoint": "https://example.vault.azure.net",
            "required_secret_names": ["required-secret"],
        },
    }
    input_path.write_text(json.dumps(request), encoding="utf-8")
    environment_path = tmp_path / "environment.json"
    environment_path.write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.environment.v1",
                "environment": "dev",
                "azure": {
                    "subscription_id": _SUBSCRIPTION_ID,
                    "tenant_id": "00000000-0000-0000-0000-000000000002",
                    "region": "koreacentral",
                },
                "execution_target": "remote-runner",
                "autonomy_mode_default": "shadow",
            }
        ),
        encoding="utf-8",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.vault.azure.net":
            return httpx.Response(404)
        if "policyAssignments" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "properties": {
                                "policyDefinitionId": "/providers/Microsoft.Authorization/"
                                "policyDefinitions/deny-disks",
                                "parameters": {},
                            }
                        }
                    ]
                },
            )
        if "policyDefinitions/deny-disks" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "name": "deny-disks",
                    "properties": {
                        "policyRule": {
                            "if": {"field": "type", "in": ["Microsoft.Compute/disks"]},
                            "then": {"effect": "deny"},
                        }
                    },
                },
            )
        if request.url.path.endswith("/usages"):
            return httpx.Response(
                200,
                json={"value": [{"name": {"value": "cores"}, "currentValue": 9, "limit": 10}]},
            )
        if "Microsoft.ResourceGraph/resources" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "roleDefinitionId": "/providers/Microsoft.Authorization/"
                            "roleDefinitions/event-role",
                            "scope": "/subscriptions/example/resourceGroups/example-group/"
                            "providers/Microsoft.EventHub/namespaces/example",
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await run_azure_live_preflight(
            input_path,
            environment_path,
            identity=_StaticIdentity(),
            http_client=client,
        )

    payload = result.to_json()
    assert result.exit_code == 2
    assert [finding.category.value for finding in result.report.findings] == [
        "identity_rbac",
        "secret_config",
        "policy_guardrail",
        "quota_capacity",
    ]
    assert [check["category"] for check in json.loads(payload)["report"]["checks"]] == [
        "identity_rbac",
        "policy_guardrail",
        "quota_capacity",
        "secret_config",
        "supply_chain_egress",
    ]
    assert _SUBSCRIPTION_ID not in payload
    assert "example-group" not in payload
    assert "executor-principal" not in payload
    assert "secret-role" not in payload
    assert "required-secret" not in payload
    assert "example.vault.azure.net" not in payload


async def test_live_preflight_sanitizes_probe_failure(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    _write_input(input_path, blocked=False)
    request = json.loads(input_path.read_text(encoding="utf-8"))
    request["resource_types"] = ["compute.disk"]
    request["azure_live"] = {"arm_resource_type_map": {"compute.disk": "Microsoft.Compute/disks"}}
    input_path.write_text(json.dumps(request), encoding="utf-8")
    environment_path = tmp_path / "environment.json"
    environment_path.write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.environment.v1",
                "environment": "dev",
                "azure": {
                    "subscription_id": _SUBSCRIPTION_ID,
                    "tenant_id": "00000000-0000-0000-0000-000000000002",
                    "region": "koreacentral",
                },
                "execution_target": "remote-runner",
                "autonomy_mode_default": "shadow",
            }
        ),
        encoding="utf-8",
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(503, text="blocked"))
    ) as client:
        with pytest.raises(PreflightInputError) as error:
            await run_azure_live_preflight(
                input_path,
                environment_path,
                identity=_StaticIdentity(),
                http_client=client,
            )

    assert _SUBSCRIPTION_ID not in str(error.value)
    assert "management.azure.com" not in str(error.value)


def test_cli_live_preflight_requires_live_input_before_network(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    _write_input(input_path, blocked=False)
    stdout = io.StringIO()

    exit_code = main(
        [
            "deploy",
            "preflight",
            "--input",
            str(input_path),
            "--environment-config",
            str(tmp_path / "missing-environment.json"),
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    assert exit_code == 4
    assert "missing azure_live configuration" in stdout.getvalue()


async def test_live_preflight_requires_declared_category_configuration(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.json"
    _write_input(input_path, blocked=False)
    request = json.loads(input_path.read_text(encoding="utf-8"))
    request["azure_live"] = {
        "required_categories": ["quota_capacity", "identity_rbac", "secret_config"]
    }
    input_path.write_text(json.dumps(request), encoding="utf-8")
    environment_path = tmp_path / "environment.json"
    environment_path.write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.environment.v1",
                "environment": "dev",
                "azure": {
                    "subscription_id": _SUBSCRIPTION_ID,
                    "tenant_id": "00000000-0000-0000-0000-000000000002",
                    "region": "koreacentral",
                },
                "execution_target": "remote-runner",
                "autonomy_mode_default": "shadow",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PreflightInputError, match="identity_rbac, quota_capacity, secret_config"):
        await run_azure_live_preflight(
            input_path,
            environment_path,
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _request: pytest.fail("network must not be called")
                )
            ),
        )
