from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DEV_ACCESS = _ROOT / "tools" / "dev-access"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_startup_harness(
    tmp_path: Path,
    *,
    direct_on_call: int,
) -> tuple[subprocess.CompletedProcess[str], list[str], int]:
    dev_access = tmp_path / "tools" / "dev-access"
    scripts = dev_access / "scripts"
    infra = dev_access / "infra"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    infra.mkdir()
    fake_bin.mkdir()
    shutil.copy2(_DEV_ACCESS / "scripts" / "vscode-startup.sh", scripts)
    (infra / "terraform.tfstate").write_text("prepared\n", encoding="utf-8")

    events = tmp_path / "events"
    route_count = tmp_path / "route-count"
    _write_executable(
        fake_bin / "terraform",
        "#!/usr/bin/env bash\nprintf 'resolver-placeholder\\n'\n",
    )
    _write_executable(
        fake_bin / "ip",
        """#!/usr/bin/env bash
set -euo pipefail
count=0
if [[ -f "${FDAI_TEST_ROUTE_COUNT_FILE}" ]]; then
  count="$(cat "${FDAI_TEST_ROUTE_COUNT_FILE}")"
fi
count=$((count + 1))
printf '%s\n' "${count}" > "${FDAI_TEST_ROUTE_COUNT_FILE}"
if (( FDAI_TEST_DIRECT_ON_CALL > 0 && count >= FDAI_TEST_DIRECT_ON_CALL )); then
  printf 'resolver-placeholder dev vpn0 src resolver-placeholder\n'
else
  printf 'resolver-placeholder via gateway-placeholder dev eth0\n'
fi
""",
    )
    _write_executable(
        fake_bin / "powershell.exe",
        "#!/usr/bin/env bash\nprintf 'vpn-open\\n' >> \"${FDAI_TEST_EVENTS}\"\n",
    )
    _write_executable(
        fake_bin / "sleep",
        '#!/usr/bin/env bash\nprintf \'sleep:%s\\n\' "$1" >> "${FDAI_TEST_EVENTS}"\n',
    )
    _write_executable(
        scripts / "wsl-dns.sh",
        '#!/usr/bin/env bash\nprintf \'dns:%s\\n\' "$1" >> "${FDAI_TEST_EVENTS}"\n',
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FDAI_TEST_DIRECT_ON_CALL": str(direct_on_call),
        "FDAI_TEST_EVENTS": str(events),
        "FDAI_TEST_ROUTE_COUNT_FILE": str(route_count),
    }
    bash = shutil.which("bash")
    assert bash is not None
    completed = subprocess.run(  # noqa: S603 - controlled script and command stubs.
        [bash, str(scripts / "vscode-startup.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    recorded_events = events.read_text(encoding="utf-8").splitlines() if events.exists() else []
    calls = int(route_count.read_text(encoding="utf-8"))
    return completed, recorded_events, calls


def test_dev_access_is_an_independent_terraform_root() -> None:
    versions = (_DEV_ACCESS / "infra" / "versions.tf").read_text(encoding="utf-8")
    main = (_DEV_ACCESS / "infra" / "main.tf").read_text(encoding="utf-8")
    production = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'required_version = ">= 1.9"' in versions
    assert 'resource "azurerm_resource_group" "dev_access"' in main
    assert 'resource "azurerm_virtual_network" "dev_access"' in main
    assert 'resource "azurerm_virtual_network_gateway" "dev_access"' in main
    assert 'resource "azurerm_private_dns_resolver" "dev_access"' in main
    assert "dev-access" not in production


def test_dev_access_uses_entra_openvpn_and_private_dns() -> None:
    main = (_DEV_ACCESS / "infra" / "main.tf").read_text(encoding="utf-8")
    outputs = (_DEV_ACCESS / "infra" / "outputs.tf").read_text(encoding="utf-8")

    assert 'name                 = "GatewaySubnet"' in main
    assert 'name    = "Microsoft.Network/dnsResolvers"' in main
    assert 'vpn_client_protocols = ["OpenVPN"]' in main
    assert 'vpn_auth_types       = ["AAD"]' in main
    assert "aad_tenant" in main
    assert "aad_audience" in main
    assert "aad_issuer" in main
    assert 'zones               = ["1", "2", "3"]' in main
    assert 'resource "azurerm_private_dns_resolver_inbound_endpoint" "dev_access"' in main
    assert 'resource "azurerm_virtual_network_dns_servers" "dev_access"' in main
    assert 'resource "azurerm_private_dns_zone_virtual_network_link" "fdai"' in main
    assert '"vaultcore.azure.net"' in outputs
    assert '"vault.azure.net"' in outputs


def test_dev_access_owns_only_removable_fdai_connections() -> None:
    main = (_DEV_ACCESS / "infra" / "main.tf").read_text(encoding="utf-8")

    assert 'resource "azurerm_virtual_network_peering" "dev_access_to_fdai"' in main
    assert 'resource "azurerm_virtual_network_peering" "fdai_to_dev_access"' in main
    assert re.search(r"allow_gateway_transit\s*=\s*true", main)
    assert re.search(r"use_remote_gateways\s*=\s*true", main)
    assert re.search(r"allow_forwarded_traffic\s*=\s*true", main)
    assert "azurerm_virtual_network_gateway.dev_access" in main
    assert "azurerm_role_assignment" not in main
    assert "ignore_changes = [ip_tags]" in main
    assert "ignore_changes = [tags]" in main

    variables = (_DEV_ACCESS / "infra" / "variables.tf").read_text(encoding="utf-8")
    assert 'default     = "VpnGw1AZ"' in variables


def test_dev_access_ships_repeatable_client_checks() -> None:
    profile = (_DEV_ACCESS / "scripts" / "profile.sh").read_text(encoding="utf-8")
    doctor = (_DEV_ACCESS / "scripts" / "doctor.sh").read_text(encoding="utf-8")
    wsl_dns = (_DEV_ACCESS / "scripts" / "wsl-dns.sh").read_text(encoding="utf-8")
    startup = (_DEV_ACCESS / "scripts" / "vscode-startup.sh").read_text(encoding="utf-8")
    tasks = (_ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8")

    assert "az network vnet-gateway vpn-client generate" in profile
    assert "terraform output -raw dns_resolver_inbound_ip" in profile
    assert "terraform output -json fdai_private_dns_routing_domains" in profile
    assert "<dnssuffixes>" in profile
    assert "from zipfile import ZipFile" in profile
    assert "networkingMode=mirrored" in doctor
    assert "dnsTunneling=true" in doctor
    assert "getent ahostsv4" in doctor
    assert "END { print answer }" in doctor
    assert 'ACTION="${1:-apply}"' in wsl_dns
    assert "resolvectl dnsovertls" in wsl_dns
    assert 'resolvectl default-route "${vpn_interface}" no' in wsl_dns
    assert "wsl.exe" in wsl_dns
    assert '"label": "dev-access: configure VPN on folder open"' in tasks
    assert '"command": "bash tools/dev-access/scripts/vscode-startup.sh"' in tasks
    assert '"problemMatcher": "$gcc"' in tasks
    assert '"revealProblems": "onProblem"' in tasks
    assert '"close": true' in tasks
    assert '"runOn": "folderOpen"' in tasks
    assert '"instanceLimit": 1' in tasks
    assert "terraform.tfstate" in startup
    assert "FDAI_DEV_ACCESS_DIRECT_VNET_MARKER" in startup
    assert ".profiles/direct-vnet" in startup
    assert startup.index("DIRECT_VNET_MARKER") < startup.index("terraform.tfstate")
    assert '"${route_line}" != *" via "*' in startup
    assert "ROUTE_RETRY_ATTEMPTS=8" in startup
    assert "ROUTE_RETRY_SECONDS=1" in startup
    assert "README.md:1:1: error:" in startup
    assert startup.index("Microsoft.AzureVpn") < startup.index("ROUTE_RETRY_ATTEMPTS; attempt++")
    assert '"${route_line}" == *" via "*' in wsl_dns
    assert 'wsl-dns.sh" apply' in startup
    assert "Microsoft.AzureVpn" in startup
    assert "exit 20" in startup


def test_folder_open_applies_dns_without_retry_when_route_is_ready(tmp_path: Path) -> None:
    completed, events, route_calls = _run_startup_harness(tmp_path, direct_on_call=1)

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert events == ["dns:apply"]
    assert route_calls == 1


def test_folder_open_recovers_when_vpn_route_appears_during_grace_window(
    tmp_path: Path,
) -> None:
    completed, events, route_calls = _run_startup_harness(tmp_path, direct_on_call=3)

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert events == ["vpn-open", "sleep:1", "dns:apply"]
    assert route_calls == 3


def test_folder_open_bounds_route_retries_before_reporting_disconnect(tmp_path: Path) -> None:
    completed, events, route_calls = _run_startup_harness(tmp_path, direct_on_call=0)

    assert completed.returncode == 20
    assert "FDAI Azure VPN is disconnected" in completed.stderr
    assert events.count("vpn-open") == 1
    assert events.count("sleep:1") == 7
    assert not any(event.startswith("dns:") for event in events)
    assert route_calls == 9
