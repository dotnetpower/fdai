"""End-to-end capability licensing: issue with a real key, then verify offline.

This repository ships unlicensed, but it MUST still be able to prove the whole
path works: mint a token with a generated Ed25519 key, verify it through the
same code a disconnected deployment runs, and observe the CLI degrade when the
token is tampered with or bound elsewhere.
"""

from __future__ import annotations

import importlib.util
import io
import json
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.deployment_cli.cli import main as cli_main

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "deployment" / "release" / "issue-license.py"
)
_CAPABILITIES = ("cost.metering", "incident.restart")


@pytest.fixture(scope="module")
def issuer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("issue_license", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _private_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_pem(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _issue(issuer: ModuleType, key: Ed25519PrivateKey, **overrides: object) -> str:
    arguments: dict[str, object] = {
        "private_key_pem": _private_pem(key),
        "public_key_pem": _public_pem(key),
        "license_id": "lic-0001",
        "distribution_id": "example-distribution",
        "capability_ids": _CAPABILITIES,
        "valid_days": 365,
    }
    arguments.update(overrides)
    from datetime import UTC, datetime

    arguments.setdefault("not_before", datetime.now(UTC))
    token: str = issuer.issue_license(**arguments)
    return token


def _materialize(tmp_path: Path, token: str, key: Ed25519PrivateKey) -> tuple[Path, Path]:
    token_path = tmp_path / "license.token"
    token_path.write_text(token + "\n", encoding="ascii")
    key_path = tmp_path / "license-public-key.pem"
    key_path.write_bytes(_public_pem(key))
    return token_path, key_path


def _inspect(token_path: Path, key_path: Path, *extra: str) -> tuple[int, dict[str, object]]:
    stdout = io.StringIO()
    code = cli_main(
        [
            "license",
            "inspect",
            "--token",
            str(token_path),
            "--public-key",
            str(key_path),
            "--output",
            "json",
            *extra,
        ],
        stdout=stdout,
    )
    payload: dict[str, object] = json.loads(stdout.getvalue())
    return code, payload


def test_issued_license_is_active_when_inspected(issuer: ModuleType, tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    token_path, key_path = _materialize(tmp_path, _issue(issuer, key), key)

    code, payload = _inspect(token_path, key_path)

    assert code == 0
    assert payload["status"] == "active"
    assert payload["active"] is True
    assert payload["license_id"] == "lic-0001"
    assert payload["mutation_performed"] is False


def test_inspection_never_echoes_the_token(issuer: ModuleType, tmp_path: Path) -> None:
    """A license in a log line is a credential in a log line."""
    key = Ed25519PrivateKey.generate()
    token = _issue(issuer, key)
    token_path, key_path = _materialize(tmp_path, token, key)

    _code, payload = _inspect(token_path, key_path)

    assert token not in json.dumps(payload)


def test_a_tampered_token_degrades_to_read_only(issuer: ModuleType, tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    token = _issue(issuer, key)
    document, signature = token.split(".")
    tampered = f"{document[:-1]}{'A' if document[-1] != 'A' else 'B'}.{signature}"
    token_path, key_path = _materialize(tmp_path, tampered, key)

    code, payload = _inspect(token_path, key_path)

    assert code == 2
    assert payload["status"] in {"untrusted", "expired", "not-yet-valid"}
    assert payload["active"] is False


def test_a_license_from_another_signer_is_untrusted(issuer: ModuleType, tmp_path: Path) -> None:
    signing_key = Ed25519PrivateKey.generate()
    packaged_key = Ed25519PrivateKey.generate()
    token_path, _own_key = _materialize(tmp_path, _issue(issuer, signing_key), signing_key)
    other_key_path = tmp_path / "packaged.pem"
    other_key_path.write_bytes(_public_pem(packaged_key))

    code, payload = _inspect(token_path, other_key_path)

    assert code == 2
    assert payload["status"] == "untrusted"


def test_a_license_bound_to_another_image_is_misbound(issuer: ModuleType, tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    token = _issue(issuer, key, image_digest="a" * 64)
    token_path, key_path = _materialize(tmp_path, token, key)

    code, payload = _inspect(token_path, key_path, "--image-digest", "c" * 64)

    assert code == 2
    assert payload["status"] == "misbound"


def test_issuing_with_a_mismatched_public_key_produces_no_token(
    issuer: ModuleType,
) -> None:
    """A rotated signing key must fail at issue time, not at the customer site."""
    signing_key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()

    with pytest.raises(issuer.LicenseIssueError, match="does not verify"):
        _issue(issuer, signing_key, public_key_pem=_public_pem(other_key))


def test_non_ed25519_signing_key_is_rejected(issuer: ModuleType) -> None:
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

    rsa_pem = generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key = Ed25519PrivateKey.generate()

    with pytest.raises(issuer.LicenseIssueError, match="MUST be Ed25519"):
        _issue(issuer, key, private_key_pem=rsa_pem)


def test_cli_reports_an_unreadable_token_without_claiming_entitlement(tmp_path: Path) -> None:
    missing = tmp_path / "absent.token"
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(_public_pem(Ed25519PrivateKey.generate()))

    code, payload = _inspect(missing, key_path)

    assert code == 4
    assert payload["active"] is False


def _cli_arguments(private_key: Path, public_key: Path, output: Path) -> list[str]:
    return [
        "--private-key",
        str(private_key),
        "--public-key",
        str(public_key),
        "--license-id",
        "lic-0001",
        "--distribution-id",
        "example-distribution",
        "--capability",
        "cost.metering",
        "--output",
        str(output),
    ]


def _key_files(tmp_path: Path) -> tuple[Path, Path]:
    key = Ed25519PrivateKey.generate()
    private_key = tmp_path / "license-key.pem"
    public_key = tmp_path / "license-key.pub"
    private_key.write_bytes(_private_pem(key))
    public_key.write_bytes(_public_pem(key))
    return private_key, public_key


def test_the_issued_token_is_readable_only_by_its_owner(issuer: ModuleType, tmp_path: Path) -> None:
    """A license without an image or deployment binding is a bearer credential.
    The default file mode leaves it readable by every account on the issuing
    host.
    """
    private_key, public_key = _key_files(tmp_path)
    output = tmp_path / "license.token"

    exit_code = issuer.main(_cli_arguments(private_key, public_key, output))

    assert exit_code == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_a_link_at_the_output_path_does_not_place_the_token_elsewhere(
    issuer: ModuleType, tmp_path: Path
) -> None:
    private_key, public_key = _key_files(tmp_path)
    elsewhere = tmp_path / "elsewhere.token"
    output = tmp_path / "license.token"
    output.symlink_to(elsewhere)

    exit_code = issuer.main(_cli_arguments(private_key, public_key, output))

    assert exit_code == 1
    assert not elsewhere.exists()
