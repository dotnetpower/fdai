from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/deployment/release/issue-license.py"
sys.path.insert(0, str(PATH.parent))
SPEC = importlib.util.spec_from_file_location("issue_license", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
try:
    SPEC.loader.exec_module(MODULE)
finally:
    sys.path.remove(str(PATH.parent))
read_key_file = MODULE.read_key_file
write_private_text = MODULE._write_private_text


def test_license_output_is_created_private(tmp_path: Path) -> None:
    output = tmp_path / "license.token"

    write_private_text(output, "token\n")

    assert output.read_text(encoding="ascii") == "token\n"
    assert output.stat().st_mode & 0o777 == 0o600


def test_license_output_never_replaces_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "license.token"
    output.write_text("existing\n", encoding="ascii")
    output.chmod(0o644)

    with pytest.raises(FileExistsError):
        write_private_text(output, "token\n")

    assert output.read_text(encoding="ascii") == "existing\n"
    assert output.stat().st_mode & 0o777 == 0o644


def test_license_main_writes_canonical_token_without_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = tmp_path / "private.pem"
    private_key.write_bytes(b"private")
    private_key.chmod(0o600)
    public_key = tmp_path / "public.pem"
    public_key.write_bytes(b"public")
    output = tmp_path / "license.token"
    monkeypatch.setattr(MODULE, "_ISSUER_PRIVATE_KEY", private_key)
    monkeypatch.setattr(MODULE, "issue_license", lambda **_kwargs: "abc.def")

    assert (
        MODULE.main(
            [
                "--public-key",
                str(public_key),
                "--license-id",
                "lic-test",
                "--distribution-id",
                "example-distribution",
                "--capability",
                "cost.metering",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_bytes() == b"abc.def"


def test_release_key_reader_is_private_bounded_no_follow_and_nonblocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifo = tmp_path / "private.pem"
    os.mkfifo(fifo, mode=0o600)
    real_open = os.open

    def open_nonblocking(path: os.PathLike[str], flags: int) -> int:
        assert flags & os.O_NONBLOCK
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", open_nonblocking)
    with pytest.raises(ValueError, match="regular file"):
        read_key_file(fifo, private=True)

    private_key = tmp_path / "key.pem"
    private_key.write_bytes(b"key")
    private_key.chmod(0o644)
    with pytest.raises(PermissionError, match="mode 0600"):
        read_key_file(private_key, private=True)
    private_key.chmod(0o600)
    assert read_key_file(private_key, private=True) == b"key"

    oversized = tmp_path / "oversized.pem"
    oversized.write_bytes(b"x" * 65_537)
    with pytest.raises(ValueError, match="65536"):
        read_key_file(oversized, private=False)

    linked = tmp_path / "linked.pem"
    linked.symlink_to(private_key)
    with pytest.raises(OSError):
        read_key_file(linked, private=False)


def test_issuer_refuses_a_validity_period_longer_than_30_days() -> None:
    with pytest.raises(MODULE.LicenseIssueError, match="between 1 and 30"):
        MODULE.issue_license(
            private_key_pem=b"not-read-after-validity-rejection",
            public_key_pem=b"not-read-after-validity-rejection",
            license_id="lic-test",
            distribution_id="example-distribution",
            capability_ids=("operations.typed-mutation",),
            valid_days=31,
            not_before=datetime(2026, 9, 9, tzinfo=UTC),
        )


def test_all_capabilities_uses_the_30_day_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = tmp_path / "private.pem"
    private_key.write_bytes(b"private")
    private_key.chmod(0o600)
    public_key = tmp_path / "public.pem"
    public_key.write_bytes(b"public")
    output = tmp_path / "license.token"
    captured: dict[str, object] = {}

    def capture_issue(**kwargs: object) -> str:
        captured.update(kwargs)
        return "abc.def"

    monkeypatch.setattr(MODULE, "_ISSUER_PRIVATE_KEY", private_key)
    monkeypatch.setattr(MODULE, "issue_license", capture_issue)

    assert (
        MODULE.main(
            [
                "--public-key",
                str(public_key),
                "--license-id",
                "lic-test",
                "--distribution-id",
                "example-distribution",
                "--all-capabilities",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert captured["valid_days"] == 30
    assert "operations.typed-mutation" in captured["capability_ids"]


def test_full_catalog_token_is_real_and_expires_after_30_days() -> None:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    )
    not_before = datetime(2026, 9, 9, tzinfo=UTC)
    capability_ids = tuple(
        capability.capability_id for capability in MODULE.default_capability_catalog().list()
    )

    token = MODULE.issue_license(
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        license_id="lic-real-test",
        distribution_id="example-distribution",
        capability_ids=capability_ids,
        valid_days=30,
        not_before=not_before,
    )
    claims, document, signature = MODULE.parse_license_token(token)
    private_key.public_key().verify(signature, document)

    assert claims.not_after - claims.not_before == timedelta(days=30)
    assert "operations.typed-mutation" in claims.capability_ids


def test_issuer_reads_only_the_fixed_upstream_integrity_key() -> None:
    assert ROOT / "secrets/integrity-signing-key.pem" == MODULE._ISSUER_PRIVATE_KEY
    with pytest.raises(SystemExit):
        MODULE.main(
            [
                "--private-key",
                "elsewhere.pem",
                "--license-id",
                "lic-test",
                "--distribution-id",
                "example-distribution",
                "--all-capabilities",
            ]
        )
