"""Exercise Genesis child launch from a bundle-shaped tree without a source project."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest
from tests.integration.scripts.test_standalone_kit_release_guards import ROOT, executable


@pytest.mark.parametrize(
    "script_name",
    [
        "genesis-foundation-apply.sh",
        "genesis-foundation-state.sh",
        "genesis-runner-image.sh",
        "genesis-runner-enrollment.sh",
    ],
)
def test_private_child_uses_selected_python_without_a_bundle_checkout(
    tmp_path, monkeypatch, script_name
):
    source = ROOT / "scripts/deployment/azure"
    monkeypatch.syspath_prepend(str(source))
    from genesis_private_command import PrivateCommandContext, PrivateCommandExecutor

    bundle = tmp_path / "bundle"
    scripts = bundle / "scripts/deployment/azure"
    scripts.mkdir(parents=True)
    for path in source.iterdir():
        if path.suffix in {".py", ".sh"} and path.is_file():
            shutil.copyfile(path, scripts / path.name)
    tools = tmp_path / "tools"
    executable(tools / "uv", "echo unexpected-checkout-launch >&2\nexit 65\n")
    calls = []
    monkeypatch.setenv("FDAI_GENESIS_PYTHON", "/untrusted/inherited-python")

    def record(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "{}", "")

    executor = PrivateCommandExecutor(
        PrivateCommandContext(bundle, "synthetic-subscription", "synthetic-tenant"),
        run_child=record,
    )
    executor.run_json(script_name, ("--help",), stage="test", reason="test", timeout=10)
    command, options = calls[0]
    assert options["env"]["FDAI_GENESIS_PYTHON"] == sys.executable
    result = subprocess.run(  # noqa: S603 - captured real launcher with help-only arguments.
        command,
        **{
            **options,
            "text": True,
            "env": {
                **options["env"],
                "PATH": f"{tools}:{os.environ['PATH']}",
                "PYTHONPATH": str(ROOT / "packages/deployment-cli/src"),
                "UV_OFFLINE": "1",
                "UV_PYTHON_DOWNLOADS": "never",
            },
        },
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert "unexpected-checkout-launch" not in result.stderr
    assert not (bundle / ".venv").exists()
    assert not (bundle / "packages").exists()


@pytest.mark.parametrize("command", ["plan", "verify-foundation-plan"])
def test_planning_cli_module_needs_no_checkout_project(tmp_path, command):
    result = subprocess.run(  # noqa: S603 - CLI help only; no plan, Azure, or installation.
        [sys.executable, "-m", "fdai_deployment_cli", "provision", command, "--help"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "packages/deployment-cli/src"),
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert not list(tmp_path.iterdir())
