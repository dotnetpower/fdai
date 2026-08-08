#!/usr/bin/env bash
# Register the ops/hub runner VM as a GitHub Actions self-hosted runner, using
# a short-lived registration token minted via the gh CLI and applied over
# `az vm run-command` (the VM has no public IP). Idempotent (--replace).
#
# Usage: AZURE_SUBSCRIPTION_ID=<expected> AZURE_TENANT_ID=<expected> \
#   ./register-runner.sh <owner>/<repo> [ops_rg] [vm_name] [runner_user] [parallelism]
set -euo pipefail

REPO="${1:?usage: register-runner.sh <owner>/<repo> [ops_rg] [vm_name] [runner_user] [parallelism]}"
OPS_RG="${2:-rg-fdai-ops-krc}"
VM="${3:-vm-runner-fdai-dev-krc}"
RUNNER_USER="${4:-fdairunner}"
PARALLELISM="${5:-1}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?set AZURE_SUBSCRIPTION_ID}"
EXPECTED_TENANT="${AZURE_TENANT_ID:?set AZURE_TENANT_ID}"

if [[ ! "$PARALLELISM" =~ ^[1-5]$ ]]; then
  echo "parallelism must be an integer from 1 through 5" >&2
  exit 2
fi

"$HERE/../../scripts/deployment/azure/verify-azure-context.sh" \
  "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT"

echo "== minting registration token =="
TOKEN=$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" --jq .token)
REMOVE_TOKEN=$(gh api -X POST "repos/${REPO}/actions/runners/remove-token" --jq .token)

echo "== registering ${PARALLELISM} runner slot(s) on ${VM} (via run-command) =="
az vm run-command invoke -g "$OPS_RG" -n "$VM" --command-id RunShellScript --scripts "
set -euo pipefail
base_home=/home/${RUNNER_USER}/actions-runner
install_runner() {
  local runner_home=\"\$1\"
  if [ -x \"\$runner_home/config.sh\" ]; then
    return
  fi
  install -d -o ${RUNNER_USER} -g ${RUNNER_USER} \"\$runner_home\"
  local runner_version
  runner_version=\$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/^v//')
  curl -fsSL -o \"\$runner_home/runner.tar.gz\" \
    \"https://github.com/actions/runner/releases/download/v\$runner_version/actions-runner-linux-x64-\$runner_version.tar.gz\"
  tar -xzf \"\$runner_home/runner.tar.gz\" -C \"\$runner_home\"
  rm -f \"\$runner_home/runner.tar.gz\"
  chown -R ${RUNNER_USER}:${RUNNER_USER} \"\$runner_home\"
}
for slot in \$(seq 1 ${PARALLELISM}); do
  runner_home=\"\$base_home\"
  runner_name=\$(hostname)
  if [ \"\$slot\" -gt 1 ]; then
    runner_home=\"\$base_home-\$slot\"
    runner_name=\"\$(hostname)-\$slot\"
  fi
  install_runner \"\$runner_home\"
  cd \"\$runner_home\"
  if [ -f .runner ]; then
    ./svc.sh stop || true
    ./svc.sh uninstall || true
    sudo -u ${RUNNER_USER} ./config.sh remove --token ${REMOVE_TOKEN}
  fi
  sudo -u ${RUNNER_USER} ./config.sh --unattended \
    --url https://github.com/${REPO} \
    --token ${TOKEN} \
    --name \"\$runner_name\" \
    --labels self-hosted,fdai-deploy
  ./svc.sh install ${RUNNER_USER}
  ./svc.sh start
  ./svc.sh status
done
for runner_home in \"\$base_home\"-[2-5]; do
  [ -d \"\$runner_home\" ] || continue
  slot=\"[${runner_home##*-}\"
  if [ \"\$slot\" -le ${PARALLELISM} ]; then
    continue
  fi
  cd \"\$runner_home\"
  if [ -f .runner ]; then
    ./svc.sh stop || true
    ./svc.sh uninstall || true
    sudo -u ${RUNNER_USER} ./config.sh remove --token ${REMOVE_TOKEN}
  fi
  rm -rf -- \"\$runner_home\"
done
" --query "value[0].message" -o tsv | tail -12

echo "== runner status on GitHub =="
gh api "repos/${REPO}/actions/runners" --jq '.runners[] | {name, status, labels: [.labels[].name]}'
