from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import cli, entra_source
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.entra_profiles import load_target_profile

EXECUTOR_OBJECT = "00000000-0000-0000-0000-000000000004"
EXECUTOR_CLIENT = "00000000-0000-0000-0000-000000000005"
TARGET_BINDING = "a" * 64


def _control() -> dict[str, object]:
    return {
        "schema_version": "fdai.entra-control-profile.v1",
        "premium_service_plan": "AAD_PREMIUM_P2",
        "role_groups": {
            "readers": "00000000-0000-0000-0000-000000000011",
            "contributors": "00000000-0000-0000-0000-000000000012",
            "approvers": "00000000-0000-0000-0000-000000000013",
            "owners": "00000000-0000-0000-0000-000000000014",
            "break_glass": "00000000-0000-0000-0000-000000000015",
        },
        "conditional_access_policies": [
            {
                "policy_id": "00000000-0000-0000-0000-000000000021",
                "include_group_slots": ["approvers", "owners"],
                "exclude_group_slots": [],
                "include_users": [],
                "exclude_users": [],
                "include_roles": [],
                "exclude_roles": [],
                "client_app_types": ["all"],
                "include_applications": ["All"],
                "exclude_applications": [],
                "include_platforms": [],
                "exclude_platforms": [],
                "include_locations": [],
                "exclude_locations": [],
                "sign_in_risk_levels": [],
                "user_risk_levels": [],
                "device_filter_mode": None,
                "device_filter_rule": None,
                "grant_operator": "AND",
                "grant_controls": ["authenticationStrength"],
                "authentication_strength_id": "00000000-0000-0000-0000-000000000022",
            }
        ],
        "access_reviews": [
            {
                "definition_id": "00000000-0000-0000-0000-000000000031",
                "group_slot": "owners",
                "scope_query_type": "MicrosoftGraph",
                "recurrence_pattern_type": "absoluteMonthly",
                "recurrence_interval": 1,
                "recurrence_range_type": "noEnd",
                "duration_days": 14,
                "allowed_statuses": ["NotStarted"],
            }
        ],
        "authentication_methods": [
            {
                "method_id": "fido2",
                "state": "enabled",
                "include_group_slots": ["approvers", "owners"],
            }
        ],
        "azure_policy_assignments": [
            {
                "assignment_id": "/subscriptions/example/providers/policyAssignments/fdai",
                "definition_id": "/providers/policyDefinitions/fdai-deny",
                "enforcement_mode": "Default",
                "scope": "/subscriptions/example",
            }
        ],
    }


def _profiles(tmp_path: Path, *, environment: str = "dev") -> tuple[Path, Path]:
    control = _control()
    control_path = tmp_path / "control.json"
    target_path = tmp_path / "target.json"
    control_path.write_text(json.dumps(control))
    target_path.write_text(
        json.dumps(
            {
                "schema_version": "fdai.entra-target-profile.v2",
                "environment": environment,
                "target_binding": TARGET_BINDING,
                "executor_object_id": EXECUTOR_OBJECT,
                "executor_client_id": EXECUTOR_CLIENT,
                "executor_display_name": "id-fdai-dev-executor",
                "executor_azure_config_dir": str((tmp_path / "executor-azure").absolute()),
                "control_profile_digest": canonical_digest(control),
            }
        )
    )
    control_path.chmod(0o600)
    target_path.chmod(0o600)
    return target_path.absolute(), control_path.absolute()


def test_parser_requires_private_profiles_and_defaults_to_read_only(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        cli,
        "run_source_entra_operation",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    assert (
        cli.main(
            [
                "provision",
                "entra",
                "--source",
                ".",
                "--work-dir",
                "/private/identity",
                "--target-profile",
                "/private/target.json",
                "--control-profile",
                "/private/controls.json",
                "--output",
                "json",
            ]
        )
        == 0
    )
    assert calls == [
        {
            "source": Path("."),
            "work_dir": Path("/private/identity"),
            "target_profile_path": Path("/private/target.json"),
            "control_profile_path": Path("/private/controls.json"),
            "apply": False,
            "output": "json",
            "timeout_seconds": 600,
        }
    ]


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_non_dev_profile_denies_apply_before_target_or_workdir(
    tmp_path, monkeypatch, environment
) -> None:
    target, control = _profiles(tmp_path, environment=environment)
    work_dir = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        entra_source,
        "azure_active_target_binding",
        lambda: pytest.fail("non-dev apply reached Azure target readback"),
    )

    with pytest.raises(ValueError, match="profile-bound dev target"):
        entra_source.run_source_entra_operation(
            source=tmp_path / "missing-source",
            work_dir=work_dir,
            target_profile_path=target,
            control_profile_path=control,
            apply=True,
            output="json",
            timeout_seconds=300,
        )

    assert not work_dir.exists()


