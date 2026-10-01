"""Key-holder entitlement issuance and license installation during deployment."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli import license_issue, standalone_host
from fdai_deployment_cli import standalone_license_installation as installation
from fdai_deployment_cli.license import signed_token_schema

_INSTALLATION = "1" * 64
_DEPLOYMENT = "2" * 64
_IMAGE = "3" * 64
_VAULT_URI = "https://kv-fdai-dev.vault.azure.net/"
_SECRET_ID = "https://kv-fdai-dev.vault.azure.net/secrets/fdai-capability-license"


@pytest.fixture
def issuer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    key = tmp_path / "integrity-signing-key.pem"
    key.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key.chmod(0o600)
    for module in (license_issue, installation):
        monkeypatch.setattr(module, "license_public_key_pem", lambda: public)
    monkeypatch.setattr(license_issue, "discover_license_signing_key", lambda: key)
    return key


def _token(**bindings: str | None) -> str | None:
    return license_issue.deployment_license_token(
        trial_token=None,
        image_digest=_IMAGE,
        deployment_binding=_DEPLOYMENT,
        work_ref="deployment",
        **bindings,
    )


def test_a_key_holder_on_aks_receives_the_installation_entitlement(issuer: Path) -> None:
    token = _token(installation_binding=_INSTALLATION)

    assert token is not None
    assert signed_token_schema(token) == "fdai.installation-entitlement.v1"


def test_a_key_holder_without_an_installation_binding_keeps_the_v1_token(issuer: Path) -> None:
    token = _token()

    assert token is not None
    assert signed_token_schema(token) == "fdai.license.v1"


class _Vault:
    """Fake `az keyvault secret set/show` that stores one secret version."""

    def __init__(self) -> None:
        self.stored = ""

    def run(self, command: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[:4] == ("az", "keyvault", "secret", "set"):
            self.stored = kwargs["input"]
            return subprocess.CompletedProcess(command, 0, stdout=f"{_SECRET_ID}/{'a' * 32}\n")
        if command[:4] == ("az", "keyvault", "secret", "show"):
            return subprocess.CompletedProcess(command, 0, stdout=f"{self.stored}\n")
        raise AssertionError(f"unexpected command: {command}")


def _install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    token: str,
    installation_binding: str | None,
) -> tuple[dict[str, object], dict[str, Any]]:
    (tmp_path / "context.json").write_text(json.dumps({"infra": str(tmp_path / "infra")}))
    (tmp_path / "application.auto.tfvars.json").write_text("{}")
    vault = _Vault()
    monkeypatch.setattr(installation.subprocess, "run", vault.run)
    monkeypatch.setattr(
        installation, "private_json", lambda path, _label: json.loads(path.read_text())
    )
    monkeypatch.setattr(
        installation, "replace_private_json", lambda path, value: path.write_text(json.dumps(value))
    )
    monkeypatch.setattr(
        installation.standalone_planned_outputs, "read_output", lambda *_args, **_kwargs: _VAULT_URI
    )
    monkeypatch.setattr(installation.sys, "stdin", io.StringIO(token))
    args = argparse.Namespace(
        image_digest=_IMAGE,
        deployment_binding=_DEPLOYMENT,
        installation_binding=installation_binding,
    )
    receipt = installation.install_license(args, tmp_path, login=lambda *_: None)
    return receipt, json.loads((tmp_path / "application.auto.tfvars.json").read_text())


def test_the_host_installs_and_reads_back_an_exactly_bound_entitlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, issuer: Path
) -> None:
    token = _token(installation_binding=_INSTALLATION)
    assert token is not None

    receipt, values = _install(tmp_path, monkeypatch, token, _INSTALLATION)

    assert receipt["secret_content_verified"] is True
    assert values["license"]["token_secret_id"] == _SECRET_ID
    assert values["license"]["deployment_digest"] == _DEPLOYMENT
    assert token not in json.dumps(receipt)


def test_the_host_refuses_an_entitlement_without_its_installation_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, issuer: Path
) -> None:
    token = _token(installation_binding=_INSTALLATION)
    assert token is not None

    with pytest.raises(ValueError, match="installation binding"):
        _install(tmp_path, monkeypatch, token, None)


def test_the_host_refuses_an_entitlement_for_another_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, issuer: Path
) -> None:
    token = _token(installation_binding=_INSTALLATION)
    assert token is not None

    with pytest.raises(ValueError, match="installation binding does not match"):
        _install(tmp_path, monkeypatch, token, "9" * 64)


def test_aks_core_mounts_an_installed_token_only_once_installed() -> None:
    assert installation.aks_license_environment({}) == ({}, {})

    environment, secrets = installation.aks_license_environment(
        {
            "license": {
                "token_secret_id": _SECRET_ID,
                "image_digest": _IMAGE,
                "deployment_digest": _DEPLOYMENT,
                "token_revision": "4" * 64,
            }
        }
    )

    assert environment == {
        "FDAI_LICENSE_IMAGE_DIGEST": _IMAGE,
        "FDAI_LICENSE_TOKEN_REVISION": "4" * 64,
    }
    assert secrets == {"FDAI_LICENSE_TOKEN": "fdai-capability-license"}


def test_the_binding_step_reports_the_installation_binding_before_runtime_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "substrate-receipt.json").write_text("{}")
    context = {
        "infra": str(tmp_path / "infra"),
        "runtime_infra": str(tmp_path / "runtime"),
        "runtime_profile": {"runtime_platform": "aks", "database_placement": "postgres-flex"},
        "tenant_id": "tenant",
        "subscription_id": "subscription",
    }
    reads: list[str] = []
    stages: list[str] = []

    def output(_infra: Path, name: str) -> str:
        reads.append(name)
        return {"installation_binding": _INSTALLATION, "cluster_name": "aks-fdai-dev"}[name]

    monkeypatch.setattr(standalone_host, "_private_json", lambda *_args: context)
    monkeypatch.setattr(standalone_host, "_managed_identity_login_from_context", lambda *_: None)
    monkeypatch.setattr(
        standalone_host, "_activate_terraform_stage", lambda stage, *_: stages.append(stage)
    )
    monkeypatch.setattr(standalone_host, "_terraform_output", output)

    receipt = standalone_host._deployment_binding(argparse.Namespace(), tmp_path)

    assert receipt["installation_binding"] == _INSTALLATION
    assert reads == ["installation_binding", "cluster_name"]
    assert stages == ["runtime"]
