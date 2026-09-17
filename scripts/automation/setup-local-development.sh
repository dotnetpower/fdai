#!/usr/bin/env bash
set -euo pipefail

# Install and verify the host toolchain used by FDAI local development.

UV_VERSION="0.11.32"
NODE_VERSION="22.23.1"
TERRAFORM_VERSION="1.9.8"
TERRAFORM_LINUX_AMD64_SHA256="186e0145f5e5f2eb97cbd785bc78f21bae4ef15119349f6ad4fa535b83b10df8"
GH_VERSION="2.100.0"
AZURE_CLI_VERSION="2.88.0"
AZD_VERSION="1.34.0"
MICROSOFT_KEY_FINGERPRINT="BC528686B50D79E339D3721CEB3E94ADBE1229CF"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
USER_BIN="$HOME/.local/bin"
USER_OPT="$HOME/.local/opt"
CHECK_ONLY=0
SKIP_VSCODE=0
TEMP_DIR=""

usage() {
  cat <<'EOF'
Usage: scripts/automation/setup-local-development.sh [options]

Options:
  --check         Verify the development environment without changing it.
  --skip-vscode   Skip VS Code machine settings and extension installation.
  -h, --help      Show this help.

The installer supports x86_64 Ubuntu and Ubuntu on WSL. It prompts for sudo
through the terminal when system packages are missing. It never signs in to
Azure or GitHub and never creates tenant-specific configuration.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --skip-vscode) SKIP_VSCODE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ ! -f "$REPO_ROOT/pyproject.toml" || ! -f "$REPO_ROOT/uv.lock" ]]; then
  printf 'cannot locate the FDAI repository root\n' >&2
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  printf 'cannot identify the host operating system\n' >&2
  exit 1
fi

# shellcheck source=/dev/null
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  printf 'unsupported operating system: %s (Ubuntu is required)\n' "${ID:-unknown}" >&2
  exit 1
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  printf 'unsupported architecture: %s (x86_64 is required)\n' "$(uname -m)" >&2
  exit 1
fi
NODE_ARCH="x64"
TERRAFORM_ARCH="amd64"
OPA_ARCH="amd64"
GH_ARCH="amd64"
IS_WSL=0
if grep -qi microsoft /proc/version; then
  IS_WSL=1
fi

export PATH="$USER_BIN:$PATH"

download() {
  local url="$1"
  local destination="$2"
  curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    --retry-all-errors --retry-max-time 180 --connect-timeout 10 --max-time 180 \
    "$url" --output "$destination"
}

require_version() {
  local label="$1"
  local actual="$2"
  local expected="$3"
  if [[ "$actual" != "$expected" ]]; then
    printf '%s version mismatch: expected %s, found %s\n' "$label" "$expected" "$actual" >&2
    return 1
  fi
  printf 'ok %-20s %s\n' "$label" "$actual"
}

run_with_docker_access() {
  local command

  if docker info >/dev/null 2>&1; then
    "$@"
    return
  fi
  if getent group docker | awk -F: '{print $4}' | tr ',' '\n' | grep -Fxq "$USER"; then
    printf -v command '%q ' "$@"
    sg docker -c "$command"
    return
  fi
  return 1
}

docker_info() {
  run_with_docker_access docker info >/dev/null
}

local_data_stack_healthy() {
  local container
  local health

  for container in fdai-postgres fdai-postgres-validation fdai-redpanda fdai-clamav; do
    health="$(
      run_with_docker_access docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$container" 2>/dev/null
    )" || return 1
    [[ "$health" == "healthy" ]] || return 1
  done
}

opa_version_from_core_image() {
  sed -n 's/^ARG OPA_VERSION=v\{0,1\}\([^[:space:]]*\)$/\1/p' \
    "$REPO_ROOT/services/core-control-plane/docker/Dockerfile" | head -n 1
}

install_system_packages() {
  sudo apt-get update
  sudo apt-get install -y \
    build-essential ca-certificates curl git gnupg ripgrep shellcheck \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor \
    docker.io docker-compose-v2
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER"
}

install_microsoft_package_source() {
  local key="$TEMP_DIR/microsoft.asc"
  local keyring="$TEMP_DIR/microsoft.gpg"
  local fingerprint

  download "https://packages.microsoft.com/keys/microsoft.asc" "$key"
  fingerprint="$(gpg --show-keys --with-colons "$key" | awk -F: '$1 == "fpr" {print $10; exit}')"
  require_version "Microsoft key" "$fingerprint" "$MICROSOFT_KEY_FINGERPRINT"
  gpg --batch --yes --dearmor --output "$keyring" "$key"
  sudo install -m 0644 "$keyring" /etc/apt/keyrings/microsoft.gpg
  printf '%s\n' \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ ${VERSION_CODENAME} main" \
    | sudo tee /etc/apt/sources.list.d/azure-cli.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y --allow-downgrades \
    "azure-cli=${AZURE_CLI_VERSION}-1~${VERSION_CODENAME}"
}

