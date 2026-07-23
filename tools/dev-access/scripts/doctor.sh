#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/infra"

if [[ $# -eq 0 ]]; then
  printf 'usage: %s <private-host> [private-host:port ...]\n' "$0" >&2
  exit 2
fi

if ! grep -qi microsoft /proc/version; then
  printf 'error: this diagnostic expects WSL on Windows\n' >&2
  exit 1
fi

windows_profile="$(cmd.exe /d /c echo %USERPROFILE% 2>/dev/null | tr -d '\r')"
wsl_config="$(wslpath -u "${windows_profile}\\.wslconfig")"
if [[ ! -f "${wsl_config}" ]]; then
  printf 'error: missing Windows WSL configuration: %s\n' "${wsl_config}" >&2
  exit 1
fi

normalized_config="$(tr -d '[:space:]' <"${wsl_config}")"
for required_setting in "networkingMode=mirrored" "dnsTunneling=true"; do
  if [[ "${normalized_config}" != *"${required_setting}"* ]]; then
    printf 'error: .wslconfig is missing %s\n' "${required_setting}" >&2
    exit 1
  fi
done

pushd "${INFRA_DIR}" >/dev/null
dns_resolver_ip="$(terraform output -raw dns_resolver_inbound_ip)"
popd >/dev/null

for target in "$@"; do
  host="${target%%:*}"
  port=""
  if [[ "${target}" == *:* ]]; then
    port="${target##*:}"
  fi

  if [[ ! "${host}" =~ ^[A-Za-z0-9.-]+$ ]] || [[ -n "${port}" && ! "${port}" =~ ^[0-9]+$ ]]; then
    printf 'error: invalid host or port: %s\n' "${target}" >&2
    exit 1
  fi

  resolved_ip="$(getent ahostsv4 "${host}" | awk 'NR == 1 { print $1 }')"
  if [[ -z "${resolved_ip}" ]]; then
    printf 'error: DNS resolution failed for %s\n' "${host}" >&2
    exit 1
  fi

  if command -v dig >/dev/null 2>&1; then
    direct_ip="$(dig +short "@${dns_resolver_ip}" "${host}" A | awk '
      /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ { answer = $0 }
      END { print answer }
    ')"
    if [[ "${direct_ip}" != "${resolved_ip}" ]]; then
      printf 'error: WSL DNS and Private DNS Resolver disagree for %s\n' "${host}" >&2
      printf 'Run tools/dev-access/scripts/wsl-dns.sh apply after connecting the VPN.\n' >&2
      exit 1
    fi
  fi

  ip route get "${resolved_ip}" >/dev/null

  if [[ -n "${port}" ]]; then
    python3 - "${host}" "${port}" <<'PY'
import socket
import sys

with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5):
    pass
PY
  fi

  printf 'ok: %s -> %s\n' "${target}" "${resolved_ip}"
done
