#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/infra"

# A checkout without local dev-access state has not opted into this workstation
# integration. Keep folder-open quiet for every other FDAI developer.
if [[ ! -s "${INFRA_DIR}/terraform.tfstate" ]]; then
  exit 0
fi

if ! dns_resolver_ip="$(terraform -chdir="${INFRA_DIR}" output -raw dns_resolver_inbound_ip 2>/dev/null)"; then
  printf 'error: FDAI dev-access state exists but its DNS Resolver output is unavailable\n' >&2
  exit 21
fi

route_line="$(ip route get "${dns_resolver_ip}" 2>/dev/null || true)"
if [[ -z "${route_line}" || "${route_line}" == *" via "* ]]; then
  powershell.exe -NoProfile -Command '
    $app = Get-StartApps | Where-Object { $_.AppID -like "Microsoft.AzureVpn*!App" } |
      Select-Object -First 1
    if ($app) {
      Start-Process ("shell:AppsFolder\" + $app.AppID)
    }
  ' >/dev/null 2>&1 || true
  printf 'error: FDAI Azure VPN is disconnected. Azure VPN Client was opened; connect the dev-access profile, then reopen the workspace or run wsl-dns.sh apply.\n' >&2
  exit 20
fi

"${SCRIPT_DIR}/wsl-dns.sh" apply >/dev/null
