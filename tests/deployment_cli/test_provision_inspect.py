"""Tests for read-only provisioning execution-profile inspection."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from fdai.deployment_cli.cli import main
from fdai.deployment_cli.offline_kit import (
    OfflineKitVerification,
    OfflineKitVerificationError,
)
from fdai.deployment_cli.provision_inspect import (
    ACCESS_PREFERENCE,
    Connectivity,
    ExecutionHost,
    ExecutionTransport,
    ProvisionInspectResult,
    inspect_provisioning,
)


def _resolver(*available: str) -> Callable[[str], str | None]:
    return lambda command: f"/tools/{command}" if command in available else None


def test_existing_online_host_is_ready_without_mutation() -> None:
    result = inspect_provisioning(
        resolve_executable=_resolver("az", "terraform"),
        online_probe=lambda: True,
        workload_identity_probe=lambda: True,
    )

    assert result.status == "ready"
    assert result.connectivity is Connectivity.ONLINE
    assert result.execution_host is ExecutionHost.EXISTING
    assert result.transport is ExecutionTransport.MANUAL
    assert result.access_method == "internal_ssh"
    assert result.required_human_approvers == 1
    assert result.require_distinct_executor_identity is True
    assert result.mutation_performed is False


def test_managed_vm_prefers_temporary_public_ssh_before_github_actions() -> None:
    result = inspect_provisioning(
        execution_host=ExecutionHost.MANAGED_VM,
        allow_temporary_public_ssh=True,
        resolve_executable=_resolver("az", "terraform", "gh"),
        online_probe=lambda: True,
        workload_identity_probe=lambda: False,
    )

    assert result.status == "review"
    assert result.access_method == "temporary_public_ssh"
    assert result.transport is ExecutionTransport.MANUAL
    assert result.to_dict()["access_preference"] == list(ACCESS_PREFERENCE)


def test_managed_vm_uses_github_actions_when_ssh_is_unavailable() -> None:
    result = inspect_provisioning(
        execution_host=ExecutionHost.MANAGED_VM,
        resolve_executable=_resolver("az", "terraform", "gh"),
        online_probe=lambda: True,
        workload_identity_probe=lambda: False,
    )

    assert result.status == "review"
    assert result.access_method == "github_actions"
    assert result.transport is ExecutionTransport.GITHUB_ACTIONS


def test_explicit_offline_mode_requires_complete_kit(tmp_path: Path) -> None:
    result = inspect_provisioning(
        connectivity=Connectivity.OFFLINE,
        execution_host=ExecutionHost.EXISTING,
        offline_kit=tmp_path,
        resolve_executable=_resolver("az", "terraform"),
        online_probe=lambda: False,
        workload_identity_probe=lambda: True,
    )

    assert result.status == "incomplete"
    assert result.exit_code == 4
    assert any(check.check_id == "artifact.offline-kit-shape" for check in result.checks)


def test_complete_offline_kit_requires_signature_review(tmp_path: Path) -> None:
    (tmp_path / "offline-kit.json").write_text("{}", encoding="utf-8")
    (tmp_path / "offline-kit.json.sig").write_bytes(b"candidate")

    result = inspect_provisioning(
        connectivity=Connectivity.OFFLINE,
        execution_host=ExecutionHost.EXISTING,
        offline_kit=tmp_path,
        resolve_executable=_resolver("az", "terraform"),
        online_probe=lambda: False,
        workload_identity_probe=lambda: True,
    )

    assert result.status == "review"
    assert result.exit_code == 2
    offline_check = next(
        check for check in result.checks if check.check_id == "artifact.offline-kit"
    )
    assert offline_check.status == "candidate"
    assert result.offline_kit_verified is False


def test_verified_offline_kit_makes_complete_existing_host_ready(tmp_path: Path) -> None:
    (tmp_path / "offline-kit.json").write_text("{}", encoding="utf-8")
    (tmp_path / "offline-kit.json.sig").write_bytes(b"candidate")

    result = inspect_provisioning(
        connectivity=Connectivity.OFFLINE,
        execution_host=ExecutionHost.EXISTING,
        offline_kit=tmp_path,
        offline_kit_verifier=lambda _path: OfflineKitVerification(
            kit_version="0.1.42",
            cli_version="0.1.42",
            bundle_version="0.1.42",
            platform_tag="linux-x86_64",
            manifest_digest="a" * 64,
            file_count=8,
            total_bytes=1024,
        ),
        resolve_executable=_resolver("az", "terraform"),
        online_probe=lambda: False,
        workload_identity_probe=lambda: True,
    )

    assert result.status == "ready"
    assert result.offline_kit_verified is True
    assert result.offline_kit_verification is not None
    assert result.offline_kit_verification.manifest_digest == "a" * 64
    offline_check = next(
        check for check in result.checks if check.check_id == "artifact.offline-kit"
    )
    assert offline_check.status == "verified"


def test_rejected_offline_kit_is_incomplete_and_sanitized(tmp_path: Path) -> None:
    (tmp_path / "offline-kit.json").write_text("{}", encoding="utf-8")
    (tmp_path / "offline-kit.json.sig").write_bytes(b"candidate")

    def reject(_path: Path) -> OfflineKitVerification:
        raise OfflineKitVerificationError("sensitive/path/offline-kit digest mismatch")

    result = inspect_provisioning(
        connectivity=Connectivity.OFFLINE,
        execution_host=ExecutionHost.EXISTING,
        offline_kit=tmp_path,
        offline_kit_verifier=reject,
        resolve_executable=_resolver("az", "terraform"),
        online_probe=lambda: False,
        workload_identity_probe=lambda: True,
    )

    assert result.status == "incomplete"
    assert result.offline_kit_verified is False
    assert result.offline_kit_verification is None
    offline_check = next(
        check for check in result.checks if check.check_id == "artifact.offline-kit"
    )
    assert offline_check.status == "fail"
    assert "sensitive" not in result.to_json()


def test_explicit_existing_host_requires_workload_identity() -> None:
    result = inspect_provisioning(
        execution_host=ExecutionHost.EXISTING,
        resolve_executable=_resolver("az", "terraform"),
        online_probe=lambda: True,
        workload_identity_probe=lambda: False,
    )

    assert result.status == "incomplete"
    assert result.execution_host is ExecutionHost.EXISTING


def test_cli_emits_stable_json(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = ProvisionInspectResult(
        status="review",
        connectivity=Connectivity.ONLINE,
        execution_host=ExecutionHost.MANAGED_VM,
        transport=ExecutionTransport.MANUAL,
        access_method="internal_ssh",
        checks=(),
    )
    monkeypatch.setattr("fdai.deployment_cli.cli.inspect_provisioning", lambda **_: expected)
    stdout = io.StringIO()

    exit_code = main(["provision", "inspect", "--output", "json"], stdout=stdout)

    assert exit_code == 2
    assert json.loads(stdout.getvalue()) == expected.to_dict()


def test_cli_text_states_that_inspection_made_no_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ProvisionInspectResult(
        status="ready",
        connectivity=Connectivity.ONLINE,
        execution_host=ExecutionHost.EXISTING,
        transport=ExecutionTransport.MANUAL,
        access_method="internal_ssh",
        checks=(),
    )
    monkeypatch.setattr("fdai.deployment_cli.cli.inspect_provisioning", lambda **_: expected)
    stdout = io.StringIO()

    exit_code = main(["provision", "inspect"], stdout=stdout)

    assert exit_code == 0
    assert stdout.getvalue().endswith("No resources were changed.\n")


def test_a_declared_offline_site_is_never_probed_over_the_public_internet() -> None:
    """The probe opens TLS connections to three public hosts. On a closed
    network that is an outbound attempt someone has to explain, and the
    operator already answered the question by declaring the site offline.
    """
    probes: list[str] = []

    def probe() -> bool:
        probes.append("public")
        return True

    result = inspect_provisioning(
        connectivity=Connectivity.OFFLINE,
        online_probe=probe,
        workload_identity_probe=lambda: False,
        resolve_executable=lambda name: None,
    )

    assert probes == []
    assert result.connectivity is Connectivity.OFFLINE


def test_an_auto_site_still_probes_because_it_has_not_been_told() -> None:
    probes: list[str] = []

    def probe() -> bool:
        probes.append("public")
        return True

    inspect_provisioning(
        connectivity=Connectivity.AUTO,
        online_probe=probe,
        workload_identity_probe=lambda: False,
        resolve_executable=lambda name: None,
    )

    assert probes == ["public"]
