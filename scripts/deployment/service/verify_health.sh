#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 3 ]] || {
    echo "usage: verify_health.sh CONTEXT PREVIOUS_REVISION CONTROL_ROOT" >&2
    exit 2
}
context_path="$1"
previous_revision="$2"
control_root="$3"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

health_json="$(terraform output -json health_contract)"
terraform output -json service >"$work_dir/service.json"
az account show --only-show-errors --output json >"$work_dir/account.json"
resource_id="$(jq -er '.target.service_resource_id' "$context_path")"
resource_group="$(jq -er '.target.resource_group' "$context_path")"
service_name="$(jq -er '.target.service_name' "$context_path")"
expected_image="$(jq -er '.target.image_ref' "$context_path")"
fqdn="$(jq -r '.fqdn // ""' "$work_dir/service.json")"
edge_resource_id="$(jq -r '.operator_channel_edge.service_resource_id // ""' "$context_path")"
edge_state="$(jq -r '.operator_channel_edge.state // "enabled"' "$context_path")"
if [[ -n "$edge_resource_id" && "$edge_state" == "disabled" ]]; then
  if timeout 60s az containerapp show \
      --ids "$edge_resource_id" \
      --only-show-errors \
      --output none 2>/dev/null; then
    echo "disabled channel edge still exists after protected apply." >&2
    exit 1
  fi
  echo "disabled channel edge route removal verified."
fi
health_deadline=$((SECONDS + 900))
activation_attempted=false
health_converged=false
while ((SECONDS < health_deadline)); do
  timeout 60s az containerapp show \
      --ids "$resource_id" \
      --only-show-errors \
      --output json >"$work_dir/app.json"
  revision_name="$(jq -er '.properties.latestRevisionName' "$work_dir/app.json")"
  timeout 60s az containerapp revision show \
      --resource-group "$resource_group" \
      --name "$service_name" \
      --revision "$revision_name" \
      --only-show-errors \
      --output json >"$work_dir/revision.json"
  requires_health_state="$(jq -er '
    if .properties.configuration.ingress == null then "false"
    elif (.properties.configuration.ingress | type) == "object" then "true"
    else error("Container App ingress configuration is invalid")
    end
  ' "$work_dir/app.json")"
  observed_image="$(jq -er '.properties.template.containers[0].image' "$work_dir/revision.json")"
  [[ "$revision_name" != "$previous_revision" && "$observed_image" == "$expected_image" ]] || {
    echo "latest revision does not match the exact protected service image." >&2
    exit 1
  }
  if [[ "$activation_attempted" == false ]] && ! jq -e '.properties.active == true' \
      "$work_dir/revision.json" >/dev/null; then
    timeout 60s az containerapp revision activate \
      --resource-group "$resource_group" \
      --name "$service_name" \
      --revision "$revision_name" \
      --only-show-errors \
      --output none
    activation_attempted=true
  fi
  if jq -e --argjson requires_health_state "$requires_health_state" '
      .properties.provisioningState == "Provisioned"
      and .properties.active == true
      and (
        .properties.healthState == "Healthy"
        or (
          ($requires_health_state | not)
          and .properties.healthState == null
          and .properties.runningState == "Running"
          and (.properties.replicas | type) == "number"
          and .properties.replicas >= 1
        )
      )
    ' \
      "$work_dir/revision.json" >/dev/null; then
    health_converged=true
    break
  fi
  # One bounded progress line per poll, so a stalled rollout is distinguishable from a slow one
  # instead of leaving the deadline as the only signal.
  echo "health poll: revision=$revision_name provisioning=$(jq -r '.properties.provisioningState // "unknown"' "$work_dir/revision.json") health=$(jq -r '.properties.healthState // "none"' "$work_dir/revision.json") running=$(jq -r '.properties.runningState // "unknown"' "$work_dir/revision.json") remaining=$((health_deadline - SECONDS))s" >&2
  sleep 5
done
if [[ "$health_converged" != true ]]; then
  echo "container app did not reach the healthy contract within its 900s health deadline." >&2
  exit 1
