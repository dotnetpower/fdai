from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai_deployment_cli import bootstrap_reconcile
from fdai_deployment_cli.bootstrap_plan import (
    FOUNDATION_PROVIDER_NAMESPACES,
    BootstrapReconcileResult,
)
from fdai_deployment_cli.bootstrap_reconcile import (
    CommandResult,
    reconcile_bootstrap,
)
from fdai_deployment_cli.cli import main
from fdai_deployment_cli.contracts import ProvisionProfile
from fdai_deployment_cli.profile import write_profile
from fdai_deployment_cli.target import compute_target_binding

_TENANT = "00000000-0000-0000-0000-000000000000"
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_SOURCE_COMMIT = "a" * 40
_TARGET_BINDING = compute_target_binding(tenant_id=_TENANT, subscription_id=_SUBSCRIPTION)


def _profile() -> ProvisionProfile:
    return ProvisionProfile(
        environment="dev",
        region="koreacentral",
        target_binding=_TARGET_BINDING,
        connectivity="online",
        host="managed-vm",
        transport="github-actions",
        access_method="github_actions",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=100,
    )


class AzureReads:
    def __init__(
        self,
        *,
        group_error: str = "ResourceGroupNotFound",
        storage_error: str = "ResourceNotFound",
        storage_available: bool = True,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.group_error = group_error
        self.storage_error = storage_error
        self.storage_available = storage_available

    def __call__(self, arguments: tuple[str, ...]) -> CommandResult:
        self.calls.append(arguments)
        if arguments[:2] == ("account", "show"):
            return CommandResult(
                0,
                json.dumps({"subscription": _SUBSCRIPTION, "tenant": _TENANT}),
            )
        if arguments[:2] == ("provider", "show"):
            return CommandResult(0, "Registered\n")
        if arguments[:2] == ("group", "show"):
            return CommandResult(1, "", json.dumps({"error": {"code": self.group_error}}))
        if arguments[:3] == ("storage", "account", "show"):
            return CommandResult(1, "", json.dumps({"error": {"code": self.storage_error}}))
        if arguments[:3] == ("storage", "account", "check-name"):
            return CommandResult(
                0,
                json.dumps({"available": self.storage_available, "reason": None}),
            )
        raise AssertionError(f"unexpected Azure CLI read: {arguments}")


def _reconcile(
    reads: AzureReads,
    *,
    now: datetime | None = None,
) -> BootstrapReconcileResult:
    return reconcile_bootstrap(
        _profile(),
        source_commit=_SOURCE_COMMIT,
        ops_resource_group="rg-fdai-ops-krc",
        app_resource_group="rg-fdai-dev-krc",
        state_storage_account="stfdaigenesis001",
        now=now,
        run=reads,
    )


def test_bootstrap_reconcile_is_read_only_target_pinned_and_reviewable() -> None:
    reads = AzureReads()
    result = _reconcile(reads, now=datetime(2026, 8, 30, tzinfo=UTC))
    payload = result.to_mapping()

    assert payload["state"] == "review"
    assert payload["mutation_performed"] is False
    assert payload["reason_codes"] == []
    assert len(result.observations) == len(FOUNDATION_PROVIDER_NAMESPACES) + 3
    operation_ids = {item["entry_id"] for item in result.intent["operations"]}
    assert {
        "ops-network",
        "deploy-identity",
        "runner",
        "state-containers",
        "state-handoff",
    } <= operation_ids
    assert result.intent["state_storage_posture"]["containers"] == [
        "tfstate",
        "deployment-plans",
    ]
    assert all(
        "--subscription" in call and call[call.index("--subscription") + 1] == _SUBSCRIPTION
        for call in reads.calls[1:]
    )
    assert all(call[:2] != ("provider", "register") for call in reads.calls)
    assert all(call[:3] != ("storage", "account", "create") for call in reads.calls)
    encoded = json.dumps(payload, sort_keys=True)
    assert _TENANT not in encoded
    assert _SUBSCRIPTION not in encoded
    assert "/subscriptions/" not in encoded


def test_bootstrap_plan_digest_excludes_observation_time() -> None:
    first = _reconcile(AzureReads(), now=datetime(2026, 8, 30, tzinfo=UTC))
    second = _reconcile(
        AzureReads(),
        now=datetime(2026, 8, 30, tzinfo=UTC) + timedelta(minutes=5),
    )

    assert first.plan_digest == second.plan_digest
    assert first.observation_digest != second.observation_digest


def test_non_not_found_read_error_blocks_instead_of_planning_create() -> None:
    result = _reconcile(AzureReads(group_error="AuthorizationFailed"))

    assert result.to_mapping()["state"] == "incomplete"
    assert "resource_group_read_failed" in result.blockers
    assert result.observations[-3].classification.value == "indeterminate"


def test_globally_unavailable_storage_name_is_a_conflict() -> None:
    result = _reconcile(AzureReads(storage_available=False))

    assert result.to_mapping()["state"] == "incomplete"
    assert result.observations[-1].classification.value == "conflict"
    assert "state_storage_name_unavailable" in result.blockers


def test_existing_storage_must_match_private_keyless_posture() -> None:
    class ExistingStorage(AzureReads):
        def __call__(self, arguments: tuple[str, ...]) -> CommandResult:
            if arguments[:3] == ("storage", "account", "show"):
                self.calls.append(arguments)
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "name": "stfdaigenesis001",
                            "location": "koreacentral",
                            "kind": "StorageV2",
                            "sku": "Standard_LRS",
                            "minimum_tls_version": "TLS1_2",
                            "public_network_access": "Enabled",
                            "shared_key_access": False,
                            "blob_public_access": False,
                            "cross_tenant_replication": False,
                        }
                    ),
                )
            return super().__call__(arguments)

    result = _reconcile(ExistingStorage())

    assert "state_storage_posture_conflict" in result.blockers


