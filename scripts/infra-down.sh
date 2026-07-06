#!/usr/bin/env bash
#
# infra-down.sh - tear the aiopspilot Azure inventory down.
#
# Guardrails: refuses to run unless
#   1. AZURE_CONFIG_DIR is unset (default profile), AND
#   2. `az account show` returns the subscription id in
#      $AIOPSPILOT_EXPECTED_SUBSCRIPTION_ID (required env var).
#
# The expected subscription id is NOT hardcoded here so this script stays
# customer-agnostic per generic-scope.instructions.md; every operator
# exports the id for their own deployment. Suggested location:
# an untracked shell profile snippet or the fork's onboarding docs.
#
# This script is destructive. Every resource created by `terraform apply` in
# infra/ is destroyed. Use only when the deployment is no longer needed;
# artifacts (audit log, PRs) can be reproduced from git + memory, but a
# destroyed Postgres loses the in-DB state.

set -euo pipefail

<<<<<<< Updated upstream
readonly MOONCHOI_SUB="00000000-0000-0000-0000-000000000002"
=======
if [[ -z "${AIOPSPILOT_EXPECTED_SUBSCRIPTION_ID:-}" ]]; then
  echo "infra-down: AIOPSPILOT_EXPECTED_SUBSCRIPTION_ID is not set." >&2
  echo "            Export the subscription id you expect to tear down, e.g.:" >&2
  echo "              export AIOPSPILOT_EXPECTED_SUBSCRIPTION_ID='<your-sub-guid>'" >&2
  exit 1
fi

readonly EXPECTED_SUB="${AIOPSPILOT_EXPECTED_SUBSCRIPTION_ID}"
>>>>>>> Stashed changes
readonly REPO_ROOT="$(git rev-parse --show-toplevel)"
readonly TFVARS="${REPO_ROOT}/infra/envs/dev.tfvars"

if [[ -n "${AZURE_CONFIG_DIR:-}" ]]; then
  echo "infra-down: refusing to run with AZURE_CONFIG_DIR set (\"${AZURE_CONFIG_DIR}\")." >&2
  echo "            aiopspilot lives in the default profile; unset first." >&2
  exit 2
fi

active_sub="$(az account show --query id -o tsv 2>/dev/null || true)"
if [[ "${active_sub}" != "${EXPECTED_SUB}" ]]; then
  echo "infra-down: active subscription is ${active_sub:-<unknown>}, expected ${EXPECTED_SUB}." >&2
  echo "            Run 'az login' or 'az account set' to switch." >&2
  exit 3
fi

if [[ ! -f "${TFVARS}" ]]; then
  echo "infra-down: ${TFVARS} not found - nothing to tear down (or wrong repo)." >&2
  exit 4
fi

if [[ -z "${TF_VAR_postgres_admin_password:-}" ]]; then
  echo "infra-down: TF_VAR_postgres_admin_password is empty." >&2
  echo "            Terraform still needs the variable for the destroy plan." >&2
  echo "            Set it to any non-empty string, e.g.:" >&2
  echo "              export TF_VAR_postgres_admin_password=placeholder-for-destroy" >&2
  exit 5
fi

echo "infra-down: destroying aiopspilot resources on subscription ${EXPECTED_SUB}..."
echo "infra-down: this will destroy 19 resources (RG + everything inside)."

read -r -p "infra-down: type 'destroy-aiopspilot' to proceed: " confirm
if [[ "${confirm}" != "destroy-aiopspilot" ]]; then
  echo "infra-down: aborted." >&2
  exit 6
fi

cd "${REPO_ROOT}/infra"
terraform destroy -auto-approve -var-file=envs/dev.tfvars
echo "infra-down: destroy complete."