install_uv_and_python() {
  download "https://astral.sh/uv/${UV_VERSION}/install.sh" "$TEMP_DIR/install-uv.sh"
  UV_INSTALL_DIR="$USER_BIN" sh "$TEMP_DIR/install-uv.sh"
  uv python install 3.13
}

install_node() {
  local archive="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
  local install_dir="$USER_OPT/node-v${NODE_VERSION}-linux-${NODE_ARCH}"

  download "https://nodejs.org/dist/v${NODE_VERSION}/${archive}" "$TEMP_DIR/$archive"
  download "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" "$TEMP_DIR/node-shasums.txt"
  (cd "$TEMP_DIR" && grep "  ${archive}$" node-shasums.txt | sha256sum --check --strict)
  rm -rf "$install_dir"
  tar -xJf "$TEMP_DIR/$archive" -C "$USER_OPT"
  ln -sfn "$install_dir" "$USER_OPT/node"
  for executable in node npm npx corepack; do
    ln -sfn "$USER_OPT/node/bin/$executable" "$USER_BIN/$executable"
  done
}

install_opa() {
  local version
  local binary="$TEMP_DIR/opa"
  local checksum="$TEMP_DIR/opa.sha256"

  version="$(opa_version_from_core_image)"
  [[ -n "$version" ]] || { printf 'cannot resolve OPA_VERSION from the Core image\n' >&2; exit 1; }
  download "https://openpolicyagent.org/downloads/v${version}/opa_linux_${OPA_ARCH}_static" "$binary"
  download "https://openpolicyagent.org/downloads/v${version}/opa_linux_${OPA_ARCH}_static.sha256" "$checksum"
  printf '%s  %s\n' "$(awk '{print $1}' "$checksum")" "$binary" | sha256sum --check --strict
  install -m 0755 "$binary" "$USER_BIN/opa"
}

install_terraform() {
  local archive="terraform_${TERRAFORM_VERSION}_linux_${TERRAFORM_ARCH}.zip"
  local expected_sha

  if [[ "$TERRAFORM_ARCH" != "amd64" ]]; then
    printf 'Terraform installation is checksum-pinned only for linux_amd64\n' >&2
    exit 1
  fi
  expected_sha="$TERRAFORM_LINUX_AMD64_SHA256"
  download "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/${archive}" "$TEMP_DIR/$archive"
  printf '%s  %s\n' "$expected_sha" "$TEMP_DIR/$archive" | sha256sum --check --strict
  mkdir -p "$TEMP_DIR/terraform"
  python3 -m zipfile -e "$TEMP_DIR/$archive" "$TEMP_DIR/terraform"
  install -m 0755 "$TEMP_DIR/terraform/terraform" "$USER_BIN/terraform"
}

install_github_cli() {
  local archive="gh_${GH_VERSION}_linux_${GH_ARCH}.tar.gz"
  local install_dir="$TEMP_DIR/gh_${GH_VERSION}_linux_${GH_ARCH}"

  download "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${archive}" "$TEMP_DIR/$archive"
  download "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" "$TEMP_DIR/gh-checksums.txt"
  (cd "$TEMP_DIR" && grep "  ${archive}$" gh-checksums.txt | sha256sum --check --strict)
  tar -xzf "$TEMP_DIR/$archive" -C "$TEMP_DIR"
  install -m 0755 "$install_dir/bin/gh" "$USER_BIN/gh"
}

install_azd() {
  download "https://aka.ms/install-azd.sh" "$TEMP_DIR/install-azd.sh"
  bash "$TEMP_DIR/install-azd.sh" \
    --version "$AZD_VERSION" \
    --install-folder "$USER_BIN"
}

install_project_dependencies() {
  cd "$REPO_ROOT"
  uv sync --python 3.13 --extra dev --frozen
  make hooks-install
  npm --prefix console ci --no-audit --no-fund
  npm --prefix console exec playwright install-deps chromium
  npm --prefix console exec playwright install chromium
}

start_local_data_stack() {
  run_with_docker_access bash "$REPO_ROOT/scripts/deployment/local/dev-up.sh"
}