def test_existing_storage_requires_management_plane_data_protection_readback() -> None:
    class ExistingStorage(AzureReads):
        def __call__(self, arguments: tuple[str, ...]) -> CommandResult:
            if arguments[:4] == ("storage", "account", "blob-service-properties", "show"):
                self.calls.append(arguments)
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "versioning": False,
                            "blob_delete_retention": True,
                            "container_delete_retention": True,
                        }
                    ),
                )
            if arguments[:3] == ("storage", "account", "show"):
                self.calls.append(arguments)
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "name": "stfdaigenesis001",
                            "location": "koreacentral",
                            "kind": "StorageV2",
                            "sku": "Standard_LRS",
                            "minimum_tls_version": "TLS1_2",
                            "public_network_access": "Disabled",
                            "shared_key_access": False,
                            "blob_public_access": False,
                            "cross_tenant_replication": False,
                        }
                    ),
                )
            return super().__call__(arguments)

    reads = ExistingStorage()
    result = _reconcile(reads)

    assert result.to_mapping()["state"] == "review"
    assert result.observations[-1].classification.value == "missing"
    assert result.observations[-1].reason_code == "state_storage_data_protection_required"
    data_protection_read = next(
        call
        for call in reads.calls
        if call[:4] == ("storage", "account", "blob-service-properties", "show")
    )
    assert data_protection_read[data_protection_read.index("--subscription") + 1] == _SUBSCRIPTION


def test_msi_environment_never_waives_target_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARM_USE_MSI", "true")
    mismatched = AzureReads()

    def wrong_target(arguments: tuple[str, ...]) -> CommandResult:
        if arguments[:2] == ("account", "show"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "subscription": "00000000-0000-0000-0000-000000000002",
                        "tenant": _TENANT,
                    }
                ),
            )
        return mismatched(arguments)

    with pytest.raises(ValueError, match="active Azure target"):
        reconcile_bootstrap(
            _profile(),
            source_commit=_SOURCE_COMMIT,
            ops_resource_group="rg-fdai-ops-krc",
            app_resource_group="rg-fdai-dev-krc",
            state_storage_account="stfdaigenesis001",
            run=wrong_target,
        )


def test_cli_writes_exclusive_private_plan_and_sanitized_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile_path = tmp_path / "profile.json"
    output_path = tmp_path / "bootstrap-plan.json"
    write_profile(profile_path, _profile())
    monkeypatch.setattr(bootstrap_reconcile, "run_azure_cli", AzureReads())

    status = main(
        [
            "provision",
            "bootstrap-reconcile",
            "--profile",
            str(profile_path),
            "--source-commit",
            _SOURCE_COMMIT,
            "--ops-resource-group",
            "rg-fdai-ops-krc",
            "--app-resource-group",
            "rg-fdai-dev-krc",
            "--state-storage-account",
            "stfdaigenesis001",
            "--output-plan",
            str(output_path),
            "--output",
            "json",
        ]
    )

    assert status == 2
    assert output_path.stat().st_mode & 0o777 == 0o600
    stdout = capsys.readouterr().out
    assert _TENANT not in stdout
    assert _SUBSCRIPTION not in stdout
    assert json.loads(stdout)["mutation_performed"] is False
    assert json.loads(output_path.read_text(encoding="utf-8"))["state"] == "review"

    assert (
        main(
            [
                "provision",
                "bootstrap-reconcile",
                "--profile",
                str(profile_path),
                "--source-commit",
                _SOURCE_COMMIT,
                "--ops-resource-group",
                "rg-fdai-ops-krc",
                "--app-resource-group",
                "rg-fdai-dev-krc",
                "--state-storage-account",
                "stfdaigenesis001",
                "--output-plan",
                str(output_path),
            ]
        )
        == 3
    )


def test_cli_never_follows_output_parent_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile_path = tmp_path / "profile.json"
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    write_profile(profile_path, _profile())
    monkeypatch.setattr(bootstrap_reconcile, "run_azure_cli", AzureReads())

    status = main(
        [
            "provision",
            "bootstrap-reconcile",
            "--profile",
            str(profile_path),
            "--source-commit",
            _SOURCE_COMMIT,
            "--ops-resource-group",
            "rg-fdai-ops-krc",
            "--app-resource-group",
            "rg-fdai-dev-krc",
            "--state-storage-account",
            "stfdaigenesis001",
            "--output-plan",
            str(linked / "bootstrap-plan.json"),
        ]
    )

    assert status == 3
    assert not (target / "bootstrap-plan.json").exists()
    assert "fdaictl:" in capsys.readouterr().err


def test_azure_cli_timeout_never_exposes_target_in_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/az")

    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            cmd=["az", "group", "show", "--subscription", _SUBSCRIPTION],
            timeout=30,
        )

    monkeypatch.setattr("subprocess.run", timeout)

    result = bootstrap_reconcile.run_azure_cli(("group", "show", "--subscription", _SUBSCRIPTION))

    assert result == CommandResult(returncode=124, stdout="", stderr="")
    assert _SUBSCRIPTION not in result.stderr