def test_target_mismatch_stops_before_source_snapshot_or_workdir(tmp_path, monkeypatch) -> None:
    target, control = _profiles(tmp_path)
    work_dir = tmp_path / "must-not-exist"
    monkeypatch.setattr(entra_source, "azure_active_target_binding", lambda: "b" * 64)
    monkeypatch.setattr(
        entra_source,
        "inspect_source",
        lambda _root: pytest.fail("target mismatch reached source inspection"),
    )

    with pytest.raises(ValueError, match="does not match"):
        entra_source.run_source_entra_operation(
            source=tmp_path / "missing-source",
            work_dir=work_dir,
            target_profile_path=target,
            control_profile_path=control,
            apply=False,
            output="json",
            timeout_seconds=300,
        )

    assert not work_dir.exists()


def test_target_profile_must_be_private_before_any_provider_read(tmp_path, monkeypatch) -> None:
    target, control = _profiles(tmp_path)
    target.chmod(0o644)
    monkeypatch.setattr(
        entra_source,
        "azure_active_target_binding",
        lambda: pytest.fail("public target profile reached provider readback"),
    )

    with pytest.raises(PermissionError, match="mode-0600"):
        entra_source.run_source_entra_operation(
            source=tmp_path,
            work_dir=tmp_path / "work",
            target_profile_path=target,
            control_profile_path=control,
            apply=False,
            output="json",
            timeout_seconds=300,
        )


def test_dev_apply_uses_snapshot_isolated_imports_and_redacts_executor_argv(
    tmp_path, monkeypatch
) -> None:
    target_path, control_path = _profiles(tmp_path)
    target = load_target_profile(target_path)
    source = tmp_path / "mutable-source"
    source.mkdir()
    work_dir = tmp_path / "private"
    snapshot = work_dir / "source-snapshot"
    tree = snapshot / "tree"
    entrypoint = tree / "scripts/deployment/azure/genesis_entra_operation.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("# tracked snapshot entrypoint\n")
    captured = {}

    monkeypatch.setattr(entra_source, "azure_active_target_binding", lambda: TARGET_BINDING)
    monkeypatch.setattr(
        entra_source,
        "inspect_source",
        lambda root: SimpleNamespace(root=root, digest="c" * 64),
    )
    monkeypatch.setattr(
        entra_source,
        "_ensure_private_directory",
        lambda path: path.mkdir(0o700, exist_ok=True),
    )
    monkeypatch.setattr(
        entra_source,
        "_prepare_snapshot",
        lambda **_kwargs: (snapshot, "d" * 64),
    )
    monkeypatch.setattr(entra_source, "verify_source_snapshot", lambda *_args, **_kwargs: {})

    def run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(entra_source, "_run_identity_process", run)

    assert (
        entra_source.run_source_entra_operation(
            source=source,
            work_dir=work_dir,
            target_profile_path=target_path,
            control_profile_path=control_path,
            apply=True,
            output="json",
            timeout_seconds=300,
        )
        == 0
    )
    command = captured["command"]
    environment = captured["environment"]
    assert command[:3] == [os.sys.executable, "-I", "-c"]
    assert "--apply" in command
    assert "--executor-principal-id" not in command
    assert EXECUTOR_OBJECT not in json.dumps(command)
    assert EXECUTOR_CLIENT not in json.dumps(command)
    assert EXECUTOR_OBJECT not in json.dumps(environment)
    assert EXECUTOR_CLIENT not in json.dumps(environment)
    assert "PYTHONPATH" not in environment
    assert environment["FDAI_ENTRA_SNAPSHOT_ROOT"] == str(tree)
    assert str(source) not in json.dumps(command)
    assert str(source) not in json.dumps(environment)
    assert target.environment == "dev"


def test_snapshot_mutation_blocks_before_child_execution(tmp_path, monkeypatch) -> None:
    target_path, control_path = _profiles(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    work_dir = tmp_path / "private"
    snapshot = work_dir / "source-snapshot"
    tree = snapshot / "tree"
    entrypoint = tree / "scripts/deployment/azure/genesis_entra_operation.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("# inspected tracked bytes\n")

    monkeypatch.setattr(entra_source, "azure_active_target_binding", lambda: TARGET_BINDING)
    monkeypatch.setattr(
        entra_source,
        "inspect_source",
        lambda root: SimpleNamespace(root=root, digest="c" * 64),
    )
    monkeypatch.setattr(
        entra_source,
        "_ensure_private_directory",
        lambda path: path.mkdir(0o700, exist_ok=True),
    )

    def prepare(**_kwargs):
        entrypoint.write_text("# substituted ignored bytes\n")
        return snapshot, "d" * 64

    monkeypatch.setattr(entra_source, "_prepare_snapshot", prepare)
    monkeypatch.setattr(
        entra_source,
        "verify_source_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("snapshot content changed")),
    )
    monkeypatch.setattr(
        entra_source,
        "_run_identity_process",
        lambda *_args, **_kwargs: pytest.fail("mutated snapshot reached child execution"),
    )

    with pytest.raises(ValueError, match="snapshot content changed"):
        entra_source.run_source_entra_operation(
            source=source,
            work_dir=work_dir,
            target_profile_path=target_path,
            control_profile_path=control_path,
            apply=True,
            output="json",
            timeout_seconds=300,
        )
