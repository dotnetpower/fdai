from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/automation/setup-local-development.sh"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _assignment(name: str) -> str:
    match = re.search(rf'^{re.escape(name)}="([^"]+)"$', _script_text(), re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_setup_script_has_valid_shell_syntax_and_help() -> None:
    subprocess.run(["/usr/bin/bash", "-n", str(SCRIPT)], check=True)  # noqa: S603
    completed = subprocess.run(  # noqa: S603
        ["/usr/bin/bash", str(SCRIPT), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    normalized_help = " ".join(completed.stdout.split())

    assert "--check" in normalized_help
    assert "never signs in to Azure or GitHub" in normalized_help
    assert "never creates tenant-specific configuration" in normalized_help


def test_setup_script_rejects_unknown_options_without_installing() -> None:
    completed = subprocess.run(  # noqa: S603
        ["/usr/bin/bash", str(SCRIPT), "--not-an-option"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "unknown option" in completed.stderr


def test_setup_tool_versions_match_repository_pins() -> None:
    toolchain = json.loads(
        (REPO_ROOT / "infra/genesis-runner-image/toolchain.json").read_text(encoding="utf-8")
    )
    core_dockerfile = (REPO_ROOT / "services/core-control-plane/docker/Dockerfile").read_text(
        encoding="utf-8"
    )
    opa_match = re.search(r"^ARG OPA_VERSION=v([^\s]+)$", core_dockerfile, re.MULTILINE)

    assert opa_match is not None
    assert "opa_version_from_core_image" in _script_text()
    assert _assignment("TERRAFORM_VERSION") == toolchain["terraform_version"]
    assert _assignment("TERRAFORM_LINUX_AMD64_SHA256") == toolchain["terraform_sha256"]
    assert _assignment("AZURE_CLI_VERSION") == toolchain["azure_cli_version"]
    assert _assignment("AZD_VERSION") == "1.34.0"
    assert (
        _assignment("MICROSOFT_KEY_FINGERPRINT") == toolchain["microsoft_package_key_fingerprint"]
    )


def test_setup_script_covers_local_development_prerequisites() -> None:
    script = _script_text()

    for package in (
        "build-essential",
        "docker.io",
        "docker-compose-v2",
        "tesseract-ocr-eng",
        "tesseract-ocr-kor",
    ):
        assert package in script
    for command in (
        "uv sync --python 3.13 --extra dev --frozen",
        "make hooks-install",
        "npm --prefix console ci --no-audit --no-fund",
        "playwright install-deps chromium",
        "playwright install chromium",
        "configure-vscode-profile.py",
        "code --install-extension",
        '--version "$AZD_VERSION"',
        '--install-folder "$USER_BIN"',
        'run_with_docker_access bash "$REPO_ROOT/scripts/deployment/local/dev-up.sh"',
        'check "Local data stack" local_data_stack_healthy',
    ):
        assert command in script
    assert "sudo usermod -aG docker" in script
    assert "FDAI_DOCKER_GROUP_REEXEC" in (
        REPO_ROOT / "scripts/deployment/local/dev-up.sh"
    ).read_text(encoding="utf-8")
    for container in (
        "fdai-postgres",
        "fdai-postgres-validation",
        "fdai-redpanda",
        "fdai-clamav",
    ):
        assert container in script
    assert "az login" not in script
    assert "gh auth login" not in script
