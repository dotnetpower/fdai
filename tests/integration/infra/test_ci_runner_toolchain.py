"""Contracts that keep every self-hosted CI runner on one declared toolchain."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra" / "ci-runner"
SPEC = importlib.util.spec_from_file_location("ci_runner_verify", INFRA / "verify-toolchain.py")
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)

MANIFEST = json.loads((INFRA / "toolchain.json").read_text(encoding="utf-8"))


def _executable(directory: Path, name: str, output: str, mode: int = 0o755) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\necho '{output}'\n", encoding="utf-8")
    path.chmod(mode)


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "fdai.ci-runner-toolchain.v1",
        "system_tools": ["sh"],
        "pinned_tools": {
            "demo": {"version": "1.2.3", "version_args": ["--version"]},
        },
        "libraries": [],
    }


def test_manifest_covers_the_tools_and_libraries_that_broke_main_ci() -> None:
    assert {"az", "azd", "gh", "terraform", "uv"} <= set(MANIFEST["pinned_tools"])
    assert {"pango-1.0", "pangoft2-1.0"} <= set(MANIFEST["libraries"])
    assert "libpango-1.0-0" in MANIFEST["apt_packages"]
    assert "tzdata" in MANIFEST["apt_packages"]
    assert "tzdata-legacy" in MANIFEST["apt_packages"]
    assert {"Etc/UTC", "America/Buenos_Aires"} <= set(MANIFEST["timezones"])
    assert MANIFEST["pinned_tools"]["terraform"]["sha256"]
    assert len(MANIFEST["pinned_tools"]["az"]["apt_key_fingerprint"]) == 40


def test_cloud_init_provisions_from_the_manifest_before_creating_the_runner() -> None:
    template = (INFRA / "cloud-init.yaml.tftpl").read_text(encoding="utf-8")
    assert "packages:" not in template
    assert "toolchain_manifest" in template
    assert template.index("/opt/fdai-ci/provision-toolchain.sh\n") < template.index("useradd")
    terraform = (INFRA / "main.tf").read_text(encoding="utf-8")
    for name in ("toolchain.json", "verify-toolchain.py", "provision-toolchain.sh"):
        assert f'file("${{path.module}}/{name}")' in terraform


def test_provisioner_is_idempotent_pinned_and_ends_with_verification() -> None:
    source = (INFRA / "provision-toolchain.sh").read_text(encoding="utf-8")
    assert "tool_current" in source
    assert "sha256sum --check --strict" in source
    assert "must run as root" in source
    assert source.index("normalize_ownership\n\nldconfig") > source.index("install_uv\n")
    assert source.rstrip().endswith('python3 "$verifier" --manifest "$manifest"')
    subprocess.run(  # noqa: S603 - syntax check of a tracked script
        ["/usr/bin/bash", "-n", str(INFRA / "provision-toolchain.sh")], check=True
    )


def test_registration_refuses_a_drifted_runner() -> None:
    register = (INFRA / "register.py").read_text(encoding="utf-8")
    assert register.index("verify-toolchain.py") < register.index("fdai-ci-storage")


def test_workflow_verifies_self_hosted_runners_before_the_regression_shard() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["python-tests-ssd"]["steps"]
    names = [step["name"] for step in steps]
    gate = steps[names.index("Verify self-hosted runner toolchain")]
    assert gate["if"] == "runner.environment == 'self-hosted'"
    assert gate["run"] == "python3 infra/ci-runner/verify-toolchain.py"
    assert names.index(gate["name"]) < names.index("Run regression shard")


def test_verifier_accepts_a_conforming_runner(tmp_path: Path) -> None:
    _executable(tmp_path, "sh", "sh")
    _executable(tmp_path, "demo", "demo 1.2.3")
    assert VERIFY.verify(_manifest(), (tmp_path,)) == []


def test_verifier_refuses_missing_timezone_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _executable(tmp_path, "sh", "sh")
    _executable(tmp_path, "demo", "demo 1.2.3")
    manifest = _manifest()
    manifest["timezones"] = ["America/Buenos_Aires"]

    def missing(_name: str) -> None:
        raise VERIFY.ZoneInfoNotFoundError("missing timezone")

    monkeypatch.setattr(VERIFY, "ZoneInfo", missing)
    assert VERIFY.verify(manifest, (tmp_path,)) == ["missing-timezone:America/Buenos_Aires"]


def test_verifier_reports_every_finding_at_once(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["libraries"] = ["fdai-library-that-does-not-exist"]
    _executable(tmp_path, "demo", "demo 9.9.9")
    assert VERIFY.verify(manifest, (tmp_path,)) == [
        "missing-tool:sh",
        "version-drift:demo:expected-1.2.3",
        "missing-library:fdai-library-that-does-not-exist",
    ]


@pytest.mark.parametrize("mode", [0o775, 0o757])
def test_verifier_rejects_a_writable_executable(tmp_path: Path, mode: int) -> None:
    _executable(tmp_path, "sh", "sh")
    _executable(tmp_path, "demo", "demo 1.2.3", mode)
    assert VERIFY.verify(_manifest(), (tmp_path,)) == ["missing-tool:demo"]


def test_main_fails_closed_with_an_actionable_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "toolchain.json"
    broken = _manifest()
    broken["system_tools"] = ["fdai-tool-that-does-not-exist"]
    manifest.write_text(json.dumps(broken), encoding="utf-8")
    assert VERIFY.main(["--manifest", str(manifest)]) == 1
    error = capsys.readouterr().err
    assert "missing-tool:fdai-tool-that-does-not-exist" in error
    assert "provision-toolchain.sh" in error
