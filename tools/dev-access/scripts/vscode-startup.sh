#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/infra"
DIRECT_VNET_MARKER="${FDAI_DEV_ACCESS_DIRECT_VNET_MARKER:-${ROOT_DIR}/.profiles/direct-vnet}"
ROUTE_RETRY_ATTEMPTS=8
ROUTE_RETRY_SECONDS=1

route_is_direct() {
  route_line="$(ip route get "$1" 2>/dev/null || true)"
  [[ -n "${route_line}" && "${route_line}" != *" via "* ]]
}

# A directly peered Azure VM uses Azure-provided DNS through its own VNet and
# must not open Azure VPN Client. The ignored marker is machine-local and is
# created only after direct peering, private DNS, and endpoint access pass.
if [[ -f "${DIRECT_VNET_MARKER}" ]]; then
  exit 0
fi

# A checkout without local dev-access state has not opted into this workstation
# integration. Keep folder-open quiet for every other FDAI developer.
if [[ ! -s "${INFRA_DIR}/terraform.tfstate" ]]; then
  exit 0
fi

if ! dns_resolver_ip="$(terraform -chdir="${INFRA_DIR}" output -raw dns_resolver_inbound_ip 2>/dev/null)"; then
  printf 'tools/dev-access/README.md:1:1: error: FDAI dev-access state exists but its DNS Resolver output is unavailable\n' >&2
  exit 21
fi

if ! route_is_direct "${dns_resolver_ip}"; then
  # PowerShell expands these variables, not Bash.
  # shellcheck disable=SC2016
  powershell.exe -NoProfile -Command '
    $app = Get-StartApps | Where-Object { $_.AppID -like "Microsoft.AzureVpn*!App" } |
      Select-Object -First 1
    if ($app) {
      Start-Process ("shell:AppsFolder\" + $app.AppID)
    }
  ' >/dev/null 2>&1 || true
  route_ready=false
  for ((attempt = 1; attempt <= ROUTE_RETRY_ATTEMPTS; attempt++)); do
    if route_is_direct "${dns_resolver_ip}"; then
      route_ready=true
      break
    fi
    if (( attempt < ROUTE_RETRY_ATTEMPTS )); then
      sleep "${ROUTE_RETRY_SECONDS}"
    fi
  done
  if [[ "${route_ready}" != true ]]; then
    printf 'tools/dev-access/README.md:1:1: error: FDAI Azure VPN is disconnected after a bounded route check. Azure VPN Client was opened; connect the dev-access profile, then reopen the workspace or run wsl-dns.sh apply.\n' >&2
    exit 20
  fi
fi

"${SCRIPT_DIR}/wsl-dns.sh" apply >/dev/null
