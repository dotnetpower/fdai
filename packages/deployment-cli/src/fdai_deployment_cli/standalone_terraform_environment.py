"""Bind standalone Terraform execution to verified local artifacts and one exact UAMI."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from fdai_deployment_cli.private_output import read_private_bytes

_CONFLICTING_AUTH = (
    "ARM_USE_CLI",
    "ARM_USE_OIDC",
    "ARM_OIDC_TOKEN",
    "ARM_CLIENT_SECRET",
    "ARM_CLIENT_CERTIFICATE_PATH",
    "ARM_CLIENT_CERTIFICATE_PASSWORD",
    "ARM_USERNAME",
    "ARM_PASSWORD",
    "ARM_USE_AKS_WORKLOAD_IDENTITY",
    "ARM_MSI_ENDPOINT",
)
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def configure_terraform(context: dict[str, object]) -> None:
    terraform = Path(str(context["terraform"]))
    provider_mirror = Path(str(context["provider_mirror"]))
    config = Path(str(context["terraform_config"]))
    data = Path(str(context["terraform_data"]))
    if not terraform.is_file() or not config.is_file():
        raise ValueError("verified Terraform execution context is unavailable")
    if read_private_bytes(config, max_bytes=16_384).decode("utf-8") != terraform_configuration(
        provider_mirror
    ):
        raise ValueError("Terraform provider configuration differs from the verified kit")
    data.mkdir(mode=0o700, exist_ok=True)
    kit_bin = Path(str(context.get("kit_bin", terraform.parent)))
    os.environ["PATH"] = os.pathsep.join(
        (str(terraform.parent), str(kit_bin), "/usr/local/bin", "/usr/bin", "/bin")
    )
    os.environ["TF_CLI_CONFIG_FILE"] = str(config)
    os.environ["TF_DATA_DIR"] = str(data)
    os.environ["TF_IN_AUTOMATION"] = "1"
    for variable in _CONFLICTING_AUTH:
        os.environ.pop(variable, None)
    os.environ["ARM_SUBSCRIPTION_ID"] = str(context["subscription_id"])
    os.environ["ARM_TENANT_ID"] = str(context["tenant_id"])
    os.environ["ARM_USE_MSI"] = "true"
    os.environ["ARM_CLIENT_ID"] = str(context["client_id"])
    os.environ["ARM_RESOURCE_PROVIDER_REGISTRATIONS"] = "none"


def terraform_configuration(provider_mirror: Path) -> str:
    return (
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f'    path = "{provider_mirror}"\n'
        '    include = ["*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["*/*"]\n'
        "  }\n"
        "}\n"
    )


def requires_aks_key_vault_private_access(
    *,
    subscription_id: str,
    resource_group_name: str,
    vault_name: str,
    work_dir: Path,
) -> bool:
    """Select only the focused private path required by an existing policy-locked vault."""

    if (
        _GUID.fullmatch(subscription_id) is None
        or re.fullmatch(r"rg-[a-z0-9-]{3,80}", resource_group_name) is None
        or re.fullmatch(r"[a-z0-9-]{3,24}", vault_name) is None
    ):
        raise ValueError("Key Vault private-access readback target is invalid")
    return _requires_private_access(
        subscription_id=subscription_id,
        resource_group_name=resource_group_name,
        resource_name=vault_name,
        list_command=(
            "az",
            "keyvault",
            "list",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group_name,
            "--output",
            "json",
            "--only-show-errors",
        ),
        label="Key Vault",
        work_dir=work_dir,
    )


def requires_aks_document_storage_private_access(
    *,
    subscription_id: str,
    resource_group_name: str,
    account_name: str,
    work_dir: Path,
) -> bool:
    """Select focused Blob/DFS access for one existing policy-locked document account."""

    if (
        _GUID.fullmatch(subscription_id) is None
        or re.fullmatch(r"rg-[a-z0-9-]{3,80}", resource_group_name) is None
        or re.fullmatch(r"[a-z0-9]{3,24}", account_name) is None
    ):
        raise ValueError("document storage private-access readback target is invalid")
    return _requires_private_access(
        subscription_id=subscription_id,
        resource_group_name=resource_group_name,
        resource_name=account_name,
        list_command=(
            "az",
            "storage",
            "account",
            "list",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group_name,
            "--output",
            "json",
            "--only-show-errors",
        ),
        label="document storage",
        work_dir=work_dir,
    )


def _requires_private_access(
    *,
    subscription_id: str,
    resource_group_name: str,
    resource_name: str,
    list_command: tuple[str, ...],
    label: str,
    work_dir: Path,
) -> bool:
    group_exists = _capture(
        (
            "az",
            "group",
            "exists",
            "--subscription",
            subscription_id,
            "--name",
            resource_group_name,
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        reason="application resource-group readback failed",
    )
    if group_exists == "false":
        return False
    if group_exists != "true":
        raise ValueError("application resource-group readback is invalid")
    raw = _capture(list_command, cwd=work_dir, reason=f"{label} public-access readback failed")
    if len(raw.encode()) > 4 * 1024 * 1024:
        raise ValueError(f"{label} public-access readback exceeds its size limit")
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} public-access readback is invalid") from exc
    if not isinstance(rows, list):
        raise ValueError(f"{label} public-access readback is invalid")
    matches = [row for row in rows if isinstance(row, dict) and row.get("name") == resource_name]
    if not matches:
        return False
    if len(matches) != 1:
        raise ValueError(f"{label} public-access readback is ambiguous")
    public_access = matches[0].get("publicNetworkAccess")
    if not isinstance(public_access, str):
        properties = matches[0].get("properties")
        public_access = (
            properties.get("publicNetworkAccess") if isinstance(properties, dict) else None
        )
    if public_access == "Disabled":
        return True
    if public_access == "Enabled":
        return False
    raise ValueError(f"{label} public-access readback is invalid")


def _capture(command: tuple[str, ...], *, cwd: Path, reason: str) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        umask=0o077,
    )
    if result.returncode != 0:
        raise ValueError(reason)
    return result.stdout.strip()


__all__ = [
    "configure_terraform",
    "requires_aks_document_storage_private_access",
    "requires_aks_key_vault_private_access",
    "terraform_configuration",
]
