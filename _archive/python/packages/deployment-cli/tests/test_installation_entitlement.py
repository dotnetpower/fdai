"""Installation entitlement issuance and offline inspection tests."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli import cli, license_issue
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.license import (
    LicenseInspectionError,
    inspect_installation_entitlement,
    inspect_license,
    signed_token_schema,
)

_INSTALLATION = "1" * 64
_DEPLOYMENT = "2" * 64


def _keys() -> tuple[Ed25519PrivateKey, bytes]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public


def _write_key(path: Path, private: Ed25519PrivateKey) -> Path:
    path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return path


def _issue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, bytes, Ed25519PrivateKey]:
    private, public = _keys()
    monkeypatch.setattr(license_issue, "license_public_key_pem", lambda: public)
    token = license_issue.issue_installation_entitlement(
        private_key=_write_key(tmp_path / "integrity-signing-key.pem", private),
        entitlement_id="ent-test",
        installation_binding=_INSTALLATION,
        deployment_binding=_DEPLOYMENT,
    )
    return token, public, private


def _sign(private: Ed25519PrivateKey, payload: dict[str, object]) -> str:
    document = canonical_bytes(payload)
    return ".".join(
        base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        for value in (document, private.sign(document))
    )


def test_issued_entitlement_has_no_expiry_or_image_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, public, _private = _issue(tmp_path, monkeypatch)

    document = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    result = inspect_installation_entitlement(
        token,
        public_key_pem=public,
        expected_installation_binding=_INSTALLATION,
        expected_deployment_binding=_DEPLOYMENT,
    )

    assert set(document) == {
        "schema_version",
        "entitlement_id",
        "distribution_id",
        "installation_binding",
        "deployment_binding",
        "issued_at",
    }
    assert document["schema_version"] == "fdai.installation-entitlement.v1"
    assert signed_token_schema(token) == "fdai.installation-entitlement.v1"
    inspection = json.loads(result.to_json())
    assert inspection["expires"] is False
    assert inspection["complete_catalog"] is True
    assert _INSTALLATION not in result.to_json()
    assert _DEPLOYMENT not in result.to_json()


@pytest.mark.parametrize(
    ("installation", "deployment", "message"),
    [
        ("3" * 64, _DEPLOYMENT, "installation binding"),
        (_INSTALLATION, "4" * 64, "deployment binding"),
        ("not-a-digest", _DEPLOYMENT, "lowercase SHA-256"),
    ],
)
def test_entitlement_inspection_requires_exact_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    installation: str,
    deployment: str,
    message: str,
) -> None:
    token, public, _private = _issue(tmp_path, monkeypatch)

    with pytest.raises(LicenseInspectionError, match=message):
        inspect_installation_entitlement(
            token,
            public_key_pem=public,
            expected_installation_binding=installation,
            expected_deployment_binding=deployment,
        )


def test_entitlement_and_v1_token_never_verify_as_each_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, public, private = _issue(tmp_path, monkeypatch)
    v1 = _sign(
        private,
        {
            "schema_version": "fdai.license.v1",
            "license_id": "lic-test",
            "distribution_id": "fdai-upstream",
            "capability_ids": ["operations.typed-mutation"],
            "not_before": "2026-10-01T00:00:00Z",
            "not_after": "2026-10-02T00:00:00Z",
            "image_digest": None,
            "tenant_binding": None,
        },
    )
    manifest = _sign(private, {"version": 1, "algorithm": "sha256", "file_count": 0, "files": {}})

    with pytest.raises(LicenseInspectionError, match="schema"):
        inspect_license(token, public_key_pem=public)
    for other in (v1, manifest):
        with pytest.raises(LicenseInspectionError, match="schema"):
            inspect_installation_entitlement(
                other,
                public_key_pem=public,
                expected_installation_binding=_INSTALLATION,
                expected_deployment_binding=_DEPLOYMENT,
            )


def test_entitlement_inspection_rejects_a_foreign_signer_and_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _public, private = _issue(tmp_path, monkeypatch)
    _other, other_public = _keys()
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    extended = _sign(private, {**payload, "not_after": "2036-10-01T00:00:00Z"})

    with pytest.raises(LicenseInspectionError, match="signature"):
        inspect_installation_entitlement(
            token,
            public_key_pem=other_public,
            expected_installation_binding=_INSTALLATION,
            expected_deployment_binding=_DEPLOYMENT,
        )
    with pytest.raises(LicenseInspectionError, match="schema"):
        inspect_installation_entitlement(
            extended,
            public_key_pem=license_issue.license_public_key_pem(),
            expected_installation_binding=_INSTALLATION,
            expected_deployment_binding=_DEPLOYMENT,
        )


def test_cli_inspects_an_entitlement_only_with_both_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    token, public, _private = _issue(tmp_path, monkeypatch)
    token_path = tmp_path / "entitlement.token"
    token_path.write_text(token, encoding="ascii")
    token_path.chmod(0o600)
    public_path = tmp_path / "upstream-signing-key.pub"
    public_path.write_bytes(public)

    def arguments(**bindings: str | None) -> argparse.Namespace:
        return argparse.Namespace(
            token=token_path,
            public_key=public_path,
            image_digest=None,
            tenant_binding=bindings.get("tenant"),
            installation_binding=bindings.get("installation"),
            output="json",
        )

    with pytest.raises(ValueError, match="--installation-binding"):
        cli._license_inspect(arguments(tenant=_DEPLOYMENT))  # noqa: SLF001 - handler under test

    assert cli._license_inspect(arguments(tenant=_DEPLOYMENT, installation=_INSTALLATION)) == 0  # noqa: SLF001
    output = capsys.readouterr().out
    assert json.loads(output)["entitlement_id"] == "ent-test"
    assert token.split(".")[1] not in output
