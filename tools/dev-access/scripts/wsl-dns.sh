#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/infra"
ACTION="${1:-apply}"

if [[ "${ACTION}" != "apply" && "${ACTION}" != "revert" && "${ACTION}" != "status" ]]; then
  printf 'usage: %s [apply|revert|status]\n' "$0" >&2
  exit 2
fi

if ! grep -qi microsoft /proc/version || [[ -z "${WSL_DISTRO_NAME:-}" ]]; then
  printf 'error: this helper expects WSL on Windows\n' >&2
  exit 1
fi

pushd "${INFRA_DIR}" >/dev/null
dns_resolver_ip="$(terraform output -raw dns_resolver_inbound_ip)"
popd >/dev/null

route_line="$(ip route get "${dns_resolver_ip}" 2>/dev/null || true)"
if [[ -z "${route_line}" || "${route_line}" == *" via "* ]]; then
  printf 'error: no WSL VPN route to the Private DNS Resolver; connect Azure VPN Client first\n' >&2
  exit 1
fi

vpn_interface="$(printf '%s\n' "${route_line}" | awk '
  NR == 1 {
    for (field_index = 1; field_index <= NF; field_index++) {
      if ($field_index == "dev") {
        print $(field_index + 1)
        exit
      }
    }
  }
')"
if [[ ! "${vpn_interface}" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
  printf 'error: no WSL route to the Private DNS Resolver; connect Azure VPN Client first\n' >&2
  exit 1
fi

case "${ACTION}" in
  apply)
    wsl.exe -d "${WSL_DISTRO_NAME}" -u root -- resolvectl dns "${vpn_interface}" "${dns_resolver_ip}"
    wsl.exe -d "${WSL_DISTRO_NAME}" -u root -- resolvectl domain "${vpn_interface}" '~.'
    wsl.exe -d "${WSL_DISTRO_NAME}" -u root -- resolvectl dnsovertls "${vpn_interface}" no
    wsl.exe -d "${WSL_DISTRO_NAME}" -u root -- resolvectl flush-caches
    ;;
  revert)
    wsl.exe -d "${WSL_DISTRO_NAME}" -u root -- resolvectl revert "${vpn_interface}"
    wsl.exe -d "${WSL_DISTRO_NAME}" -u root -- resolvectl flush-caches
    ;;
esac

resolvectl status "${vpn_interface}"
