"""Install a verified capability token or installation entitlement through Key Vault.

The managed host reads the token from standard input, verifies it against the packaged
upstream key and the exact deployment bindings, writes it to the fixed Key Vault
secret, and verifies the stored content again before any runtime consumes it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fdai_deployment_cli import standalone_planned_outputs
from fdai_deployment_cli.license import (
    INSTALLATION_ENTITLEMENT_SCHEMA,
    inspect_installation_entitlement,
    inspect_license,
    signed_token_schema,
)
from fdai_deployment_cli.standalone_host_state import private_json, replace_private_json
from fdai_deployment_cli.standalone_host_values import vault_name
from fdai_deployment_cli.trust_roots import license_public_key_pem

LICENSE_SECRET_NAME = "fdai-capability-license"


def install_license(
    args: argparse.Namespace,
    work_dir: Path,
    *,
    login: Callable[[dict[str, object], Path], None],
) -> dict[str, object]:
    """Store one verified token and record the Container Apps license variables."""

    context = private_json(work_dir / "context.json", "standalone host context")
    login(context, work_dir)
    token = sys.stdin.read(8193)
    if len(token) > 8192 or token != token.strip():
        raise ValueError("license token stdin is invalid")
    _inspect(token, args)
    token_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    infra = Path(str(context["infra"]))
    key_vault = vault_name(_output(infra, "key_vault_uri"))
    result = subprocess.run(
        (
            "az",
            "keyvault",
            "secret",
            "set",
            "--vault-name",
            key_vault,
            "--name",
            LICENSE_SECRET_NAME,
            "--file",
            "/dev/stdin",
            "--encoding",
            "utf-8",
            "--query",
            "id",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        input=token,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    token = ""
    if result.returncode != 0:
        raise ValueError("license token Key Vault installation failed")
    versioned_secret_id = result.stdout.strip()
    match = re.fullmatch(
        rf"https://{re.escape(key_vault)}[.]vault[.]azure[.]net/secrets/"
        rf"{LICENSE_SECRET_NAME}/([0-9a-f]{{32}})",
        versioned_secret_id,
    )
    if match is None:
        raise ValueError("license token Key Vault readback is invalid")
    readback = subprocess.run(
        (
            "az",
            "keyvault",
            "secret",
            "show",
            "--id",
            versioned_secret_id,
            "--query",
            "value",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if readback.returncode != 0:
        raise ValueError("license token Key Vault content readback failed")
    stored = readback.stdout.strip()
    _inspect(stored, args)
    if hashlib.sha256(stored.encode("ascii")).hexdigest() != token_digest:
        raise ValueError("license token Key Vault content differs")
    values = private_json(work_dir / "application.auto.tfvars.json", "application variables")
    values["license"] = {
        "token_secret_id": versioned_secret_id.rsplit("/", 1)[0],
        "image_digest": args.image_digest,
        "deployment_digest": args.deployment_binding,
        "token_revision": hashlib.sha256(
            f"{args.image_digest}:{args.deployment_binding}".encode()
        ).hexdigest(),
    }
    replace_private_json(work_dir / "application.auto.tfvars.json", values)
    return {
        "schema_version": "fdai.standalone-license-installation.v1",
        "state": "installed",
        "secret_metadata_verified": True,
        "secret_content_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }


def aks_license_environment(
    application_values: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return Core's plain and Key Vault-backed license environment once a token is installed."""

    license_values = application_values.get("license")
    if not isinstance(license_values, dict) or not license_values.get("token_secret_id"):
        return {}, {}
    return (
        {
            "FDAI_LICENSE_IMAGE_DIGEST": str(license_values["image_digest"]),
            "FDAI_LICENSE_TOKEN_REVISION": str(license_values["token_revision"]),
        },
        {"FDAI_LICENSE_TOKEN": LICENSE_SECRET_NAME},
    )


def _inspect(token: str, args: argparse.Namespace) -> None:
    if signed_token_schema(token) == INSTALLATION_ENTITLEMENT_SCHEMA:
        installation_binding = getattr(args, "installation_binding", None)
        if not installation_binding:
            raise ValueError("an installation entitlement requires its installation binding")
        inspect_installation_entitlement(
            token,
            public_key_pem=license_public_key_pem(),
            expected_installation_binding=installation_binding,
            expected_deployment_binding=args.deployment_binding,
        )
        return
    inspect_license(
        token,
        public_key_pem=license_public_key_pem(),
        expected_image_digest=args.image_digest,
        expected_tenant_binding=args.deployment_binding,
    )


def _output(infra: Path, name: str) -> str:
    value = standalone_planned_outputs.read_output(
        infra, name, raw=True, reason="Terraform output readback failed"
    )
    return str(value)


__all__ = ["LICENSE_SECRET_NAME", "aks_license_environment", "install_license"]
