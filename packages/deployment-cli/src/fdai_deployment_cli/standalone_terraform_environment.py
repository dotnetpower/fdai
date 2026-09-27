"""Bind standalone Terraform execution to verified local artifacts and one exact UAMI."""

from __future__ import annotations

import os
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


__all__ = ["configure_terraform", "terraform_configuration"]
