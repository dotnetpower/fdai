#!/usr/bin/env bash
# Register the ops/hub runner VM as a GitHub Actions self-hosted runner, using
# a short-lived registration token minted via the gh CLI and applied over
# `az vm run-command` (the VM has no public IP). Idempotent (--replace).
#
# Usage:  ./register-runner.sh <owner>/<repo> [ops_rg] [vm_name] [runner_user]
set -euo pipefail

REPO="${1:?usage: register-runner.sh <owner>/<repo> [ops_rg] [vm_name] [runner_user]}"
OPS_RG="${2:-rg-fdai-ops-krc}"
VM="${3:-vm-runner-fdai-dev-krc}"
RUNNER_USER="${4:-fdairunner}"

echo "== minting registration token =="
TOKEN=$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" --jq .token)
REMOVE_TOKEN=$(gh api -X POST "repos/${REPO}/actions/runners/remove-token" --jq .token)

echo "== registering runner on ${VM} (via run-command) =="
az vm run-command invoke -g "$OPS_RG" -n "$VM" --command-id RunShellScript --scripts "
set -e
cd /home/${RUNNER_USER}/actions-runner || cd \$(find /home -maxdepth 3 -name config.sh -printf '%h' -quit)
if [ -f .runner ]; then
  ./svc.sh stop || true
  ./svc.sh uninstall || true
  sudo -u ${RUNNER_USER} ./config.sh remove --token ${REMOVE_TOKEN}
fi
sudo -u ${RUNNER_USER} ./config.sh --unattended \
  --url https://github.com/${REPO} \
  --token ${TOKEN} \
  --name \$(hostname) \
  --labels self-hosted,fdai-deploy
./svc.sh install ${RUNNER_USER}
./svc.sh start
./svc.sh status
" --query "value[0].message" -o tsv | tail -12

echo "== runner status on GitHub =="
gh api "repos/${REPO}/actions/runners" --jq '.runners[] | {name, status, labels: [.labels[].name]}'
