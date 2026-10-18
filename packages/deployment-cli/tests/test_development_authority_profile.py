from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli import cli
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.development_authority_profile import (
    apply_development_authority_profile,
    clear_development_authority_profile,
    load_development_authority_profile,
    stage_development_authority_profile,
    staged_development_authority_profile_from_path,
    validate_deployment_target,
)
from fdai_deployment_cli.standalone_host_values import aks_core_environment
from fdai_deployment_cli.standalone_development_authority import (
    apply_service_update_development_authority,
)


def _scope_digest(value: str) -> str:
    return "sha256:" + canonical_digest({"value": value.strip().lower()})


def _profile() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "profile_id": "fdai.dev.f06-f07",
        "scope": {
            "tenant_digest": _scope_digest("tenant-1"),
            "subscription_digest": _scope_digest("subscription-1"),
            "resource_group_digests": [],
        },
        "classification": "disposable_development",
        "owner_principal": "human:owner",
        "executor_principal": "identity:executor",
        "valid_from": "2026-10-18T00:00:00+00:00",
        "valid_until": "2026-10-19T00:00:00+00:00",
        "source_revision": "a" * 40,
        "catalog_revision": "catalog-1",
        "policy_revision": "policy-1",
        "registered_actions": [
            {
                "action_type": "remediate.right-size",
                "version": "1.0.0",
                "action_type_digest": "sha256:" + "b" * 64,
            }
        ],
    }


