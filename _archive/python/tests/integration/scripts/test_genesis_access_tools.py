from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _write_fake_az(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_AZ_CALLS"
case "$1 $2" in
  "config set")
    printf 'no\n' > "$FAKE_DYNAMIC_INSTALL"
    printf 'false\n' > "$FAKE_PREVIEW_INSTALL"
    ;;
  "config get")
    if [[ "$3" == "extension.use_dynamic_install" ]]; then
      cat "$FAKE_DYNAMIC_INSTALL"
    else
      cat "$FAKE_PREVIEW_INSTALL"
    fi
    ;;
  "extension show")
    name=""
    while (($# > 0)); do
      [[ "$1" != "--name" ]] || name="${2:-}"
      shift
    done
    state="$FAKE_EXTENSION_STATE/$name"
    [[ -f "$state" ]] || exit 3
    cat "$state"
    ;;
  "extension add")
    name=""
    version=""
    while (($# > 0)); do
      case "$1" in
        --name) name="${2:-}"; shift 2 ;;
        --version) version="${2:-}"; shift 2 ;;
        *) shift ;;
      esac
    done
    printf '%s\n' "$version" > "$FAKE_EXTENSION_STATE/$name"
    ;;
  "network bastion" | "ssh vm") ;;
  *) exit 9 ;;
esac
""",
        encoding="ascii",
    )
    path.chmod(0o755)


def test_access_tool_preparation_pins_extensions_and_is_idempotent(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    bash = shutil.which("bash")
    assert bash is not None
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_az(fake_bin / "az")
    calls = tmp_path / "calls"
    extension_state = tmp_path / "extensions"
    extension_state.mkdir()
    dynamic_install = tmp_path / "dynamic-install"
    preview_install = tmp_path / "preview-install"
    dynamic_install.write_text("yes_without_prompt\n", encoding="ascii")
    preview_install.write_text("true\n", encoding="ascii")
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_AZ_CALLS": str(calls),
        "FAKE_EXTENSION_STATE": str(extension_state),
        "FAKE_DYNAMIC_INSTALL": str(dynamic_install),
        "FAKE_PREVIEW_INSTALL": str(preview_install),
    }
    command = [bash, "scripts/deployment/azure/prepare-genesis-access-tools.sh"]

    first = subprocess.run(  # noqa: S603 - fixed local interpreter and repository script.
        command,
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(  # noqa: S603 - fixed local interpreter and repository script.
        command,
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == ("ready: bastion=1.4.3 ssh=2.0.9 dynamic-install=no preview=false\n")
    assert "already installed" in second.stderr
    invocations = calls.read_text(encoding="ascii").splitlines()
    assert invocations[0].startswith("config set ")
    assert "extension.dynamic_install_allow_preview=false" in invocations[0]
    assert sum(line.startswith("extension add ") for line in invocations) == 2
    assert any("--name bastion --version 1.4.3" in line for line in invocations)
    assert any("--name ssh --version 2.0.9" in line for line in invocations)
    assert any(line.startswith("network bastion create --help") for line in invocations)
    assert any(line.startswith("network bastion ssh --help") for line in invocations)
    assert any(line.startswith("ssh vm --help") for line in invocations)
    assert dynamic_install.read_text(encoding="ascii") == "no\n"
    assert preview_install.read_text(encoding="ascii") == "false\n"
