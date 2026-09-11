from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = (
    _ROOT / "scripts" / "deployment" / "azure" / "update_inventory_job_runtime_call_evidence.sh"
)
_WORKSPACE_ID = "00000000-0000-0000-0000-000000000000"


def _run(
    tmp_path: Path,
    *,
    current_value: str = "",
    current_workspace: str = "",
    fail_update: bool = False,
    missing_target: bool = False,
    require_existing: bool = True,
    sticky_update: bool = False,
    desired_enabled: bool = True,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    state = tmp_path / "binding"
    state.write_text(current_value, encoding="ascii")
    workspace_state = tmp_path / "workspace"
    workspace_state.write_text(current_workspace, encoding="ascii")
    calls = tmp_path / "calls"
    az = tmp_path / "az"
    az.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2 $3" == "containerapp job show" ]]; then
  [[ "${MISSING_TARGET:-0}" != "1" ]] || exit 3
  if [[ "$*" == *"FDAI_MONITOR_WORKSPACE_ID"* ]]; then
    cat "$WORKSPACE_STATE"
  else
    cat "$BINDING_STATE"
  fi
  exit 0
fi
if [[ "$1 $2 $3 $4" == "monitor log-analytics workspace show" ]]; then
  printf '%s' "$WORKSPACE_ID"
  exit 0
fi
if [[ "$1 $2 $3" != "containerapp job update" ]]; then
  exit 90
fi
if [[ "$*" == *"--set-env-vars FDAI_RUNTIME_CALL_EVIDENCE_ENABLED=1"* ]]; then
  printf '%s\n' enable >> "$UPDATE_CALLS"
  [[ "${FAIL_UPDATE:-0}" != "1" ]] || exit 9
fi
sticky="${STICKY_UPDATE:-0}"
for value in "$@"; do
  if [[ "$value" == "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED=1" && "$sticky" != "1" ]]; then
    printf '1' > "$BINDING_STATE"
  elif [[ "$value" == FDAI_MONITOR_WORKSPACE_ID=* && "$sticky" != "1" ]]; then
    printf '%s' "${value#*=}" > "$WORKSPACE_STATE"
  elif [[ "$value" == "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED" ]]; then
    printf '%s\n' remove >> "$UPDATE_CALLS"
    : > "$BINDING_STATE"
  elif [[ "$value" == "FDAI_MONITOR_WORKSPACE_ID" ]]; then
    : > "$WORKSPACE_STATE"
  fi
done
if [[ "$*" == *"--set-env-vars"* || "$*" == *"--remove-env-vars"* ]]; then
  exit 0
fi
exit 91
""",
        encoding="ascii",
    )
    az.chmod(0o755)
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 - resolved Bash runs one repository script.
        [bash, str(_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "BINDING_STATE": str(state),
            "ENABLE_RUNTIME_CALL_EVIDENCE": "true" if desired_enabled else "false",
            "FAIL_UPDATE": "1" if fail_update else "0",
            "MISSING_TARGET": "1" if missing_target else "0",
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "REQUIRE_EXISTING_TARGET": "true" if require_existing else "false",
            "STICKY_UPDATE": "1" if sticky_update else "0",
            "TARGET_CONTAINER_NAME": "inventory",
            "TARGET_JOB_NAME": "ca-fdai-dev-krc-core-inventory",
            "TARGET_RESOURCE_GROUP": "rg-fdai-dev-krc",
            "TARGET_WORKSPACE_NAME": "log-fdai-dev-krc",
            "UPDATE_CALLS": str(calls),
            "WORKSPACE_ID": _WORKSPACE_ID,
            "WORKSPACE_STATE": str(workspace_state),
        },
    )
    return result, state, workspace_state, calls


def test_enables_and_verifies_runtime_call_evidence(tmp_path: Path) -> None:
    result, state, workspace, calls = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert state.read_text(encoding="ascii") == "1"
    assert workspace.read_text(encoding="ascii") == _WORKSPACE_ID
    assert calls.read_text(encoding="ascii").splitlines() == ["enable"]
    assert "effect verified" in result.stdout


def test_enabled_binding_is_a_noop(tmp_path: Path) -> None:
    result, state, workspace, calls = _run(
        tmp_path,
        current_value="1",
        current_workspace=_WORKSPACE_ID,
    )

    assert result.returncode == 0
    assert state.read_text(encoding="ascii") == "1"
    assert workspace.read_text(encoding="ascii") == _WORKSPACE_ID
    assert not calls.exists()


def test_enabled_runtime_flag_adds_missing_workspace_binding(tmp_path: Path) -> None:
    result, state, workspace, calls = _run(tmp_path, current_value="1")

    assert result.returncode == 0, result.stderr
    assert state.read_text(encoding="ascii") == "1"
    assert workspace.read_text(encoding="ascii") == _WORKSPACE_ID
    assert calls.read_text(encoding="ascii").splitlines() == ["enable"]


def test_failed_effect_verification_removes_the_new_binding(tmp_path: Path) -> None:
    result, state, workspace, calls = _run(tmp_path, sticky_update=True)

    assert result.returncode == 1
    assert state.read_text(encoding="ascii") == ""
    assert workspace.read_text(encoding="ascii") == ""
    assert calls.read_text(encoding="ascii").splitlines() == ["enable", "remove"]
    assert "rollback verified" in result.stderr


def test_failed_workspace_effect_preserves_the_existing_runtime_flag(tmp_path: Path) -> None:
    result, state, workspace, calls = _run(
        tmp_path,
        current_value="1",
        sticky_update=True,
    )

    assert result.returncode == 1
    assert state.read_text(encoding="ascii") == "1"
    assert workspace.read_text(encoding="ascii") == ""
    assert calls.read_text(encoding="ascii").splitlines() == ["enable", "enable"]
    assert "rollback verified" in result.stderr


def test_failed_update_removes_and_verifies_the_new_binding(tmp_path: Path) -> None:
    result, state, workspace, calls = _run(tmp_path, fail_update=True)

    assert result.returncode == 9
    assert state.read_text(encoding="ascii") == ""
    assert workspace.read_text(encoding="ascii") == ""
    assert calls.read_text(encoding="ascii").splitlines() == ["enable", "remove"]
    assert "rollback verified" in result.stderr


def test_general_apply_defers_when_target_is_absent(tmp_path: Path) -> None:
    result, _state, _workspace, calls = _run(
        tmp_path,
        missing_target=True,
        require_existing=False,
    )

    assert result.returncode == 0
    assert "does not exist yet" in result.stdout
    assert not calls.exists()


def test_disabled_general_apply_does_not_read_or_mutate_the_target(tmp_path: Path) -> None:
    result, state, workspace, calls = _run(
        tmp_path,
        current_value="",
        missing_target=True,
        require_existing=False,
        desired_enabled=False,
    )

    assert result.returncode == 0
    assert state.read_text(encoding="ascii") == ""
    assert workspace.read_text(encoding="ascii") == ""
    assert "transition is disabled" in result.stdout
    assert not calls.exists()


def test_protected_transition_fails_when_target_is_absent(tmp_path: Path) -> None:
    result, _state, _workspace, calls = _run(tmp_path, missing_target=True)

    assert result.returncode == 1
    assert "target is unavailable" in result.stderr
    assert not calls.exists()
