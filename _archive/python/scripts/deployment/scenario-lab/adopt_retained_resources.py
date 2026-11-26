"""Plan exact Terraform imports for retained scenario-lab compute and data resources.

An interrupted apply or an out-of-band recovery can leave a scenario-lab resource in Azure while
Terraform state no longer records it. The next plan then proposes to create a resource that already
exists, and the protected apply fails. This helper observes only an allowlist of exact resources,
verifies scenario-lab ownership and resource-id shape, and writes Terraform ``import`` blocks. The
reviewed plan therefore shows every adoption before approval, and the approved apply performs it.
The helper never changes Azure or Terraform state itself.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AZ_TIMEOUT_SECONDS = 60
ENVIRONMENT = "lab"
AKS_NAME = "aks-store-demo"
AKS_TYPE = "microsoft.containerservice/managedclusters"
MYSQL_TYPE = "microsoft.dbformysql/flexibleservers"
NIC_TYPE = "microsoft.network/networkinterfaces"
AKS_ADDRESS = "azurerm_kubernetes_cluster.scenario_lab"
MYSQL_ADDRESS = "azurerm_mysql_flexible_server.scenario_lab"
NIC_NSG_ADDRESS = "azurerm_network_interface_security_group_association.stress_vm"
RUNNER_AKS_ROLES = (
    (
        "azurerm_role_assignment.runner_aks_credentials",
        "Azure Kubernetes Service Cluster User Role",
    ),
    (
        "azurerm_role_assignment.runner_aks_admin",
        "Azure Kubernetes Service RBAC Cluster Admin",
    ),
)
OWNERSHIP_TAGS = {
    "fdai:managed": "true",
    "fdai:layer": "scenario-lab",
    "fdai:env": ENVIRONMENT,
    "fdai:workload": "fdai",
}
GUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
GUID = re.compile(rf"^{GUID_PATTERN}$", re.IGNORECASE)
RESOURCE_GROUP = re.compile(r"^[A-Za-z0-9._-]{1,90}$")
REGION_SHORT = re.compile(r"^[a-z0-9]{2,12}$")
MYSQL_ZONE = re.compile(r"^([0-9a-f]{6})\.mysql\.database\.azure\.com$")
SAFE_IMPORT_ID = re.compile(r"^/subscriptions/[A-Za-z0-9/._|-]+$")
ROLE_ASSIGNMENT_SUFFIX = re.compile(
    rf"/providers/microsoft\.authorization/roleassignments/({GUID_PATTERN})$",
    re.IGNORECASE,
)

AzRunner = Callable[[Sequence[str]], Any]


class AdoptionRefusedError(RuntimeError):
    """An observed resource exists but is not the exact scenario-lab resource."""


class AzureObservationError(RuntimeError):
    """A bounded Azure read failed or returned an unexpected shape."""


@dataclass(frozen=True)
class Scope:
    """The exact protected scenario-lab target."""

    subscription_id: str
    resource_group: str
    region_short: str
    runner_principal_id: str

    @property
    def suffix(self) -> str:
        return f"fdai-sre-{ENVIRONMENT}-{self.region_short}"

    def resource_id(self, provider_path: str) -> str:
        return (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"
            f"/providers/{provider_path}"
        )


@dataclass(frozen=True)
class ImportBlock:
    """One Terraform import the reviewed plan must show."""

    address: str
    resource_id: str


@dataclass(frozen=True)
class Observations:
    """Bounded Azure reads for the allowlisted retained resources."""

    resources: Mapping[tuple[str, str], Mapping[str, Any]]
    aks_role_assignments: Sequence[Mapping[str, Any]]
    stress_nic_nsg_id: str | None


def _stress_nic_name(scope: Scope) -> str:
    return f"nic-{scope.suffix}-stress"


def _aks_id(scope: Scope) -> str:
    return scope.resource_id(f"Microsoft.ContainerService/managedClusters/{AKS_NAME}")


def _require_owned(row: Mapping[str, Any], expected_id: str, label: str) -> None:
    observed_id = row.get("id")
    if not isinstance(observed_id, str) or observed_id.lower() != expected_id.lower():
        raise AdoptionRefusedError(
            f"{label} does not resolve to the exact scenario-lab resource id"
        )
    tags = row.get("tags")
    if not isinstance(tags, Mapping):
        raise AdoptionRefusedError(f"{label} has no scenario-lab ownership tags")
    for key, value in OWNERSHIP_TAGS.items():
        if tags.get(key) != value:
            raise AdoptionRefusedError(f"{label} is not owned by the scenario lab ({key})")


def _is_runner_grant(
    assignment: Mapping[str, Any], role_name: str, aks_id: str, principal_id: str
) -> bool:
    return (
        str(assignment.get("principalId", "")).lower() == principal_id.lower()
        and assignment.get("roleDefinitionName") == role_name
        and str(assignment.get("scope", "")).lower() == aks_id.lower()
    )


def _role_assignment_import_id(assignment: Mapping[str, Any], aks_id: str, label: str) -> str:
    if assignment.get("condition"):
        raise AdoptionRefusedError(f"{label} is a conditional role assignment")
    assignment_id = assignment.get("id")
    if not isinstance(assignment_id, str) or not assignment_id.lower().startswith(
        aks_id.lower() + "/providers/"
    ):
        raise AdoptionRefusedError(f"{label} is outside the exact scenario-lab AKS scope")
    match = ROLE_ASSIGNMENT_SUFFIX.search(assignment_id)
    if match is None or match.start() != len(aks_id):
        raise AdoptionRefusedError(f"{label} has an invalid role assignment id")
    return f"{aks_id}/providers/Microsoft.Authorization/roleAssignments/{match.group(1).lower()}"


def plan_imports(
    scope: Scope,
    state_addresses: frozenset[str],
    mysql_suffix: str | None,
    observed: Observations,
) -> list[ImportBlock]:
    """Return exact import blocks for retained resources that state does not record."""

    blocks: list[ImportBlock] = []
    aks_id = _aks_id(scope)
    aks_row = observed.resources.get((AKS_TYPE, AKS_NAME))
    if aks_row is not None and AKS_ADDRESS not in state_addresses:
        _require_owned(aks_row, aks_id, "The retained AKS cluster")
        blocks.append(ImportBlock(AKS_ADDRESS, aks_id))

    if mysql_suffix is not None and MYSQL_ADDRESS not in state_addresses:
        mysql_name = f"mysql-fdai-sre-{mysql_suffix}"
        mysql_row = observed.resources.get((MYSQL_TYPE, mysql_name))
        if mysql_row is not None:
            mysql_id = scope.resource_id(f"Microsoft.DBforMySQL/flexibleServers/{mysql_name}")
            _require_owned(mysql_row, mysql_id, "The retained MySQL server")
            blocks.append(ImportBlock(MYSQL_ADDRESS, mysql_id))

    if aks_row is not None:
        for address, role_name in RUNNER_AKS_ROLES:
            if address in state_addresses:
                continue
            matches = [
                assignment
                for assignment in observed.aks_role_assignments
                if _is_runner_grant(assignment, role_name, aks_id, scope.runner_principal_id)
            ]
            if len(matches) > 1:
                raise AdoptionRefusedError(
                    f"{address} matches more than one retained role assignment"
                )
            if matches:
                import_id = _role_assignment_import_id(matches[0], aks_id, address)
                blocks.append(ImportBlock(address, import_id))

    nic_name = _stress_nic_name(scope)
    nic_row = observed.resources.get((NIC_TYPE, nic_name))
    if (
        nic_row is not None
        and NIC_NSG_ADDRESS not in state_addresses
        and observed.stress_nic_nsg_id is not None
    ):
        nic_id = scope.resource_id(f"Microsoft.Network/networkInterfaces/{nic_name}")
        nsg_id = scope.resource_id(f"Microsoft.Network/networkSecurityGroups/nsg-{scope.suffix}")
        _require_owned(nic_row, nic_id, "The retained stress VM NIC")
        if observed.stress_nic_nsg_id.lower() != nsg_id.lower():
            raise AdoptionRefusedError(
                "The stress VM NIC uses an NSG outside the scenario-lab root"
            )
        blocks.append(ImportBlock(NIC_NSG_ADDRESS, f"{nic_id}|{nsg_id}"))

    for block in blocks:
        if SAFE_IMPORT_ID.fullmatch(block.resource_id) is None:
            raise AdoptionRefusedError(f"{block.address} has an unsafe import id")
    return blocks


def run_az(arguments: Sequence[str]) -> Any:
    """Run one bounded read-only Azure CLI query and parse its JSON output."""

    try:
        completed = subprocess.run(
            ["az", *arguments, "--output", "json", "--only-show-errors"],
            capture_output=True,
            check=False,
            text=True,
            timeout=AZ_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AzureObservationError(f"az {arguments[0]} exceeded its deadline") from exc
    if completed.returncode != 0:
        raise AzureObservationError(f"az {' '.join(arguments[:2])} failed")
    try:
        return json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise AzureObservationError(f"az {' '.join(arguments[:2])} returned invalid JSON") from exc


def observe(az: AzRunner, scope: Scope, state_addresses: frozenset[str]) -> Observations:
    """Read only the allowlisted retained resources from the exact resource group."""

    rows = az(["resource", "list", "--resource-group", scope.resource_group])
    if not isinstance(rows, list):
        raise AzureObservationError("az resource list returned an unexpected shape")
    resources: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        if isinstance(row, Mapping):
            key = (str(row.get("type", "")).lower(), str(row.get("name", "")))
            resources[key] = row

    role_assignments: list[Mapping[str, Any]] = []
    if (AKS_TYPE, AKS_NAME) in resources and any(
        address not in state_addresses for address, _ in RUNNER_AKS_ROLES
    ):
        listed = az(["role", "assignment", "list", "--scope", _aks_id(scope)])
        if not isinstance(listed, list):
            raise AzureObservationError("az role assignment list returned an unexpected shape")
        role_assignments = [item for item in listed if isinstance(item, Mapping)]

    nsg_id: str | None = None
    nic_name = _stress_nic_name(scope)
    if (NIC_TYPE, nic_name) in resources and NIC_NSG_ADDRESS not in state_addresses:
        nic = az(
            [
                "network",
                "nic",
                "show",
                "--ids",
                scope.resource_id(f"Microsoft.Network/networkInterfaces/{nic_name}"),
            ]
        )
        if not isinstance(nic, Mapping):
            raise AzureObservationError("az network nic show returned an unexpected shape")
        association = nic.get("networkSecurityGroup")
        if isinstance(association, Mapping) and isinstance(association.get("id"), str):
            nsg_id = association["id"]
    return Observations(resources, role_assignments, nsg_id)


def render_imports(blocks: Sequence[ImportBlock]) -> str:
    """Render deterministic HCL import blocks for one protected run."""

    lines = ["# Generated by adopt_retained_resources.py for one protected run. Do not commit."]
    for block in blocks:
        lines.extend(
            [
                "",
                "import {",
                f"  to = {block.address}",
                f'  id = "{block.resource_id}"',
                "}",
            ]
        )
    return "\n".join(lines) + "\n"


def _mysql_suffix(zone_name: str) -> str | None:
    if not zone_name:
        return None
    match = MYSQL_ZONE.fullmatch(zone_name)
    if match is None:
        raise AdoptionRefusedError("The recorded MySQL private DNS zone has an unexpected name")
    return match.group(1)


def _scope(args: argparse.Namespace) -> Scope:
    if GUID.fullmatch(args.subscription_id) is None:
        raise ValueError("subscription id must be a GUID")
    if RESOURCE_GROUP.fullmatch(args.resource_group) is None:
        raise ValueError("resource group must use letters, digits, periods, underscores, hyphens")
    if REGION_SHORT.fullmatch(args.region_short) is None:
        raise ValueError("region short name must be 2-12 lowercase letters or digits")
    if GUID.fullmatch(args.runner_principal_id) is None:
        raise ValueError("runner principal id must be a GUID")
    return Scope(
        subscription_id=args.subscription_id.lower(),
        resource_group=args.resource_group,
        region_short=args.region_short,
        runner_principal_id=args.runner_principal_id.lower(),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-addresses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mysql-zone-name", default="")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--region-short", required=True)
    parser.add_argument("--runner-principal-id", required=True)
    return parser


def main(argv: Sequence[str], az: AzRunner = run_az) -> int:
    args = _parser().parse_args(argv)
    try:
        scope = _scope(args)
    except ValueError as exc:
        print(f"adopt_retained_resources: {exc}", file=sys.stderr)
        return 2
    try:
        state_text = args.state_addresses.read_text(encoding="utf-8")
    except OSError:
        print("adopt_retained_resources: the state address list is unreadable", file=sys.stderr)
        return 2
    state_addresses = frozenset(line.strip() for line in state_text.splitlines() if line.strip())
    try:
        mysql_suffix = _mysql_suffix(args.mysql_zone_name.strip())
        blocks = plan_imports(
            scope, state_addresses, mysql_suffix, observe(az, scope, state_addresses)
        )
    except (AdoptionRefusedError, AzureObservationError) as exc:
        print(f"scenario-lab retained-resource adoption refused: {exc}.", file=sys.stderr)
        return 1

    if blocks:
        args.output.write_text(render_imports(blocks), encoding="utf-8")
    else:
        args.output.unlink(missing_ok=True)
    for block in blocks:
        print(f"adopt\t{block.address}")
    print(f"Scenario lab retained-resource adoption: {len(blocks)} import.")
    if args.github_output is not None:
        mysql_name = f"mysql-fdai-sre-{mysql_suffix}" if mysql_suffix else ""
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"import_count={len(blocks)}\n")
            handle.write(f"mysql_server_name={mysql_name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
