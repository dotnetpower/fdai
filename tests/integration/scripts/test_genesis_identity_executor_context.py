"""Offline serialization tests for the process-wide Azure CLI identity context."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from threading import Event, Thread

import pytest
from fdai_deployment_cli.entra_profiles import EntraTargetProfile

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_identity_executor  # noqa: E402

EXECUTOR = "00000000-0000-0000-0000-000000000002"
EXECUTOR_CLIENT = "00000000-0000-0000-0000-000000000003"


def _target(config_dir: Path) -> EntraTargetProfile:
    config_dir.mkdir(mode=0o700)
    config_dir.chmod(0o700)
    return EntraTargetProfile.from_mapping(
        {
            "schema_version": "fdai.entra-target-profile.v2",
            "environment": "dev",
            "target_binding": "a" * 64,
            "executor_object_id": EXECUTOR,
            "executor_client_id": EXECUTOR_CLIENT,
            "executor_display_name": "id-fdai-dev-executor",
            "executor_azure_config_dir": str(config_dir),
            "control_profile_digest": "b" * 64,
        }
    )


def _bind_executor(monkeypatch, binding: str | None) -> list[str | None]:
    observed_configs: list[str | None] = []

    def active_target() -> str | None:
        observed_configs.append(os.environ.get("AZURE_CONFIG_DIR"))
        return binding

    monkeypatch.setattr(
        genesis_identity_executor,
        "_current_graph_token_identity",
        lambda: (EXECUTOR, EXECUTOR_CLIENT),
    )
    monkeypatch.setattr(
        genesis_identity_executor,
        "azure_active_target_binding",
        active_target,
    )
    return observed_configs


def test_identity_operations_serialize_nested_executor_contexts_and_restore(
    tmp_path: Path,
    monkeypatch,
) -> None:
    human_config = tmp_path / "human"
    human_config.mkdir(mode=0o700)
    first = _target(tmp_path / "executor-one")
    second = _target(tmp_path / "executor-two")
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(human_config))
    _bind_executor(monkeypatch, first.target_binding)

    first_entered = Event()
    release_first = Event()
    second_attempting = Event()
    second_entered = Event()
    observations: list[tuple[str, str | None]] = []
    errors: list[BaseException] = []

    def first_operation() -> None:
        try:
            with genesis_identity_executor.identity_operation_context():
                observations.append(("first-human", os.environ.get("AZURE_CONFIG_DIR")))
                with genesis_identity_executor.executor_execution_context(first):
                    observations.append(("first-executor", os.environ.get("AZURE_CONFIG_DIR")))
                    first_entered.set()
                    if not release_first.wait(timeout=2):
                        raise AssertionError("second operation did not release the first")
                observations.append(("first-restored", os.environ.get("AZURE_CONFIG_DIR")))
        except BaseException as exc:
            errors.append(exc)

    def second_operation() -> None:
        try:
            if not first_entered.wait(timeout=2):
                raise AssertionError("first operation did not enter its executor context")
            second_attempting.set()
            with genesis_identity_executor.identity_operation_context():
                observations.append(("second-human", os.environ.get("AZURE_CONFIG_DIR")))
                second_entered.set()
                try:
                    with genesis_identity_executor.executor_execution_context(second):
                        observations.append(("second-executor", os.environ.get("AZURE_CONFIG_DIR")))
                        raise RuntimeError("executor provider read failed")
                except RuntimeError:
                    observations.append(("second-after-error", os.environ.get("AZURE_CONFIG_DIR")))
            observations.append(("second-after-operation", os.environ.get("AZURE_CONFIG_DIR")))
        except BaseException as exc:
            errors.append(exc)

    first_thread = Thread(target=first_operation)
    second_thread = Thread(target=second_operation)
    first_thread.start()
    assert first_entered.wait(timeout=2)
    second_thread.start()
    assert second_attempting.wait(timeout=2)
    try:
        assert not second_entered.wait(timeout=0.2)
    finally:
        release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert observations == [
        ("first-human", str(human_config)),
        ("first-executor", str(first.executor_azure_config_dir)),
        ("first-restored", str(human_config)),
        ("second-human", str(human_config)),
        ("second-executor", str(second.executor_azure_config_dir)),
        ("second-after-error", str(human_config)),
        ("second-after-operation", str(human_config)),
    ]
    assert os.environ["AZURE_CONFIG_DIR"] == str(human_config)


@pytest.mark.parametrize(
    ("active_binding", "expected"),
    [
        (None, "executor Azure target is unavailable"),
        ("c" * 64, "executor Azure target does not match the target profile"),
    ],
)
def test_executor_context_rejects_unavailable_or_mismatched_active_target(
    tmp_path: Path,
    monkeypatch,
    active_binding: str | None,
    expected: str,
) -> None:
    human_config = tmp_path / "human"
    human_config.mkdir(mode=0o700)
    target = _target(tmp_path / "executor")
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(human_config))
    target_contexts = _bind_executor(monkeypatch, active_binding)
    caller_entered = False

    with pytest.raises(ValueError, match=expected) as error:
        with genesis_identity_executor.executor_execution_context(target):
            caller_entered = True

    assert caller_entered is False
    assert os.environ["AZURE_CONFIG_DIR"] == str(human_config)
    assert target_contexts == [str(target.executor_azure_config_dir)]
    rendered = str(error.value)
    for private_value in (
        EXECUTOR,
        EXECUTOR_CLIENT,
        target.target_binding,
        str(target.executor_azure_config_dir),
    ):
        assert private_value not in rendered
