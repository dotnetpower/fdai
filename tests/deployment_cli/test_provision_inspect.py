"""Tests for read-only provisioning execution-profile inspection."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from fdai.deployment_cli.cli import main
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
