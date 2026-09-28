"""AKS workload composition follows the same explicit product profile as Terraform."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_host

_FULL_ADD_ONS = (
    "enterprise-identity-governance",
    "governed-execution",
    "notifications",
    "read-only-console",
)
_PROFILE_JSON = json.dumps(
    {
        "schema_version": "fdai.product-profile.v1",
        "name": "observation-first",
        "add_ons": [],
        "observation_permissions": {"base_role": "Reader", "selected_sources": []},
        "authority_granted": False,
    },
    sort_keys=True,
    separators=(",", ":"),
)


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, add_ons: tuple[str, ...]) -> dict:
    for name in ("runtime-receipt.json", "image-import-receipt.json", "migration-receipt.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    context = {
        "runtime_profile": {
            "runtime_platform": "aks",
            "database_placement": "postgres-flex",
            "product_profile": {
                "schema_version": "fdai.product-profile.v1",
                "name": "observation-first",
                "add_ons": list(add_ons),
                "observation_permissions": {"base_role": "Reader", "selected_sources": []},
                "authority_granted": False,
            },
        },
        "infra": str(tmp_path / "infra"),
        "runtime_infra": str(tmp_path / "runtime"),
        "tenant_id": "tenant",
        "subscription_id": "subscription",
        "source_commit": "a" * 40,
        "image_refs": {
            name: f"example.azurecr.io/{name}@sha256:{'b' * 64}"
            for name in (
                "core-control-plane",
                "operator-service",
                "isolated-executor",
                "document-ingestion-api",
                "document-processing-worker",
                "clamav",
            )
        },
    }
    application = {
        "enable_llm": True,
        "region": "westus2",
        "region_short": "wus2",
        "env": "dev",
        "workload": "fdai",
        "resource_name_suffix": "abc123",
        "product_profile_json": _PROFILE_JSON,
        "operator_api_audience": "api://operator",
        "rbac_readers_group_id": "readers",
        "rbac_contributors_group_id": "contributors",
        "rbac_approvers_group_id": "approvers",
        "rbac_owners_group_id": "owners",
        "rbac_break_glass_group_id": "break-glass",
        "stewardship_maintainers": "operator",
        "stewardship_agent_bindings": {"Odin": "user:operator"},
    }
    identities = {
        name: {"resource_id": f"/identities/{name}", "client_id": f"{name}-client"}
        for name in (
            "core",
            "operator",
            "command",
            "executor",
            "inventory",
            "canary",
            "ingestion",
            "ingestion_worker",
        )
    }
    captured: dict[str, object] = {}

    def private_json(path: Path, _label: str) -> dict[str, object]:
        return context if path.name == "context.json" else application

    def json_output(_infra: Path, name: str) -> object:
        return {
            "runtime_identity_bindings": identities,
            "event_bus_topics": ["events"],
            "event_bus_semantic_topics": ["requests", "projections", "investigations"],
            "llm_model_endpoints": {"model": "endpoint"},
            "document_storage_binding": {"account": "store"},
            "document_event_topics": {"ingested": "documents"},
            "catalog_review_gitops_binding": {},
        }.get(name, {})

    monkeypatch.setattr(standalone_host, "_private_json", private_json)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(standalone_host, "_activate_terraform_stage", lambda *_: None)
    monkeypatch.setattr(
        standalone_host,
        "_terraform_output",
        lambda _infra, name: (
            "console.azurestaticapps.net" if name == "console_default_hostname" else name
        ),
    )
    monkeypatch.setattr(standalone_host, "_terraform_json_output", json_output)
    monkeypatch.setattr(
        standalone_host, "_subnet_network_security_group", lambda *_a, **_k: "/nsg/aks"
    )
    monkeypatch.setattr(
        standalone_host, "_prepare_aks_kubeconfig", lambda *_a, **_k: tmp_path / "aks.kubeconfig"
    )
    monkeypatch.setattr(standalone_host, "_aks_core_conversation_environment", lambda **_kwargs: {})
    monkeypatch.setattr(
        standalone_host, "_aks_kubernetes_direct_api_environment", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        standalone_host,
        "_aks_document_workloads",
        lambda **_kwargs: {
            "document-ingestion-api": {
                "image": "ingestion",
                "replicas": 1,
                "max_replicas": 1,
                "env": {},
                "secret_environment": {"FDAI_STATE_STORE_DSN": "fdai-state-store-dsn"},
            }
        },
    )
    monkeypatch.setattr(
        standalone_host,
        "_prepare_aks_scheduled_jobs",
        lambda **_kwargs: SimpleNamespace(
            jobs={},
            protected_template_digests={},
            protected_identity_bindings={},
            catalog_review_available=False,
        ),
    )
    monkeypatch.setattr(standalone_host, "_vault_name", lambda _uri: "vault")
    monkeypatch.setattr(
        standalone_host,
        "_replace_or_verify_private_json",
        lambda _path, values: captured.update(values=values),
    )
    monkeypatch.setattr(standalone_host, "_replace_private_json", lambda *_a, **_k: None)
    monkeypatch.setattr(standalone_host, "_initialize_terraform_stage", lambda *_a, **_k: None)
    monkeypatch.setattr(
        standalone_host,
        "_aks_workload",
        lambda name, *_a, **_k: {
            "service": name,
            "env": _a[2],
            "secret_environment": _a[3],
            "image": f"image-{name}",
            "replicas": 1,
            "max_replicas": 1,
        },
    )

    standalone_host._prepare_aks_application(SimpleNamespace(), tmp_path)
    values = captured["values"]
    assert isinstance(values, dict)
    return values


def test_default_aks_workloads_carry_the_profile_and_omit_unselected_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _prepare(tmp_path, monkeypatch, ())
    workloads = values["workloads"]
    assert isinstance(workloads, dict)

    assert set(workloads) == {"core-control-plane"}
    assert workloads["core-control-plane"]["env"]["FDAI_PRODUCT_PROFILE_JSON"] == _PROFILE_JSON


def test_explicit_add_ons_restore_every_aks_workload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _prepare(tmp_path, monkeypatch, _FULL_ADD_ONS)
    workloads = values["workloads"]
    assert isinstance(workloads, dict)

    assert {"core-control-plane", "operator-service", "isolated-executor"} <= set(workloads)
    assert "document-ingestion-api" in workloads
    assert workloads["core-control-plane"]["env"]["FDAI_PRODUCT_PROFILE_JSON"] == _PROFILE_JSON
    operator_env = workloads["operator-service"]["env"]
    assert operator_env["FDAI_RBAC_APPROVERS_GROUP_ID"] == "approvers"
    assert operator_env["FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS"].startswith("https://")