fi
timeout 120s python3 "$control_root/deployment_recovery.py" verify \
    --context "$context_path" \
    --service-output "$work_dir/service.json" \
    --account "$work_dir/account.json" \
    --app "$work_dir/app.json" \
    --revision "$work_dir/revision.json" \
    --previous-revision "$previous_revision"

if [[ -n "$fqdn" ]]; then
  readiness_path="$(HEALTH_JSON="$health_json" timeout 30s python3 -c 'import json, os; print(json.loads(os.environ["HEALTH_JSON"])["readiness_path"])')"
  timeout 60s curl --fail --silent --show-error --retry 5 --retry-delay 2 \
    --retry-max-time 40 --connect-timeout 5 --max-time 15 \
    "https://${fqdn}${readiness_path}" >/dev/null
fi

if [[ -n "$edge_resource_id" && "$edge_state" != "disabled" ]]; then
  jq -e '.channel_edge | type == "object"' "$work_dir/service.json" >/dev/null || {
    echo "Terraform channel edge output is missing after protected apply." >&2
    exit 1
  }
  jq '.channel_edge' "$work_dir/service.json" >"$work_dir/edge-service.json"
  jq '.target = .operator_channel_edge | del(.operator_channel_edge)' \
    "$context_path" >"$work_dir/edge-context.json"
  edge_resource_group="$(jq -er '.target.resource_group' "$work_dir/edge-context.json")"
  edge_service_name="$(jq -er '.target.service_name' "$work_dir/edge-context.json")"
  edge_expected_image="$(jq -er '.target.image_ref' "$work_dir/edge-context.json")"
  previous_edge_revision="${PREVIOUS_CHANNEL_EDGE_REVISION:-absent}"
  edge_health_converged=false
  edge_health_deadline=$((SECONDS + 900))
  while ((SECONDS < edge_health_deadline)); do
    timeout 60s az containerapp show \
      --ids "$edge_resource_id" \
      --only-show-errors \
      --output json >"$work_dir/edge-app.json"
    edge_revision_name="$(jq -er '.properties.latestRevisionName' "$work_dir/edge-app.json")"
    timeout 60s az containerapp revision show \
      --resource-group "$edge_resource_group" \
      --name "$edge_service_name" \
      --revision "$edge_revision_name" \
      --only-show-errors \
      --output json >"$work_dir/edge-revision.json"
    edge_observed_image="$(jq -er '.properties.template.containers[0].image' \
      "$work_dir/edge-revision.json")"
    [[ "$edge_revision_name" != "$previous_edge_revision" \
      && "$edge_observed_image" == "$edge_expected_image" ]] || {
      echo "channel edge revision does not match the exact protected image." >&2
      exit 1
    }
    if jq -e '
      .properties.provisioningState == "Provisioned"
      and .properties.active == true
      and .properties.healthState == "Healthy"
    ' "$work_dir/edge-revision.json" >/dev/null; then
      edge_health_converged=true
      break
    fi
    echo "edge health poll: revision=$edge_revision_name provisioning=$(jq -r '.properties.provisioningState // "unknown"' "$work_dir/edge-revision.json") health=$(jq -r '.properties.healthState // "none"' "$work_dir/edge-revision.json") remaining=$((edge_health_deadline - SECONDS))s" >&2
    sleep 5
  done
  if [[ "$edge_health_converged" != true ]]; then
    echo "channel edge did not reach the healthy contract within its 900s deadline." >&2
    exit 1
  fi
  timeout 120s python3 "$control_root/deployment_recovery.py" verify \
    --context "$work_dir/edge-context.json" \
    --service-output "$work_dir/edge-service.json" \
    --account "$work_dir/account.json" \
    --app "$work_dir/edge-app.json" \
    --revision "$work_dir/edge-revision.json" \
    --previous-revision "$previous_edge_revision"
  edge_fqdn="$(jq -er '.fqdn' "$work_dir/edge-service.json")"
  edge_readiness_path="$(terraform output -json channel_edge_health_contract \
    | jq -er '.readiness_path')"
  timeout 60s curl --fail --silent --show-error --retry 5 --retry-delay 2 \
    --retry-max-time 40 --connect-timeout 5 --max-time 15 \
    "https://${edge_fqdn}${edge_readiness_path}" >/dev/null
fi
