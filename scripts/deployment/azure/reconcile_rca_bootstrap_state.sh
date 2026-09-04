#!/usr/bin/env bash
# Reconcile the two legacy measurement Job addresses that block a targeted RCA identity plan.
set -euo pipefail

before_digest="$(terraform state pull | sha256sum | cut -d' ' -f1)"
state_list="$(terraform state list)"

state_has() {
  grep -Fxq -- "$1" <<< "$state_list"
}

for resource in baseline_regression pattern_growth; do
  new="module.measurement_runners[0].azurerm_container_app_job.${resource}[0]"
  legacy=()
  for candidate in \
    "module.measurement_runners[0].azurerm_container_app_job.${resource}" \
    "module.measurement_runners.azurerm_container_app_job.${resource}[0]"; do
    state_has "$candidate" && legacy+=("$candidate")
  done
  if (( ${#legacy[@]} > 1 )) || { (( ${#legacy[@]} == 1 )) && state_has "$new"; }; then
    echo "legacy and current measurement state addresses conflict" >&2
    exit 1
  fi
  if (( ${#legacy[@]} == 1 )); then
    terraform state mv "${legacy[0]}" "$new"
    state_list="${state_list//${legacy[0]}/$new}"
  fi
done

after_digest="$(terraform state pull | sha256sum | cut -d' ' -f1)"
{
  echo "RCA bootstrap prerequisite state reconciliation completed."
  echo "Before digest: \`sha256:${before_digest}\`"
  echo "After digest: \`sha256:${after_digest}\`"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
