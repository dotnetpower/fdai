from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts/deployment/azure"
sys.path.insert(0, str(_SCRIPTS))


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ambiguity = _load("scoped_terraform_ambiguity")
coordinator = _load("scoped_terraform")
VM = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"


NOW = datetime.now(UTC)


def _log(*events: tuple[str, str, int]):
    def run(command: tuple[str, ...], _timeout: int) -> str:
        assert command[:4] == ("az", "monitor", "activity-log", "list")
        return json.dumps(
            [
                {"c": c, "s": s, "t": (NOW + timedelta(seconds=offset)).isoformat()}
                for c, s, offset in events
            ]
        )

    return run


def _record(tmp_path: Path, operation: str = "apply") -> None:
    ambiguity.record(tmp_path, "target", operation_id="op-a", operation=operation, started_at=NOW)


def _settle(tmp_path: Path, run, operation: str, operation_id: str = "op-a") -> bool:
    return ambiguity.require_settled(
        run, tmp_path, "target", vm_resource_id=VM, operation_id=operation_id, operation=operation
    )


SETTLED = _log(("x", "Started", 1), ("x", "Accepted", 2), ("x", "Succeeded", 90))


def test_no_marker_permits_every_operation(tmp_path: Path) -> None:
    for operation in ("plan", "apply", "verify"):
        assert _settle(tmp_path, _log(), operation) is False


@pytest.mark.parametrize(
    ("events", "state"),
    [
        ((), "unrecorded"),
        ((("x", "Started", 1), ("x", "Accepted", 2)), "running"),
        ((("old", "Started", -600),), "unrecorded"),
        ((("x", "Started", 1), ("x", "Succeeded", 9), ("y", "Started", 20)), "running"),
    ],
)
def test_unsettled_host_blocks_even_verify(
    tmp_path: Path, events: tuple[tuple[str, str, int], ...], state: str
) -> None:
    _record(tmp_path)

    for operation in ("plan", "apply", "verify"):
        with pytest.raises(ambiguity.AmbiguousOutcomeError, match=f"is {state}"):
            _settle(tmp_path, _log(*events), operation)


@pytest.mark.parametrize("terminal", ambiguity.TERMINAL)
def test_settled_host_permits_only_verify_of_the_same_operation(
    tmp_path: Path, terminal: str
) -> None:
    _record(tmp_path)
    run = _log(("x", "Started", 1), ("x", terminal, 60))

    for operation in ("plan", "apply"):
        with pytest.raises(ambiguity.AmbiguousOutcomeError, match="run verify for operation op-a"):
            _settle(tmp_path, run, operation)
    with pytest.raises(ambiguity.AmbiguousOutcomeError, match="op-a"):
        _settle(tmp_path, run, "verify", operation_id="op-b")
    assert _settle(tmp_path, run, "verify") is True

    ambiguity.clear(tmp_path, "target")
    assert _settle(tmp_path, _log(), "apply") is False


def test_marker_is_private(tmp_path: Path) -> None:
    _record(tmp_path, "plan")
    path = ambiguity.marker_path(tmp_path, "target")

    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["operation_id"] == "op-a"


def test_transport_timeout_and_missing_result_are_ambiguous() -> None:
    def timeout(_command: tuple[str, ...], _timeout: int) -> str:
        raise coordinator.CoordinatorError("az vm exceeded 2400s")

    def empty(_command: tuple[str, ...], _timeout: int) -> str:
        return json.dumps({"value": [{"message": "[stdout]\n\n[stderr]\n"}]})

    def lost(_command: tuple[str, ...], _timeout: int) -> str:
        raise subprocess.SubprocessError("connection reset")

    for run in (timeout, empty, lost):
        with pytest.raises(coordinator.TransportAmbiguousError):
            coordinator.invoke(run, VM, "#!/bin/bash\n", "apply")


def test_busy_host_is_not_recorded_as_ambiguous() -> None:
    def busy(_command: tuple[str, ...], _timeout: int) -> str:
        raise coordinator.RunCommandBusyError("another Run Command is active on the managed host")

    with pytest.raises(coordinator.RunCommandBusyError):
        coordinator.invoke(busy, VM, "#!/bin/bash\n", "apply")


def test_capture_classifies_the_azure_busy_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess(
        ("az",),
        1,
        stdout="",
        stderr="ERROR: (Conflict) Run command extension execution is in progress.",
    )
    monkeypatch.setattr(coordinator.subprocess, "run", lambda *_a, **_k: completed)

    with pytest.raises(coordinator.RunCommandBusyError):
        coordinator.capture(("az", "vm", "run-command", "invoke"), 5)
