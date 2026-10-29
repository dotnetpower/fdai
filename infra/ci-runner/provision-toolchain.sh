#!/usr/bin/env bash
# Idempotently converge a CI runner VM onto infra/ci-runner/toolchain.json.
#
# Run as root from cloud-init on a new VM, or through Azure Run Command on an existing one.
# It installs only manifest-declared packages and checksum- or fingerprint-pinned tools,
# never signs in anywhere, and ends with verify-toolchain.py so a partial result fails closed.
set -euo pipefail

if [[ "$(id -u)" != "0" ]]; then
  echo "provision-toolchain: must run as root" >&2
  exit 1
fi

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
manifest="${1:-$here/toolchain.json}"
verifier="$here/verify-toolchain.py"
export DEBIAN_FRONTEND=noninteractive
export HOME="${HOME:-/root}"

# shellcheck source=/dev/null
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "$(uname -m)" == "x86_64" ]] || {
  echo "provision-toolchain: Ubuntu x86_64 is required" >&2
  exit 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

field() { jq -er "$1" "$manifest"; }

download() {
  curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    --retry-all-errors --connect-timeout 10 --max-time 300 "$1" --output "$2"
}

tool_current() {
  local name="$1" version
  version="$(field ".pinned_tools.${name}.version")"
  [[ -x "/usr/local/bin/$name" || -x "/usr/bin/$name" ]] || return 1
  "$name" "$(field ".pinned_tools.${name}.version_args[0]")" 2>&1 | grep -qF "$version"
}

apt-get update -y
mapfile -t packages < <(field '.apt_packages[]')
apt-get install -y --no-install-recommends "${packages[@]}"

install_azure_cli() {
  local version fingerprint actual
  version="$(field '.pinned_tools.az.version')"
  fingerprint="$(field '.pinned_tools.az.apt_key_fingerprint')"
  tool_current az && return 0
  download https://packages.microsoft.com/keys/microsoft.asc "$work/microsoft.asc"
  actual="$(gpg --show-keys --with-colons "$work/microsoft.asc" | awk -F: '$1 == "fpr" {print $10; exit}')"
  [[ "$actual" == "$fingerprint" ]] || { echo "Microsoft apt key fingerprint mismatch" >&2; exit 1; }
  install -d -m 0755 /etc/apt/keyrings
  gpg --batch --yes --dearmor --output /etc/apt/keyrings/microsoft.gpg "$work/microsoft.asc"
  chmod 0644 /etc/apt/keyrings/microsoft.gpg
  printf 'deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ %s main\n' \
    "$VERSION_CODENAME" > /etc/apt/sources.list.d/azure-cli.list
  apt-get update -y
  apt-get install -y --allow-downgrades "azure-cli=${version}-1~${VERSION_CODENAME}"
}

install_terraform() {
  local version sha archive
  version="$(field '.pinned_tools.terraform.version')"
  sha="$(field '.pinned_tools.terraform.sha256')"
  tool_current terraform && return 0
  archive="terraform_${version}_linux_amd64.zip"
  download "https://releases.hashicorp.com/terraform/${version}/${archive}" "$work/$archive"
  printf '%s  %s\n' "$sha" "$work/$archive" | sha256sum --check --strict
  unzip -o -q "$work/$archive" terraform -d "$work/terraform"
  install -m 0755 "$work/terraform/terraform" /usr/local/bin/terraform
}

install_github_cli() {
  local version archive
  version="$(field '.pinned_tools.gh.version')"
  tool_current gh && return 0
  archive="gh_${version}_linux_amd64.tar.gz"
  download "https://github.com/cli/cli/releases/download/v${version}/${archive}" "$work/$archive"
  download "https://github.com/cli/cli/releases/download/v${version}/gh_${version}_checksums.txt" "$work/gh-checksums.txt"
  (cd "$work" && grep "  ${archive}\$" gh-checksums.txt | sha256sum --check --strict)
  tar -xzf "$work/$archive" -C "$work"
  install -m 0755 "$work/gh_${version}_linux_amd64/bin/gh" /usr/local/bin/gh
}

install_azd() {
  local version
  version="$(field '.pinned_tools.azd.version')"
  tool_current azd && return 0
  download https://aka.ms/install-azd.sh "$work/install-azd.sh"
  bash "$work/install-azd.sh" --version "$version" --install-folder /usr/local/bin
}

install_uv() {
  local version
  version="$(field '.pinned_tools.uv.version')"
  tool_current uv && return 0
  download "https://astral.sh/uv/${version}/install.sh" "$work/install-uv.sh"
  UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh "$work/install-uv.sh"
}

# A previous install can leave a tool owned or writable by another account, which the
# trusted-tool rules reject; converge ownership of every resolved pinned binary.
normalize_ownership() {
  local name target
  for name in $(jq -r '.pinned_tools | keys[]' "$manifest"); do
    target="$(readlink -f "/usr/local/bin/$name" 2>/dev/null || readlink -f "/usr/bin/$name")"
    [[ -f "$target" ]] || continue
    chown root:root "$target"
    chmod go-w "$target"
  done
}

install_azure_cli
install_terraform
install_github_cli
install_azd
install_uv
normalize_ownership

ldconfig
python3 "$verifier" --manifest "$manifest"