configure_vscode() {
  local extension

  if ! command -v code >/dev/null 2>&1; then
    printf 'skip VS Code configuration: code CLI is not available\n'
    return
  fi
  if (( IS_WSL )); then
    python3 "$REPO_ROOT/scripts/automation/configure-vscode-profile.py" \
      --apply-machine-settings --check-machine-settings
  else
    python3 "$REPO_ROOT/scripts/automation/configure-vscode-profile.py"
  fi
  while IFS= read -r extension; do
    code --install-extension "$extension" --force >/dev/null
  done < <(python3 -c 'import json, sys; print("\n".join(json.load(open(sys.argv[1], encoding="utf-8"))["recommendations"]))' "$REPO_ROOT/.vscode/extensions.json")
  if code --list-extensions | grep -Fxiq 'ms-azuretools.vscode-azureterraform'; then
    code --uninstall-extension ms-azuretools.vscode-azureterraform >/dev/null
  fi
}

run_checks() {
  local failures=0
  local opa_expected
  opa_expected="$(opa_version_from_core_image)"

  check() {
    local label="$1"
    shift
    if "$@"; then
      printf 'ok %-20s\n' "$label"
    else
      printf 'missing or invalid: %s\n' "$label" >&2
      failures=$((failures + 1))
    fi
  }

  check "build tools" bash -c 'command -v make >/dev/null && command -v gcc >/dev/null && command -v g++ >/dev/null'
  check "ripgrep" rg --version
  check "ShellCheck" shellcheck --version
  check "Tesseract English" bash -c 'tesseract --list-langs 2>/dev/null | grep -Fxq eng'
  check "Tesseract Korean" bash -c 'tesseract --list-langs 2>/dev/null | grep -Fxq kor'
  check "Docker CLI" docker --version
  check "Docker Compose v2" docker compose version
  check "Docker daemon" docker_info
  check "Local data stack" local_data_stack_healthy
  check "uv ${UV_VERSION}" bash -c "[[ \$(uv --version) == 'uv ${UV_VERSION} '* ]]"
  check "Python 3.13" uv python find 3.13
  check "Node ${NODE_VERSION}" bash -c "[[ \$(node --version) == 'v${NODE_VERSION}' ]]"
  check "npm" npm --version
  check "OPA ${opa_expected}" bash -c "[[ \$(opa version | awk '/^Version:/ {print \$2}') == '${opa_expected}' ]]"
  check "OPA policies" opa check "$REPO_ROOT/policies"
  check "Terraform ${TERRAFORM_VERSION}" bash -c "[[ \$(terraform version -json | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"terraform_version\"])') == '${TERRAFORM_VERSION}' ]]"
  check "Azure CLI ${AZURE_CLI_VERSION}" bash -c "[[ \$(az version --query '\"azure-cli\"' --output tsv) == '${AZURE_CLI_VERSION}' ]]"
  check "Azure Developer CLI ${AZD_VERSION}" bash -c "[[ \$(azd version | awk '{print \$3}') == '${AZD_VERSION}' ]]"
  check "GitHub CLI ${GH_VERSION}" bash -c "[[ \$(gh --version | awk 'NR == 1 {print \$3}') == '${GH_VERSION}' ]]"
  check "Project Python 3.13" bash -c "[[ \$('$REPO_ROOT/.venv/bin/python' -c 'import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}\")') == '3.13' ]]"
  check "Python dependencies" "$REPO_ROOT/.venv/bin/python" -c 'import aiohttp, alembic, httpx, pydantic, pytest, sqlalchemy'
  check "Playwright" npm --prefix "$REPO_ROOT/console" exec playwright -- --version
  check "Git hooks" bash -c "[[ \$(git -C '$REPO_ROOT' config --get core.hooksPath) == '.githooks' ]]"

  if (( ! SKIP_VSCODE )) && command -v code >/dev/null 2>&1; then
    if (( IS_WSL )); then
      check "VS Code profile" python3 "$REPO_ROOT/scripts/automation/configure-vscode-profile.py" --check-machine-settings
    else
      check "VS Code profile" python3 "$REPO_ROOT/scripts/automation/configure-vscode-profile.py"
    fi
  fi

  if (( failures > 0 )); then
    printf '%d development environment check(s) failed\n' "$failures" >&2
    return 1
  fi
  printf 'FDAI local development environment is ready.\n'
}

if (( CHECK_ONLY )); then
  run_checks
  exit
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
mkdir -p "$USER_BIN" "$USER_OPT"

install_system_packages
install_microsoft_package_source
install_uv_and_python
install_node
install_opa
install_terraform
install_github_cli
install_azd
install_project_dependencies
start_local_data_stack
if (( ! SKIP_VSCODE )); then
  configure_vscode
fi
run_checks

printf '\nImport .vscode/fdai.code-profile with "Profiles: Import Profile" in VS Code.\n'
printf 'Reopen the WSL window once so existing terminals receive Docker group membership.\n'
