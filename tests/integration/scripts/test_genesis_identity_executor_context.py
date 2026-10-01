"""Offline serialization tests for the process-wide Azure CLI identity context."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from threading import Event, RLock, Thread

import pytest
from fdai_deployment_cli.entra_profiles import EntraTargetProfile

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_identity_executor  # noqa: E402

EXECUTOR = "00000000-0000-0000-0000-000000000002"
EXECUTOR_CLIENT = "00000000-0000-0000-0000-000000000003"
# Only a stalled protocol exhausts this bound; no assertion races the scheduler.
STALL_GUARD_SECONDS = 30


class _ContentionObservingLock:
    """Delegate to the production lock and signal when another thread must wait for it."""

    def __init__(self, lock: RLock, progress: Event) -> None:
        self._lock = lock
        self._progress = progress
        self.contended = False

    def __enter__(self) -> None:
        if not self._lock.acquire(blocking=False):
            self.contended = True
            self._progress.set()
            self._lock.acquire()

    def __exit__(self, *_exc_info: object) -> None:
        self._lock.release()


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
    second_progress = Event()
    lock = _ContentionObservingLock(
        genesis_identity_executor._AZURE_CONFIG_CONTEXT_LOCK, second_progress
    )
    monkeypatch.setattr(genesis_identity_executor, "_AZURE_CONFIG_CONTEXT_LOCK", lock)

    first_entered = Event()
    release_first = Event()
    first_stalled = Event()
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
                    if not release_first.wait(timeout=STALL_GUARD_SECONDS):
                        first_stalled.set()
                        raise AssertionError("the test never released the first operation")
                observations.append(("first-restored", os.environ.get("AZURE_CONFIG_DIR")))
        except BaseException as exc:
            errors.append(exc)

    def second_operation() -> None:
        try:
            with genesis_identity_executor.identity_operation_context():
                observations.append(("second-human", os.environ.get("AZURE_CONFIG_DIR")))
                second_entered.set()
                second_progress.set()
                try:
                    with genesis_identity_executor.executor_execution_context(second):
                        observations.append(("second-executor", os.environ.get("AZURE_CONFIG_DIR")))
                        raise RuntimeError("executor provider read failed")
                except RuntimeError:
                    observations.append(("second-after-error", os.environ.get("AZURE_CONFIG_DIR")))
            observations.append(("second-after-operation", os.environ.get("AZURE_CONFIG_DIR")))
        except BaseException as exc:
            errors.append(exc)

    first_thread = Thread(target=first_operation, daemon=True)
    second_thread = Thread(target=second_operation, daemon=True)
    first_thread.start()
    try:
        assert first_entered.wait(timeout=STALL_GUARD_SECONDS)
        assert lock.contended is False
        second_thread.start()
        # The second operation either waits on the lock the first holds or, if serialization
        # failed, enters. Neither outcome depends on how far the scheduler delays this thread.
        assert second_progress.wait(timeout=STALL_GUARD_SECONDS)
        entered_early = second_entered.is_set()
        # A stall releases the first operation, so report it before a serialization failure.
        assert not first_stalled.is_set(), "the test stalled past the first operation's guard"
        assert not entered_early, "the second operation entered while the first held the lock"
        assert lock.contended is True
    finally:
        release_first.set()
    first_thread.join(timeout=STALL_GUARD_SECONDS)
    second_thread.join(timeout=STALL_GUARD_SECONDS)

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


def test_executor_contexts_serialize_without_an_identity_operation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    human_config = tmp_path / "human"
    human_config.mkdir(mode=0o700)
    first = _target(tmp_path / "executor-one")
    second = _target(tmp_path / "executor-two")
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(human_config))
    _bind_executor(monkeypatch, first.target_binding)
    second_progress = Event()
    lock = _ContentionObservingLock(
        genesis_identity_executor._AZURE_CONFIG_CONTEXT_LOCK, second_progress
    )
    monkeypatch.setattr(genesis_identity_executor, "_AZURE_CONFIG_CONTEXT_LOCK", lock)
    first_entered = Event()
    release_first = Event()
    first_stalled = Event()
    second_entered = Event()
    second_configs: list[str | None] = []
    errors: list[BaseException] = []

    def first_operation() -> None:
        try:
            with genesis_identity_executor.executor_execution_context(first):
                first_entered.set()
                if not release_first.wait(timeout=STALL_GUARD_SECONDS):
                    first_stalled.set()
                    raise AssertionError("the test never released the first operation")
        except BaseException as exc:
            errors.append(exc)

    def second_operation() -> None:
        try:
            with genesis_identity_executor.executor_execution_context(second):
                second_configs.append(os.environ.get("AZURE_CONFIG_DIR"))
                second_entered.set()
                second_progress.set()
        except BaseException as exc:
            errors.append(exc)

    first_thread = Thread(target=first_operation, daemon=True)
    second_thread = Thread(target=second_operation, daemon=True)
    first_thread.start()
    try:
        assert first_entered.wait(timeout=STALL_GUARD_SECONDS)
        second_thread.start()
        assert second_progress.wait(timeout=STALL_GUARD_SECONDS)
        entered_early = second_entered.is_set()
        assert not first_stalled.is_set(), "the test stalled past the first operation's guard"
        assert not entered_early, "the second executor context entered while the first held it"
        assert lock.contended is True
    finally:
        release_first.set()
    first_thread.join(timeout=STALL_GUARD_SECONDS)
    second_thread.join(timeout=STALL_GUARD_SECONDS)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert second_configs == [str(second.executor_azure_config_dir)]
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
