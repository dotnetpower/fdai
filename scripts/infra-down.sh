#!/usr/bin/env bash
#
# infra-down.sh — tear the aiopspilot Azure inventory down.
#
# Guardrails: refuses to run unless
#   1. AZURE_CONFIG_DIR is unset (default moonchoi profile), AND
#   2. `az account show` returns the moonchoi subscription id.
#
# This script is destructive. Every resource created by `terraform apply` in
# infra/ is destroyed. Use only when the deployment is no longer needed;
# artifacts (audit log, PRs) can be reproduced from git + memory, but a
# destroyed Postgres loses the in-DB state.

set -euo pipefail

readonly MOONCHOI_SUB="00000000-0000-0000-0000-000000000002"
readonly REPO_ROOT="$(git rev-parse --show-toplevel)"
readonly TFVARS="${REPO_ROOT}/infra/envs/dev.tfvars"

if [[ -n "${AZURE_CONFIG_DIR:-}" ]]; then
  echo "infra-down: refusing to run with AZURE_CONFIG_DIR set (\"${AZURE_CONFIG_DIR}\")." >&2
  echo "            aiopspilot lives in the default moonchoi profile; unset first." >&2
  exit 2
fi

active_sub="$(az account show --query id -o tsv 2>/dev/null || true)"
if [[ "${active_sub}" != "${MOONCHOI_SUB}" ]]; then
  echo "infra-down: active subscription is ${active_sub:-<unknown>}, expected ${MOONCHOI_SUB}." >&2
  echo "            Run 'az login' or 'az account set' to switch to moonchoi." >&2
  exit 3
fi

if [[ ! -f "${TFVARS}" ]]; then
  echo "infra-down: ${TFVARS} not found — nothing to tear down (or wrong repo)." >&2
  exit 4
fi

if [[ -z "${TF_VAR_postgres_admin_password:-}" ]]; then
  echo "infra-down: TF_VAR_postgres_admin_password is empty." >&2
  echo "            Terraform still needs the variable for the destroy plan." >&2
  echo "            Set it to any non-empty string, e.g.:" >&2
  echo "              export TF_VAR_postgres_admin_password=placeholder-for-destroy" >&2
  exit 5
fi

echo "infra-down: destroying aiopspilot resources on subscription ${MOONCHOI_SUB}..."
echo "infra-down: this will destroy 19 resources (RG + everything inside)."

read -r -p "infra-down: type 'destroy-aiopspilot' to proceed: " confirm
if [[ "${confirm}" != "destroy-aiopspilot" ]]; then
  echo "infra-down: aborted." >&2
  exit 6
fi

cd "${REPO_ROOT}/infra"
terraform destroy -auto-approve -var-file=envs/dev.tfvars
echo "infra-down: destroy complete."
