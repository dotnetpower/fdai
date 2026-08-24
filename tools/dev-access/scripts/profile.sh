#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/infra"
PROFILE_DIR="${FDAI_DEV_ACCESS_PROFILE_DIR:-${ROOT_DIR}/.profiles}"

for command_name in az curl python3 terraform; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    printf 'error: required command is unavailable: %s\n' "${command_name}" >&2
    exit 1
  fi
done

pushd "${INFRA_DIR}" >/dev/null
subscription_id="$(terraform output -raw subscription_id)"
resource_group_name="$(terraform output -raw resource_group_name)"
vpn_gateway_name="$(terraform output -raw vpn_gateway_name)"
dns_resolver_ip="$(terraform output -raw dns_resolver_inbound_ip)"
routing_domains_json="$(terraform output -json fdai_private_dns_routing_domains)"
extra_routing_domains_json="${FDAI_DEV_ACCESS_EXTRA_DNS_DOMAINS_JSON:-[]}"
popd >/dev/null

active_subscription_id="$(az account show --query id --output tsv)"
if [[ "${active_subscription_id}" != "${subscription_id}" ]]; then
  printf 'error: active Azure subscription does not own the dev-access stack\n' >&2
  exit 1
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf -- "${temporary_directory}"' EXIT

profile_url="$(az network vnet-gateway vpn-client generate \
  --resource-group "${resource_group_name}" \
  --name "${vpn_gateway_name}" \
  --processor-architecture Amd64 \
  --subscription "${subscription_id}" \
  --only-show-errors \
  --output tsv)"

curl --fail --location --silent --show-error \
  --proto '=https' \
  --output "${temporary_directory}/vpn-client.zip" \
  "${profile_url}"

profile_path="${temporary_directory}/azurevpnconfig.xml"
python3 - "${temporary_directory}/vpn-client.zip" "${profile_path}" <<'PY'
from pathlib import Path
import sys
from zipfile import ZipFile

archive_path = Path(sys.argv[1])
profile_path = Path(sys.argv[2])
expected_names = {
    "AzureVPN/azurevpnconfig.xml",
    "AzureVPN/azurevpnconfig_aad.xml",
}

with ZipFile(archive_path) as archive:
    profile_entry = next(
        (name for name in archive.namelist() if name.replace("\\", "/") in expected_names),
        None,
    )
    if profile_entry is None:
        raise SystemExit("error: generated package does not contain an Azure VPN Client profile")
    profile_path.write_bytes(archive.read(profile_entry))
PY

if ! grep -Fq "${dns_resolver_ip}" "${profile_path}"; then
  printf 'error: generated profile does not contain the Private DNS Resolver address\n' >&2
  printf 'Regenerate the profile after the VNet DNS server update has converged.\n' >&2
  exit 1
fi

# Constrain the Resolver to FDAI private-service suffixes. Without <dnssuffixes>,
# an Entra Azure VPN Client turns <dnsservers> into a catch-all NRPT rule ('.')
# that also captures public sign-in domains such as login.microsoftonline.com and
# breaks browser authentication. See the Azure VPN Client optional configuration
# guide (DNS suffixes / NRPT).
python3 - "${profile_path}" "${routing_domains_json}" "${extra_routing_domains_json}" <<'PY'
import json
import re
import sys

profile_path = sys.argv[1]
routing_domains = sorted(set(json.loads(sys.argv[2])) | set(json.loads(sys.argv[3])))
if not routing_domains:
    raise SystemExit("error: no private DNS routing domains to constrain the profile")

text = open(profile_path, encoding="utf-8").read()
if "<dnssuffixes>" in text:
    raise SystemExit(0)

entries = "".join(f"      <dnssuffix>.{domain}</dnssuffix>\n" for domain in routing_domains)
block = f"    <dnssuffixes>\n{entries}    </dnssuffixes>\n"
new_text, count = re.subn(r"(</dnsservers>[ \t]*\n)", r"\1" + block, text, count=1)
if count != 1:
    raise SystemExit("error: profile has no <dnsservers> block to anchor DNS suffixes")
open(profile_path, "w", encoding="utf-8").write(new_text)
PY

mkdir -p "${PROFILE_DIR}"
install -m 0600 "${profile_path}" "${PROFILE_DIR}/azurevpnconfig.xml"
printf 'Azure VPN Client profile: %s\n' "${PROFILE_DIR}/azurevpnconfig.xml"
