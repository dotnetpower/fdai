from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fdai_deployment_cli import support_install
from fdai_deployment_cli.support_install import _validate_requirements, install_support

_TESTS = str(Path(__file__).parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
test_offline_prepare = importlib.import_module("test_offline_prepare")
_sign_kit = test_offline_prepare._sign_kit

PACKAGES = {
    "fdai-service-contracts",
    "fdai-core-control-plane",
    "fdai-operator-service",
    "fdai-document-ingestion-api",
    "fdai-document-processing-worker",
    "fdai-isolated-executor-service",
}


@pytest.fixture
def support_release(tmp_path):
    kit, key, public = test_offline_prepare.release.__wrapped__(tmp_path)
    root = kit / "support/python"
    (root / "build").mkdir(parents=True)
    (root / "requirements").mkdir()
    records = {}
    lines = []
    for name in sorted(PACKAGES):
        relative = f"build/{name.replace('-', '_')}-1.0-py3-none-any.whl"
        content = b"synthetic unit-test wheel; never executed"
        (root / relative).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        records[name] = {"version": "1.0", "wheel": relative}
        lines.append(f"{name}==1.0 --hash=sha256:{digest}")
    (root / "requirements/support.txt").write_text("\n".join(lines) + "\n")
    inventory = {
        "schema_version": "fdai.runtime-wheelhouse.v1",
        "status": "complete",
        "artifact_kind": "local-runtime-wheelhouse",
        "support_requirements": "requirements/support.txt",
        "packages": records,
        "support_packages": {},
        "files": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*")
            if path.is_file()
        },
    }
    (root / "inventory.json").write_text(json.dumps(inventory))
    _sign_kit(kit, key)
    return kit, key, public


def _install(tmp_path: Path, support_release):
    work = tmp_path / "install"
    work.mkdir(mode=0o700)
    return install_support(
        support_release[0],
        work_dir=work,
        release_root_pem=support_release[2],
        cli_version="0.1.0",
        platform_tag="linux-x86_64",
    )


def test_support_installer_uses_only_authenticated_wheels_and_reads_back_packages(
    tmp_path: Path, support_release, monkeypatch
) -> None:
    calls = []
    monkeypatch.setattr(support_install.shutil, "which", lambda name: "/usr/bin/uv")

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=json.dumps([{"name": name, "version": "1.0"} for name in PACKAGES]).encode(),
        )

    monkeypatch.setattr(support_install.subprocess, "run", run)
    result = _install(tmp_path, support_release)
    assert result["packages"] == dict.fromkeys(PACKAGES, "1.0")
    assert result["services_started"] is False
    assert result["cloud_mutation_performed"] is False
    assert result["subscription_ready"] is False
    assert len(calls) == 4
    assert calls[0][0][1] == "venv"
    install = calls[1][0]
    for option in ("--offline", "--no-cache", "--no-index", "--require-hashes", "--only-binary"):
        assert option in install
    assert calls[2][0][1:3] == ["pip", "check"]
    assert calls[3][0][1:3] == ["pip", "list"]
    for _arguments, options in calls:
        assert options["env"]["UV_OFFLINE"] == "1"
        assert options["env"]["UV_NO_CACHE"] == "1"
        assert options["umask"] == 0o077
        assert options["timeout"] <= 300
    assert (tmp_path / "install/support-installation.json").is_file()


@pytest.mark.parametrize(
    "failure", ["install", "dependency-check", "empty-readback", "wrong-version"]
)
def test_failed_installation_never_publishes_a_receipt(
    tmp_path: Path, support_release, monkeypatch, failure: str
) -> None:
    monkeypatch.setattr(support_install.shutil, "which", lambda name: "/usr/bin/uv")

    def run(arguments, **kwargs):
        if failure == "install" and arguments[1:3] == ["pip", "install"]:
            raise subprocess.CalledProcessError(23, arguments, stderr=b"do not expose tool output")
        if failure == "dependency-check" and arguments[1:3] == ["pip", "check"]:
            raise subprocess.CalledProcessError(1, arguments)
        entries = (
            []
            if failure == "empty-readback"
            else [{"name": name, "version": "2.0"} for name in PACKAGES]
        )
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(entries).encode())

    monkeypatch.setattr(support_install.subprocess, "run", run)
    with pytest.raises(ValueError):
        _install(tmp_path, support_release)
    assert not (tmp_path / "install/support-installation.json").exists()


@pytest.mark.parametrize(
    "content",
    [
        b"-e ./source",
        b"dependency @ https://example.com/dependency.whl",
        b"--index-url https://example.com/simple",
        b"dependency==1.0 --find-links /tmp",
        b"dependency>=1.0",
        b"../dependency.whl",
    ],
)
def test_support_requirements_cannot_escape_the_offline_wheelhouse(content: bytes) -> None:
    with pytest.raises(ValueError):
        _validate_requirements(content)


def test_tampered_support_wheel_never_reaches_uv(
    tmp_path: Path, support_release, monkeypatch
) -> None:
    wheel = next((support_release[0] / "support/python/build").glob("*.whl"))
    wheel.write_bytes(b"tampered")

    def forbidden(*args, **kwargs):
        pytest.fail("unverified support payload must not reach an installer")

    monkeypatch.setattr(support_install.subprocess, "run", forbidden)
    with pytest.raises(ValueError):
        _install(tmp_path, support_release)