def _write(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return path


class _Tunnel:
    def __init__(self) -> None:
        self.copied: list[tuple[Path, str]] = []

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        assert timeout == 120
        self.copied.append((source, destination))


def test_profile_is_validated_staged_and_bound_to_exact_target(tmp_path: Path) -> None:
    selected = load_development_authority_profile(_write(tmp_path / "profile.json", _profile()))
    values: dict[str, object] = {}

    apply_development_authority_profile(values, selected)
    validate_deployment_target(
        selected,
        tenant_id="tenant-1",
        subscription_id="subscription-1",
        resource_groups=("rg-dev", "rg-ops"),
        source_revision="a" * 40,
    )
    tunnel = _Tunnel()
    arguments = stage_development_authority_profile(
        selected,
        tunnel=tunnel,
        prepared_root=tmp_path,
        remote_root="/remote",
    )
    staged = staged_development_authority_profile_from_path(tunnel.copied[0][0])

    assert arguments == (
        "--development-authority-profile",
        "/remote/development-authority-profile.json",
    )
    assert staged == selected
    assert values == {
        "development_authority_profile_json": selected.profile_json,
        "development_authority_executor_principal": "identity:executor",
    }
    assert clear_development_authority_profile(values) is True
    assert clear_development_authority_profile(values) is False
    assert values == {}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("executor_principal", "human:owner", "MUST be distinct"),
        ("valid_until", "2026-10-17T00:00:00+00:00", "interval"),
        ("source_revision", "", "source_revision"),
    ],
)
def test_invalid_profile_fails_before_staging(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    payload = {**_profile(), field: value}

    with pytest.raises(ValueError, match=message):
        load_development_authority_profile(_write(tmp_path / "profile.json", payload))


def test_target_or_source_drift_is_rejected(tmp_path: Path) -> None:
    selected = load_development_authority_profile(_write(tmp_path / "profile.json", _profile()))

    with pytest.raises(ValueError, match="subscription differs"):
        validate_deployment_target(
            selected,
            tenant_id="tenant-1",
            subscription_id="subscription-2",
            resource_groups=("rg-dev",),
            source_revision="a" * 40,
        )
    with pytest.raises(ValueError, match="source revision differs"):
        validate_deployment_target(
            selected,
            tenant_id="tenant-1",
            subscription_id="subscription-1",
            resource_groups=("rg-dev",),
            source_revision="c" * 40,
        )


def test_aks_core_environment_includes_profile_and_executor_together(
    tmp_path: Path,
) -> None:
    selected = load_development_authority_profile(_write(tmp_path / "profile.json", _profile()))
    application_values: dict[str, object] = {
        "region": "westus3",
        "env": "dev",
        "product_profile_json": "{}",
    }
    apply_development_authority_profile(application_values, selected)

    environment = aks_core_environment(
        context={"tenant_id": "tenant-1", "subscription_id": "subscription-1"},
        application_values=application_values,
        substrate_outputs={
            "kafka": "events",
            "postgres_fqdn": "postgres.example.invalid",
            "postgres_database": "fdai",
            "workspace": "workspace",
            "operating_model_topic": "operating-model",
            "operational_kafka": "operational-events",
            "installation_binding": "installation",
        },
        resource_group="rg-dev",
        core_identity={"client_id": "client"},
        topics=["events"],
        deployment_binding="deployment",
    )

    assert environment["FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON"] == (selected.profile_json)
    assert environment["FDAI_FULL_AUTHORITY_DEVELOPMENT_EXECUTOR_PRINCIPAL"] == (
        "identity:executor"
    )


def test_aks_core_environment_rejects_partial_binding() -> None:
    with pytest.raises(ValueError, match="selected together"):
        aks_core_environment(
            context={"tenant_id": "tenant-1", "subscription_id": "subscription-1"},
            application_values={
                "region": "westus3",
                "env": "dev",
                "product_profile_json": "{}",
                "development_authority_profile_json": "{}",
            },
            substrate_outputs={
                "kafka": "events",
                "postgres_fqdn": "postgres.example.invalid",
                "postgres_database": "fdai",
                "workspace": "workspace",
                "operating_model_topic": "operating-model",
                "operational_kafka": "operational-events",
                "installation_binding": "installation",
            },
            resource_group="rg-dev",
            core_identity={"client_id": "client"},
            topics=["events"],
            deployment_binding="deployment",
        )


def test_cli_requires_explicit_select_or_clear(tmp_path: Path, capsys) -> None:
    profile = _write(tmp_path / "profile.json", _profile())

    result = cli.main(
        [
            "provision",
            "azure",
            "--source",
            ".",
            "--runtime",
            "aks",
            "--development-authority-profile",
            str(profile),
            "--clear-development-profile",
        ]
    )

    assert result == 3
    assert "mutually exclusive" in capsys.readouterr().err


def test_service_update_selects_and_clears_core_environment(tmp_path: Path) -> None:
    profile_path = _write(tmp_path / "profile.json", _profile())
    context = {
        "tenant_id": "tenant-1",
        "subscription_id": "subscription-1",
        "resource_group_name": "rg-dev",
        "state_resource_group": "rg-ops",
    }
    workload: dict[str, object] = {"environment": {}}

    operation, digest = apply_service_update_development_authority(
        type(
            "Args",
            (),
            {
                "development_authority_profile": profile_path,
                "clear_development_authority_profile": False,
            },
        )(),
        context=context,
        workload=workload,
        source_revision="a" * 40,
    )
    environment = workload["environment"]

    assert operation == "select"
    assert digest
    assert isinstance(environment, dict)
    assert environment["FDAI_FULL_AUTHORITY_DEVELOPMENT_EXECUTOR_PRINCIPAL"] == (
        "identity:executor"
    )

    operation, digest = apply_service_update_development_authority(
        type(
            "Args",
            (),
            {
                "development_authority_profile": None,
                "clear_development_authority_profile": True,
            },
        )(),
        context=context,
        workload=workload,
        source_revision="a" * 40,
    )

    assert (operation, digest) == ("clear", "")
    assert environment == {}


def test_service_update_authority_requires_core(tmp_path: Path, capsys) -> None:
    profile = _write(tmp_path / "profile.json", _profile())

    result = cli.main(
        [
            "provision",
            "source-service-update",
            "--source",
            ".",
            "--service",
            "operator-service",
            "--application-work-dir",
            str(tmp_path / "application"),
            "--development-authority-profile",
            str(profile),
        ]
    )

    assert result == 3
    assert "require a Core service update" in capsys.readouterr().err
