"""Workstation preflight: entitlement selection and Azure session before any Azure call."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai_deployment_cli import cli, entitlement_preflight, license_issue


def _public_pem(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _write_key(root: Path, private: Ed25519PrivateKey, *, mode: int = 0o600) -> Path:
    key = root / "secrets" / "integrity-signing-key.pem"
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key.chmod(mode)
    return key


def test_absent_key_selects_the_trial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert entitlement_preflight.select_entitlement_mode() == "trial"


def test_matching_integrity_key_selects_the_key_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = Ed25519PrivateKey.generate()
    _write_key(tmp_path, private)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(license_issue, "license_public_key_pem", lambda: _public_pem(private))

    assert entitlement_preflight.select_entitlement_mode() == "key-holder"


@pytest.mark.parametrize("defect", ["mode", "mismatch", "link"])
def test_present_but_unusable_key_stops_with_a_fixed_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    private = Ed25519PrivateKey.generate()
    key = _write_key(tmp_path, private, mode=0o644 if defect == "mode" else 0o600)
    expected = Ed25519PrivateKey.generate() if defect == "mismatch" else private
    if defect == "link":
        target = key.with_name("target.pem")
        key.rename(target)
        key.symlink_to(target)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(license_issue, "license_public_key_pem", lambda: _public_pem(expected))

    with pytest.raises(ValueError, match="present but unusable") as raised:
        entitlement_preflight.select_entitlement_mode()
    assert "PRIVATE KEY" not in str(raised.value)


def test_unusable_key_stops_the_command_before_any_azure_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_key(tmp_path, Ed25519PrivateKey.generate(), mode=0o644)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli, "select_entitlement_mode", entitlement_preflight.select_entitlement_mode
    )
    monkeypatch.setattr(
        cli,
        "ensure_azure_session",
        lambda **_: pytest.fail("Azure was called before the key check"),
    )
    monkeypatch.setattr(cli, "plan_source_installation", lambda **_: pytest.fail("no deployment"))

    exit_code = cli.main(
        ["provision", "azure", "--source", ".", "--work-dir", str(tmp_path / "work")]
    )

    assert exit_code == 3
    assert "present but unusable" in capsys.readouterr().err


def _fake_azure_cli(directory: Path, *, signed_in: bool) -> Path:
    recorder = directory / "az-calls"
    directory.mkdir(parents=True, exist_ok=True)
    az = directory / "az"
    az.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{recorder}"\n'
        f'if [[ "$1" == account ]]; then exit {0 if signed_in else 1}; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    return recorder


def test_existing_azure_session_needs_no_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _fake_azure_cli(tmp_path / "bin", signed_in=True)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")

    entitlement_preflight.ensure_azure_session()

    assert recorder.read_text(encoding="utf-8").splitlines() == [
        "account show --only-show-errors --output none"
    ]


def test_missing_session_starts_az_login_only_on_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _fake_azure_cli(tmp_path / "bin", signed_in=False)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(ValueError, match="run az login first"):
        entitlement_preflight.ensure_azure_session()
    assert "login" not in recorder.read_text(encoding="utf-8")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    entitlement_preflight.ensure_azure_session()
    assert recorder.read_text(encoding="utf-8").splitlines()[-1] == (
        "login --only-show-errors --output none"
    )
