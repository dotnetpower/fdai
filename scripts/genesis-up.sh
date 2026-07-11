#!/usr/bin/env bash
#
# genesis-up.sh - Day-1 Genesis provisioning surface (surface A).
#
# Pipes `terraform -chdir=infra apply -json` into the ephemeral bootstrap
# `python -m fdai.delivery.provisioning`, which hosts the Genesis screen
# (mocks/ui-webgl/provision-genesis.html) plus the `provision.*` SSE route on
# localhost for the lifetime of one apply.
#
# The bridge (src/fdai/delivery/provisioning/terraform_bridge.py) is a pure
# fold over Terraform's `-json` machine output; nothing in this script edits
# Azure state, and no subprocess is spawned by the Python core. The core
# never runs Terraform - the operator does, and pipes the stream in.
#
# Rationale: deploy-and-onboard.md nominates `terraform apply` (not `azd up`)
# as the entry command, and `azd up` does not emit Terraform's `-json`
# stream on its own stdout, so the Genesis surface is wired directly against
# Terraform. `azd-up.sh` remains the safe-preview wrapper.
#
# Safety:
#   - Default action is a NON-mutating preview (`terraform plan -json`).
#   - Real apply only when FDAI_GENESIS_CONFIRM=1 (mirrors `FDAI_AZD_CONFIRM`
#     in azd-up.sh).
#   - Never prints or stores secrets; environment values come from Terraform
#     variable inputs (env / tfvars), never from this repo.
#
# Optional overrides:
#   FDAI_GENESIS_HOST         bind host (default 127.0.0.1)
#   FDAI_GENESIS_PORT         bind port (default 8770)
#   FDAI_GENESIS_HTML         path to the Genesis HTML
#                             (default mocks/ui-webgl/provision-genesis.html)
#   FDAI_GENESIS_LINGER_SECS  seconds to keep serving after apply ends
#                             (default: CLI default = 6)

set -euo pipefail

log() { printf 'genesis-up: %s\n' "$*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

command -v terraform >/dev/null 2>&1 || fail "terraform is not installed"
command -v python >/dev/null 2>&1 || fail "python is not on PATH (activate the venv)"

infra_dir="${repo_root}/infra"
[[ -d "${infra_dir}" ]] || fail "infra/ not found at ${infra_dir}"

genesis_html="${FDAI_GENESIS_HTML:-${repo_root}/mocks/ui-webgl/provision-genesis.html}"
[[ -f "${genesis_html}" ]] || fail "Genesis HTML not found: ${genesis_html}"

host="${FDAI_GENESIS_HOST:-127.0.0.1}"
port="${FDAI_GENESIS_PORT:-8770}"

# Import check - fail fast if the bootstrap package cannot be imported. Avoids
# discovering it at end-of-plan when the stream has already been consumed.
python -c 'import fdai.delivery.provisioning.cli' \
  || fail "cannot import fdai.delivery.provisioning (activate the venv first)"

# Idempotent init - safe to re-run; short-circuits when the working directory
# is already initialised for the current backend.
terraform -chdir="${infra_dir}" init -input=false -upgrade=false >/dev/null

cli_args=(--host "${host}" --port "${port}" --genesis-html "${genesis_html}")
if [[ -n "${FDAI_GENESIS_LINGER_SECS:-}" ]]; then
  cli_args+=(--linger-seconds "${FDAI_GENESIS_LINGER_SECS}")
fi

if [[ "${FDAI_GENESIS_CONFIRM:-0}" == "1" ]]; then
  log "FDAI_GENESIS_CONFIRM=1 - running 'terraform apply -json' (real provisioning)"
  log "Genesis screen: http://${host}:${port}/"
  # -auto-approve is required because we are streaming machine output; there
  # is no TTY to answer the confirmation prompt.
  terraform -chdir="${infra_dir}" apply -json -auto-approve \
    | python -m fdai.delivery.provisioning "${cli_args[@]}"
  exit "${PIPESTATUS[0]}"
fi

log "safe mode: running 'terraform plan -json' (no changes applied)"
log "to actually provision, re-run with FDAI_GENESIS_CONFIRM=1"
log "Genesis screen: http://${host}:${port}/"
terraform -chdir="${infra_dir}" plan -json \
  | python -m fdai.delivery.provisioning "${cli_args[@]}"
exit "${PIPESTATUS[0]}"
