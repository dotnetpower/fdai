#!/usr/bin/env bash
# Reconcile the two legacy measurement Job addresses that block a targeted RCA identity plan.
set -euo pipefail

before_digest="$(terraform state pull | sha256sum | cut -d' ' -f1)"
state_list="$(terraform state list)"

state_has() {
  grep -Fxq -- "$1" <<< "$state_list"
}

for resource in baseline_regression pattern_growth; do
  old="module.measurement_runners.azurerm_container_app_job.${resource}[0]"
  new="module.measurement_runners[0].azurerm_container_app_job.${resource}[0]"
  if state_has "$old"; then
    ! state_has "$new" || {
      echo "both legacy and current measurement state addresses exist" >&2
      exit 1
    }
    terraform state mv "$old" "$new"
    state_list="${state_list//$old/$new}"
  fi
done

after_digest="$(terraform state pull | sha256sum | cut -d' ' -f1)"
{
  echo "RCA bootstrap prerequisite state reconciliation completed."
  echo "Before digest: \`sha256:${before_digest}\`"
  echo "After digest: \`sha256:${after_digest}\`"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
