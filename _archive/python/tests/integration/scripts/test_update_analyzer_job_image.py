from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/azure/update_analyzer_job_image.sh"
_OLD_IMAGE = f"example.azurecr.io/fdai@sha256:{'a' * 64}"
_NEW_IMAGE = f"example.azurecr.io/fdai@sha256:{'b' * 64}"


def _run(
    tmp_path: Path,
    *,
    current_image: str = _OLD_IMAGE,
    desired_image: str = _NEW_IMAGE,
    fail_desired: bool = False,
    missing_target: bool = False,
    require_existing: bool = True,
    sticky_desired: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    state = tmp_path / "image"
    state.write_text(current_image, encoding="ascii")
    calls = tmp_path / "calls"
    az = tmp_path / "az"
    az.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2 $3" == "containerapp job show" ]]; then
  [[ "${MISSING_TARGET:-0}" != "1" ]] || exit 3
  cat "$IMAGE_STATE"
  exit 0
fi
if [[ "$1 $2 $3" != "containerapp job update" ]]; then
  exit 90
fi
while (( $# )); do
  if [[ "$1" == "--image" ]]; then
    image="$2"
    break
  fi
  shift
done
printf '%s\n' "$image" >> "$UPDATE_CALLS"
if [[ "${FAIL_DESIRED:-0}" == "1" && "$image" == "$DESIRED_IMAGE" ]]; then
  exit 9
fi
if [[ "${STICKY_DESIRED:-0}" != "1" || "$image" != "$DESIRED_IMAGE" ]]; then
  printf '%s' "$image" > "$IMAGE_STATE"
fi
""",
        encoding="ascii",
    )
    az.chmod(0o755)
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 - resolved Bash runs one repository script
        [bash, str(_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DESIRED_IMAGE": desired_image,
            "FAIL_DESIRED": "1" if fail_desired else "0",
            "IMAGE_STATE": str(state),
            "MISSING_TARGET": "1" if missing_target else "0",
            "REQUIRE_EXISTING_TARGET": "true" if require_existing else "false",
            "STICKY_DESIRED": "1" if sticky_desired else "0",
            "TARGET_CONTAINER_NAME": "analyzer-tick",
            "TARGET_JOB_NAME": "ca-fdai-dev-core-analyzer",
            "TARGET_RESOURCE_GROUP": "rg-fdai-dev",
            "UPDATE_CALLS": str(calls),
        },
    )
    return result, state, calls


def test_updates_and_verifies_the_exact_digest(tmp_path: Path) -> None:
    result, state, calls = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert state.read_text(encoding="ascii") == _NEW_IMAGE
    assert calls.read_text(encoding="ascii").splitlines() == [_NEW_IMAGE]
    assert "effect verified" in result.stdout


def test_matching_digest_is_a_noop(tmp_path: Path) -> None:
    result, state, calls = _run(tmp_path, current_image=_NEW_IMAGE)

    assert result.returncode == 0
    assert state.read_text(encoding="ascii") == _NEW_IMAGE
    assert not calls.exists()


def test_failed_effect_verification_rolls_back(tmp_path: Path) -> None:
    result, state, calls = _run(tmp_path, sticky_desired=True)

    assert result.returncode == 1
    assert state.read_text(encoding="ascii") == _OLD_IMAGE
    assert calls.read_text(encoding="ascii").splitlines() == [_NEW_IMAGE, _OLD_IMAGE]
    assert "effect verification failed" in result.stderr
    assert "rollback verified" in result.stderr


def test_failed_update_reasserts_and_verifies_the_previous_digest(tmp_path: Path) -> None:
    result, state, calls = _run(tmp_path, fail_desired=True)

    assert result.returncode == 9
    assert state.read_text(encoding="ascii") == _OLD_IMAGE
    assert calls.read_text(encoding="ascii").splitlines() == [_NEW_IMAGE, _OLD_IMAGE]
    assert "rollback verified" in result.stderr


def test_rejects_unpinned_image_before_reading_target(tmp_path: Path) -> None:
    result, _state, calls = _run(tmp_path, desired_image="example.azurecr.io/fdai:latest")

    assert result.returncode == 2
    assert "pinned by sha256 digest" in result.stderr
    assert not calls.exists()


def test_general_apply_defers_to_declarative_creation_when_target_is_absent(
    tmp_path: Path,
) -> None:
    result, _state, calls = _run(tmp_path, missing_target=True, require_existing=False)

    assert result.returncode == 0
    assert "does not exist yet" in result.stdout
    assert not calls.exists()


def test_first_apply_defers_placeholder_image_when_target_is_absent(tmp_path: Path) -> None:
    result, _state, calls = _run(
        tmp_path,
        desired_image="ghcr.io/example/fdai:unbuilt",
        missing_target=True,
        require_existing=False,
    )

    assert result.returncode == 0
    assert "does not exist yet" in result.stdout
    assert not calls.exists()


def test_protected_update_fails_when_target_is_absent(tmp_path: Path) -> None:
    result, _state, calls = _run(tmp_path, missing_target=True)

    assert result.returncode == 1
    assert "target is unavailable" in result.stderr
    assert not calls.exists()
