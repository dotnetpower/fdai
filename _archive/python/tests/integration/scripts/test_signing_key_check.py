"""Signing-key identification contract tests.

The checker must identify a packaged signing root without ever exposing key
material, and must report the custody requirements the kit build enforces.
"""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts/deployment/release/check-signing-key.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_signing_key", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_key(path: Path, key: Ed25519PrivateKey, *, mode: int = 0o600) -> Path:
    path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    path.chmod(mode)
    return path


def test_expected_roots_cover_every_packaged_role() -> None:
    roots = _module().expected_roots()

    assert set(roots) == {"deployment-release", "deployment-bundle", "integrity"}
    assert all(len(value) == 64 for value in roots.values())
    # The development profile pins one signer for both complete-kit roles.
    assert roots["deployment-release"] == roots["deployment-bundle"]
    assert roots["integrity"] != roots["deployment-release"]


def test_package_role_hints_name_the_kit_builder_not_the_retired_wrapper_option() -> None:
    hints = dict(_module()._ROLES)
    builder = _ROOT / "scripts/deployment/release/build-standalone-deployment-kit.sh"
    wrapper = (_ROOT / "scripts/deployment/azure/fdai-up.sh").read_text(encoding="utf-8")

    # fdai-up.sh refuses --signing-key; only the kit builder accepts the package keys.
    assert "--signing-key was removed" in wrapper
    for role in ("deployment-release", "deployment-bundle"):
        assert hints[role].startswith(f"{builder.name} --signing-key")
        assert "fdai-up.sh" not in hints[role]
    builder_text = builder.read_text(encoding="utf-8")
    for option in ("--signing-key)", "--release-key)", "--bundle-key)"):
        assert option in builder_text


def test_integrity_role_is_the_only_license_verification_key() -> None:
    from fdai_deployment_cli import trust_roots

    module = _module()
    integrity = (_ROOT / "security/integrity/upstream-signing-key.pub").read_bytes()

    assert trust_roots.license_public_key_pem() == integrity
    assert module.expected_roots()["integrity"] == module._fingerprint(
        module._public_bytes(integrity)
    )


def test_unrelated_key_is_reported_as_no_match(tmp_path: Path, capsys) -> None:
    module = _module()
    key = _write_key(tmp_path / "other.pem", Ed25519PrivateKey.generate())

    exit_code = module.main(["--key", str(key)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "roles               none" in captured.out
    assert "NO MATCH" in captured.err


def test_no_output_stream_contains_key_material(tmp_path: Path, capsys) -> None:
    module = _module()
    private = Ed25519PrivateKey.generate()
    key = _write_key(tmp_path / "secret.pem", private)
    secret = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode(
        "ascii"
    )
    body = "".join(line for line in secret.splitlines() if "PRIVATE KEY" not in line)

    module.main(["--key", str(key)])
    captured = capsys.readouterr()

    assert body not in captured.out + captured.err
    for line in body.splitlines():
        assert line.strip() == "" or line not in captured.out + captured.err


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o400])
def test_custody_findings_report_a_non_owner_only_mode(tmp_path: Path, mode: int) -> None:
    module = _module()
    key = _write_key(tmp_path / "wide.pem", Ed25519PrivateKey.generate(), mode=mode)

    findings = module.custody_findings(key)

    expected = oct(stat.S_IMODE(os.stat(key).st_mode))[2:]
    assert any(f"mode is {expected}" in finding for finding in findings)


def test_owner_only_mode_has_no_custody_finding(tmp_path: Path) -> None:
    module = _module()
    key = _write_key(tmp_path / "tight.pem", Ed25519PrivateKey.generate())

    assert module.custody_findings(key) == []


def test_a_directory_scan_reports_no_match_for_unrelated_keys(tmp_path: Path, capsys) -> None:
    module = _module()
    (tmp_path / "nested").mkdir()
    _write_key(tmp_path / "nested/unrelated.pem", Ed25519PrivateKey.generate())

    exit_code = module.main(["--scan", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "matches=0" in captured.out
    assert "MATCH " not in captured.out


def test_non_key_files_are_skipped_without_failing(tmp_path: Path, capsys) -> None:
    module = _module()
    (tmp_path / "notes.pem").write_text("this is not a key\n", encoding="ascii")

    exit_code = module.main(["--scan", str(tmp_path)])

    assert exit_code == 1
    assert "scanned=0" in capsys.readouterr().out


def test_a_missing_candidate_is_a_usage_error(tmp_path: Path) -> None:
    assert _module().main(["--key", str(tmp_path / "absent.pem")]) == 2


def test_symlinked_candidates_are_not_scanned(tmp_path: Path, capsys) -> None:
    module = _module()
    real = _write_key(tmp_path / "real.pem", Ed25519PrivateKey.generate())
    (tmp_path / "link.pem").symlink_to(real)

    module.main(["--scan", str(tmp_path)])

    assert "scanned=1" in capsys.readouterr().out
