"""One-command Genesis repository-configuration regressions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_repository_config as repository_config  # noqa: E402

SOURCE = "a" * 40


def _handoff() -> dict[str, Any]:
    return {
        "terraform_root": "infra/genesis-foundation",
        "source_commit": SOURCE,
        "run_digest": "b" * 64,
        "subscription_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "region": "koreacentral",
        "app_resource_group": {
            "id": "/subscriptions/example/resourceGroups/example",
            "name": "rg-example",
            "foundation_context_digest": "c" * 64,
        },
        "ops": {
            "resource_group_name": "rg-ops-example",
            "vnet_id": (
                "/subscriptions/example/resourceGroups/example/providers/"
                "Microsoft.Network/virtualNetworks/example"
            ),
            "vnet_name": "vnet-example",
        },
        "state": {
            "account_name": "stateexample",
            "container_name": "tfstate",
        },
        "runner": {
            "client_id": "00000000-0000-0000-0000-000000000003",
            "principal_id": "00000000-0000-0000-0000-000000000004",
        },
        "access": {"method": "bastion"},
    }


def _template() -> dict[str, Any]:
    return {
        "schema_version": "fdai.deployment.preflight-input.v1",
        "scope": "resource-group-equivalent:deployment",
        "mode": "enforce",
        "resource_types": [],
        "egress_hosts": [],
        "terraform_resource_type_map": {},
        "required_links": [],
        "policy": {"denied_resource_types": [], "blocked_egress_hosts": []},
        "azure_live": {
            "required_categories": [
                "policy_guardrail",
                "quota_capacity",
                "identity_rbac",
                "secret_config",
            ],
            "resource_group": "resolved-by-genesis",
            "arm_resource_type_map": {},
            "quota_checks": [{"quota_name": "cores", "required": 1}],
            "identity_rbac": {
                "allow_planned_creation": True,
                "required_role_names": ["Azure Event Hubs Data Owner"],
            },
            "key_vault": {
                "allow_planned_creation": True,
                "required_secret_names": ["fdai-state-store-dsn"],
            },
        },
    }


def _plan() -> repository_config.RepositoryConfigPlan:
    image_refs = {
        image: f"ghcr.io/example/fdai/{image}@sha256:{digest * 64}"
        for image, digest in (
            ("fdai-core-control-plane", "1"),
            ("fdai-operator-service", "2"),
            ("fdai-document-ingestion-api", "3"),
        )
    }
    entra_bindings = {
        "ENTRA_CONSOLE_API_SCOPE": "api://example/access",
        "ENTRA_CONSOLE_SPA_CLIENT_ID": "spa-example",
        "OPERATOR_API_AUDIENCE": "api://example",
        "RBAC_APPROVERS_GROUP_ID": "approvers",
        "RBAC_BREAK_GLASS_GROUP_ID": "break-glass",
        "RBAC_CONTRIBUTORS_GROUP_ID": "contributors",
        "RBAC_OWNERS_GROUP_ID": "owners",
        "RBAC_READERS_GROUP_ID": "readers",
    }
    return repository_config.create_repository_config_plan(
        repository="example/fdai",
        source_commit=SOURCE,
        handoff=_handoff(),
        foundation_variables={"region_short": "krc"},
        preflight_template=_template(),
        image_refs=image_refs,
        entra_bindings=entra_bindings,
    )


def test_repository_plan_binds_foundation_and_exact_source_images() -> None:
    plan = _plan()

    assert plan.variables["ARM_SUBSCRIPTION_ID"].endswith("0001")
    assert plan.variables["FOUNDATION_RESOURCE_GROUP_CONTEXT_DIGEST"] == "c" * 64
    assert plan.variables["CORE_IMAGE"].endswith("@sha256:" + "1" * 64)
    preflight = json.loads(plan.variables["DEPLOY_PREFLIGHT_INPUT_JSON"])
    assert preflight["azure_live"]["resource_group"] == "rg-example"
    assert preflight["azure_live"]["identity_rbac"]["allow_planned_creation"] is True
    assert len(plan.digest) == 64


def test_repository_apply_changes_only_drift_and_verifies_names(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_path.chmod(0o700)
    plan = _plan()
    existing = {}
    final = {**existing, **plan.variables}
    variable_reads = iter((existing, final, final))
    secret_reads = iter(((), plan.required_secrets))
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(repository_config, "_variable_map", lambda _repo: next(variable_reads))
    monkeypatch.setattr(repository_config, "_secret_names", lambda _repo: next(secret_reads))
    monkeypatch.setattr(repository_config, "_verify_entra_bindings", lambda *_: None)

    def fake_gh(arguments: tuple[str, ...], *, input_text: str | None = None) -> str:
        commands.append(arguments)
        if arguments[:2] == ("secret", "set"):
            assert input_text
        return ""

    monkeypatch.setattr(repository_config, "_gh", fake_gh)
    receipt = repository_config.apply_repository_config(
        repository="example/fdai",
        plan=plan,
        actor_digest="d" * 64,
        receipt_path=tmp_path / "receipt.json",
    )

    changed_variables = [call[2] for call in commands if call[:2] == ("variable", "set")]
    assert changed_variables == sorted(plan.variables)
    assert receipt["readback_verified"] is True
    assert receipt["created_secrets"] == list(plan.required_secrets)
    assert (tmp_path / "receipt.json").stat().st_mode & 0o777 == 0o600


def test_repository_plan_never_embeds_secret_values() -> None:
    serialized = json.dumps(_plan().variables, sort_keys=True)

    assert "POSTGRES_ADMIN_PASSWORD" not in serialized
    assert "POSTGRES_ADMIN_LOGIN" not in serialized
    assert "private_key" not in serialized.casefold()
