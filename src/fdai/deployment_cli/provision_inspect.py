"""Read-only execution-profile inspection for operator-initiated provisioning."""

from __future__ import annotations

import json
import shutil
import socket
import ssl
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import httpx

PROVISION_INSPECT_SCHEMA: Final = "fdai.deployment-cli.provision-inspect.v1"
ACCESS_PREFERENCE: Final[tuple[str, ...]] = (
    "internal_ssh",
    "temporary_public_ssh",
    "github_actions",
    "azure_bastion",
    "azure_run_command_emergency",
)
_ONLINE_HOSTS: Final[tuple[str, ...]] = (
    "api.github.com",
    "pypi.org",
    "registry.terraform.io",
)
_IMDS_IDENTITY_URL: Final = (
    "http://169.254.169.254/metadata/identity/oauth2/token"
    "?api-version=2018-02-01&resource=https%3A%2F%2Fmanagement.azure.com%2F"
)


class Connectivity(StrEnum):
    AUTO = "auto"
    ONLINE = "online"
    OFFLINE = "offline"


class ExecutionHost(StrEnum):
    AUTO = "auto"
    EXISTING = "existing-host"
    MANAGED_VM = "managed-vm"


class ExecutionTransport(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    GITHUB_ACTIONS = "github-actions"


@dataclass(frozen=True, slots=True)
class ProvisionInspectCheck:
    check_id: str
    status: str
    summary: str
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class ProvisionInspectResult:
    status: str
    connectivity: Connectivity
    execution_host: ExecutionHost
    transport: ExecutionTransport
    access_method: str | None
    checks: tuple[ProvisionInspectCheck, ...]
    required_human_approvers: int = 1
    require_distinct_executor_identity: bool = True
    managed_vm_lifecycle: str = "persistent_deallocated"
    mutation_performed: bool = False
    schema_version: str = PROVISION_INSPECT_SCHEMA

    @property
    def exit_code(self) -> int:
        return {"ready": 0, "review": 2, "incomplete": 4}[self.status]

    def to_dict(self) -> dict[str, object]:
        return {
            "access_method": self.access_method,
            "access_preference": list(ACCESS_PREFERENCE),
            "checks": [asdict(check) for check in self.checks],
            "connectivity": self.connectivity.value,
            "execution_host": self.execution_host.value,
            "managed_vm_lifecycle": self.managed_vm_lifecycle,
            "mutation_performed": self.mutation_performed,
            "required_human_approvers": self.required_human_approvers,
            "require_distinct_executor_identity": self.require_distinct_executor_identity,
            "schema_version": self.schema_version,
            "status": self.status,
            "transport": self.transport.value,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


ExecutableResolver = Callable[[str], str | None]
AvailabilityProbe = Callable[[], bool]


def inspect_provisioning(
    *,
    connectivity: Connectivity = Connectivity.AUTO,
    execution_host: ExecutionHost = ExecutionHost.AUTO,
    transport: ExecutionTransport = ExecutionTransport.AUTO,
    offline_kit: Path | None = None,
    internal_ssh: bool = False,
    allow_temporary_public_ssh: bool = False,
    bastion: bool = False,
    resolve_executable: ExecutableResolver = shutil.which,
    online_probe: AvailabilityProbe | None = None,
    workload_identity_probe: AvailabilityProbe | None = None,
) -> ProvisionInspectResult:
    """Inspect local provisioning capabilities without changing host or cloud state."""
    tools = {name: resolve_executable(name) is not None for name in ("az", "terraform", "gh")}
    online_available = (online_probe or _probe_online_egress)()
    workload_identity_available = (workload_identity_probe or _probe_workload_identity)()
    offline_kit_available = _offline_kit_candidate_exists(offline_kit)

    selected_connectivity = _select_connectivity(
        requested=connectivity,
        online_available=online_available,
        offline_kit_available=offline_kit_available,
    )
    existing_host_ready = tools["az"] and tools["terraform"] and workload_identity_available
    selected_host = (
        ExecutionHost.EXISTING
        if execution_host is ExecutionHost.AUTO and existing_host_ready
        else ExecutionHost.MANAGED_VM
        if execution_host is ExecutionHost.AUTO
        else execution_host
    )
    access_method = _select_access_method(
        selected_host=selected_host,
        selected_connectivity=selected_connectivity,
        internal_ssh=internal_ssh,
        allow_temporary_public_ssh=allow_temporary_public_ssh,
        github_actions_available=tools["gh"] and online_available,
        bastion=bastion,
        run_command_available=tools["az"],
    )
    selected_transport = _select_transport(
        requested=transport,
        selected_host=selected_host,
        access_method=access_method,
    )
    checks = _checks(
        tools=tools,
        online_available=online_available,
        offline_kit=offline_kit,
        offline_kit_available=offline_kit_available,
        workload_identity_available=workload_identity_available,
    )
    status = _status(
        requested_connectivity=connectivity,
        selected_connectivity=selected_connectivity,
        selected_host=selected_host,
        requested_host=execution_host,
        requested_transport=transport,
        selected_transport=selected_transport,
        access_method=access_method,
        existing_host_ready=existing_host_ready,
        online_available=online_available,
        offline_kit_available=offline_kit_available,
        github_actions_available=tools["gh"] and online_available,
    )
    return ProvisionInspectResult(
        status=status,
        connectivity=selected_connectivity,
        execution_host=selected_host,
        transport=selected_transport,
        access_method=access_method,
        checks=checks,
    )


def _select_connectivity(
    *,
    requested: Connectivity,
    online_available: bool,
    offline_kit_available: bool,
) -> Connectivity:
    if requested is not Connectivity.AUTO:
        return requested
    if online_available:
        return Connectivity.ONLINE
    if offline_kit_available:
        return Connectivity.OFFLINE
    return Connectivity.OFFLINE


def _select_access_method(
    *,
    selected_host: ExecutionHost,
    selected_connectivity: Connectivity,
    internal_ssh: bool,
    allow_temporary_public_ssh: bool,
    github_actions_available: bool,
    bastion: bool,
    run_command_available: bool,
) -> str | None:
    if selected_host is ExecutionHost.EXISTING:
        return "internal_ssh"
    candidates = {
        "internal_ssh": internal_ssh,
        "temporary_public_ssh": allow_temporary_public_ssh,
        "github_actions": (
            selected_connectivity is Connectivity.ONLINE and github_actions_available
        ),
        "azure_bastion": bastion,
        "azure_run_command_emergency": run_command_available,
    }
    return next((method for method in ACCESS_PREFERENCE if candidates[method]), None)


def _select_transport(
    *,
    requested: ExecutionTransport,
    selected_host: ExecutionHost,
    access_method: str | None,
) -> ExecutionTransport:
    if requested is not ExecutionTransport.AUTO:
        return requested
    if access_method == "github_actions":
        return ExecutionTransport.GITHUB_ACTIONS
    if selected_host in {ExecutionHost.EXISTING, ExecutionHost.MANAGED_VM}:
        return ExecutionTransport.MANUAL
    return ExecutionTransport.MANUAL


def _status(
    *,
    requested_connectivity: Connectivity,
    selected_connectivity: Connectivity,
    selected_host: ExecutionHost,
    requested_host: ExecutionHost,
    requested_transport: ExecutionTransport,
    selected_transport: ExecutionTransport,
    access_method: str | None,
    existing_host_ready: bool,
    online_available: bool,
    offline_kit_available: bool,
    github_actions_available: bool,
) -> str:
    if selected_connectivity is Connectivity.ONLINE and not online_available:
        return "incomplete"
    if selected_connectivity is Connectivity.OFFLINE and not offline_kit_available:
        return "incomplete"
    if requested_host is ExecutionHost.EXISTING and not existing_host_ready:
        return "incomplete"
    if selected_host is ExecutionHost.MANAGED_VM and access_method is None:
        return "incomplete"
    if requested_transport is ExecutionTransport.GITHUB_ACTIONS and not github_actions_available:
        return "incomplete"
    if selected_transport is ExecutionTransport.GITHUB_ACTIONS and not github_actions_available:
        return "incomplete"
    if selected_connectivity is Connectivity.OFFLINE:
        return "review"
    if requested_connectivity is Connectivity.AUTO and not online_available:
        return "review"
    if selected_host is ExecutionHost.MANAGED_VM:
        return "review"
    return "ready"


def _checks(
    *,
    tools: dict[str, bool],
    online_available: bool,
    offline_kit: Path | None,
    offline_kit_available: bool,
    workload_identity_available: bool,
) -> tuple[ProvisionInspectCheck, ...]:
    checks = [
        ProvisionInspectCheck(
            check_id=f"tool.{name}",
            status="pass" if available else "fail",
            summary=f"{name} is {'available' if available else 'unavailable'}",
            remediation=None if available else f"Install {name} on the execution host.",
        )
        for name, available in sorted(tools.items())
    ]
    checks.extend(
        (
            ProvisionInspectCheck(
                check_id="connectivity.online-sources",
                status="pass" if online_available else "fail",
                summary=(
                    "Required online artifact sources are reachable"
                    if online_available
                    else "Required online artifact sources are unreachable"
                ),
                remediation=(
                    None
                    if online_available
                    else "Provide a signed offline kit or allow the required TLS egress."
                ),
            ),
            ProvisionInspectCheck(
                check_id="artifact.offline-kit",
                status="candidate" if offline_kit_available else "not-configured",
                summary=(
                    "Offline kit candidate is present and requires signature verification"
                    if offline_kit_available
                    else "Offline kit candidate is not configured"
                ),
                remediation=(
                    None
                    if offline_kit_available
                    else "Set --offline-kit to a signed offline kit directory."
                ),
            ),
            ProvisionInspectCheck(
                check_id="identity.workload",
                status="pass" if workload_identity_available else "fail",
                summary=(
                    "Azure workload identity is available"
                    if workload_identity_available
                    else "Azure workload identity is unavailable"
                ),
                remediation=(
                    None
                    if workload_identity_available
                    else "Use a managed VM or assign a managed identity to the existing host."
                ),
            ),
        )
    )
    if offline_kit is not None and not offline_kit_available:
        checks.append(
            ProvisionInspectCheck(
                check_id="artifact.offline-kit-shape",
                status="fail",
                summary="Offline kit directory is incomplete",
                remediation="Provide offline-kit.json and offline-kit.json.sig.",
            )
        )
    return tuple(checks)


def _offline_kit_candidate_exists(path: Path | None) -> bool:
    if path is None or path.is_symlink() or not path.is_dir():
        return False
    return all((path / name).is_file() for name in ("offline-kit.json", "offline-kit.json.sig"))


def _probe_online_egress() -> bool:
    context = ssl.create_default_context()
    for host in _ONLINE_HOSTS:
        try:
            with socket.create_connection((host, 443), timeout=3.0) as stream:
                with context.wrap_socket(stream, server_hostname=host):
                    continue
        except (OSError, ssl.SSLError):
            return False
    return True


def _probe_workload_identity() -> bool:
    try:
        response = httpx.get(
            _IMDS_IDENTITY_URL,
            headers={"Metadata": "true"},
            timeout=1.0,
            trust_env=False,
        )
    except httpx.HTTPError:
        return False
    return response.status_code == 200


__all__ = [
    "ACCESS_PREFERENCE",
    "PROVISION_INSPECT_SCHEMA",
    "Connectivity",
    "ExecutionHost",
    "ExecutionTransport",
    "ProvisionInspectCheck",
    "ProvisionInspectResult",
    "inspect_provisioning",
]
