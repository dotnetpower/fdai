"""Secret-free inputs for planning the ARM-only genesis foundation."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

from fdai_deployment_cli.plan_input import PlanInputContext, read_plan_input, write_plan_input
from fdai_deployment_cli.target import compute_target_binding

_STRINGS = {
    "workload": r"[a-z][a-z0-9]{1,11}",
    "region_short": r"[a-z][a-z0-9]{1,7}",
    "state_storage_account_name": r"[a-z0-9]{3,24}",
    "runner_ssh_public_key": r"ssh-(?:ed25519|rsa) [A-Za-z0-9+/]+={0,2}",
    "source_commit": r"[0-9a-f]{40}",
    "run_digest": r"[0-9a-f]{64}",
    "foundation_context_digest": r"[0-9a-f]{64}",
}
_NETWORKS = ("ops_address_space", "runner_subnet_prefix", "pe_subnet_prefix")
_REQUIRED = (
    frozenset(_STRINGS)
    | frozenset(_NETWORKS)
    | {
        "tenant_id",
        "subscription_id",
        "target_binding",
        "region",
        "runner_source_image_id",
    }
)
_OPTIONAL = frozenset({"state_retention_days", "runner_vm_size", "enable_public_egress"})
_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_SEGMENT = r"[A-Za-z0-9._()-]+"
_IMAGE = re.compile(
    rf"/subscriptions/{_UUID}/resourceGroups/{_SEGMENT}/providers/Microsoft\.Compute/"
    rf"(?:images/{_SEGMENT}|galleries/{_SEGMENT}/images/{_SEGMENT}/versions/[0-9]+\.[0-9]+\.[0-9]+)",
    re.IGNORECASE,
)


def snapshot_foundation_input(
    source: Path,
    destination: Path,
    *,
    expected_target_binding: str,
    expected_region: str,
    expected_environment: str,
) -> PlanInputContext:
    """Snapshot only reviewed foundation inputs; never accept credentials.

    This validates a dry-run input, not image trust, network policy, source
    eligibility, approval, or existing-resource adoption. The protected executor
    must independently bind those before applying a separately sealed plan.
    """

    values = read_plan_input(source)
    if not _REQUIRED <= values.keys() or values.keys() - (_REQUIRED | _OPTIONAL):
        raise ValueError("foundation plan input fields do not match the secret-free schema")
    tenant = values["tenant_id"]
    subscription = values["subscription_id"]
    if (
        not isinstance(tenant, str)
        or not isinstance(subscription, str)
        or not tenant
        or not subscription
    ):
        raise ValueError("foundation plan target values MUST be strings")
    binding = compute_target_binding(tenant_id=tenant, subscription_id=subscription)
    if values["target_binding"] != binding or binding != expected_target_binding:
        raise ValueError("foundation plan target binding does not match the profile")
    if values["region"] != expected_region:
        raise ValueError("foundation plan region does not match the profile")
    if expected_environment not in {"dev", "staging", "prod"}:
        raise ValueError("foundation plan environment is unsupported")
    for name, pattern in _STRINGS.items():
        value = values[name]
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            raise ValueError(f"foundation plan {name} is invalid")
    image = values["runner_source_image_id"]
    if not isinstance(image, str) or _IMAGE.fullmatch(image) is None:
        raise ValueError("foundation plan requires an exact managed image or gallery version")
    _validate_networks(values)
    retention = values.get("state_retention_days", 30)
    if type(retention) is not int or not 1 <= retention <= 365:
        raise ValueError("foundation plan retention MUST be an integer from 1 through 365")
    size = values.get("runner_vm_size", "Standard_D4ds_v5")
    if not isinstance(size, str) or re.fullmatch(r"Standard_[A-Za-z0-9_]{1,64}", size) is None:
        raise ValueError("foundation plan runner size is invalid")
    if type(values.get("enable_public_egress", False)) is not bool:
        raise ValueError("foundation plan public egress selection MUST be boolean")
    terraform_values = {key: value for key, value in values.items() if key != "target_binding"}
    terraform_values["env"] = expected_environment
    write_plan_input(destination, terraform_values)
    return PlanInputContext(subscription_id=subscription, tenant_id=tenant)


def _validate_networks(values: dict[str, object]) -> None:
    networks: list[ipaddress.IPv4Network] = []
    for name in _NETWORKS:
        value = values[name]
        if not isinstance(value, str) or "/" not in value:
            raise ValueError("foundation network prefixes MUST be IPv4 CIDRs")
        try:
            network = ipaddress.IPv4Network(value)
        except ValueError:
            raise ValueError("foundation network prefixes MUST be canonical IPv4 CIDRs") from None
        networks.append(network)
    hub, runner, endpoint = networks
    if not runner.subnet_of(hub) or not endpoint.subnet_of(hub) or runner.overlaps(endpoint):
        raise ValueError("foundation subnets MUST be disjoint and contained in the ops network")
