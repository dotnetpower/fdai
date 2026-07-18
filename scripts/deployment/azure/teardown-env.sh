#!/usr/bin/env bash
# Cost/lifecycle helper for the ops/hub runner + an app environment.
#
#   ./scripts/deployment/azure/teardown-env.sh runner-stop            # deallocate the runner VM
#   ./scripts/deployment/azure/teardown-env.sh runner-start           # start it before a CI run
#   ./scripts/deployment/azure/teardown-env.sh env-destroy <env> <owner/repo>   # destroy an app env
#
# env-destroy dispatches the destroy-env workflow (self-hosted runner, real
# remote state) - it never deletes the ops hub or the state account, and the
# workflow re-checks the confirm guard.
#
# The ops resource-group and runner VM names are deployment-specific (CAF
# rendering picks a different suffix per environment / region), so this
# script requires them via env rather than hardcoding a default:
#
#   export FDAI_OPS_RG='<caf-ops-resource-group>'
#   export FDAI_OPS_RUNNER_VM='<caf-runner-vm>'
#
# Legacy OPS_RG / VM env names are still honoured for back-compat.
set -euo pipefail

OPS_RG="${FDAI_OPS_RG:-${OPS_RG:-}}"
VM="${FDAI_OPS_RUNNER_VM:-${VM:-}}"

_need() {
  local name="$1" value="$2"
  if [ -z "$value" ]; then
    echo "teardown-env: $name is not set. Export the CAF-named resource, e.g.:" >&2
    echo "  export $name='<caf-name>'" >&2
    exit 2
  fi
}

case "${1:-}" in
  runner-stop)
    _need FDAI_OPS_RG "$OPS_RG"
    _need FDAI_OPS_RUNNER_VM "$VM"
    az vm deallocate -g "$OPS_RG" -n "$VM"
    echo "runner deallocated (compute billing stops; disk still billed)."
    ;;
  runner-start)
    _need FDAI_OPS_RG "$OPS_RG"
    _need FDAI_OPS_RUNNER_VM "$VM"
    az vm start -g "$OPS_RG" -n "$VM"
    echo "runner started; give the actions-runner service ~30s to reconnect."
    ;;
  env-destroy)
    ENV="${2:?usage: teardown-env.sh env-destroy <dev|staging|prod> [owner/repo]}"
    REPO="${3:-${GH_REPO:-}}"
    [ -n "$REPO" ] || { echo "set owner/repo (arg 3) or GH_REPO env." >&2; exit 1; }
    echo "This destroys the '$ENV' app environment via the destroy-env workflow"
    echo "(real remote state; the ops hub + state account are NOT touched)."
    read -r -p "Type the env name to confirm: " confirm
    [ "$confirm" = "$ENV" ] || { echo "aborted."; exit 1; }
    # The destroy runs on the self-hosted runner with the vetted backend + vars,
    # never a stale local dir. The workflow re-checks confirm == environment.
    gh workflow run destroy-env.yml -R "$REPO" \
      -f environment="$ENV" -f confirm="$ENV"
    echo "destroy-env workflow dispatched; watch: gh run watch -R $REPO"
    ;;
  *)
    echo "usage: teardown-env.sh {runner-stop|runner-start|env-destroy <env>}" >&2
    exit 1
    ;;
esac
