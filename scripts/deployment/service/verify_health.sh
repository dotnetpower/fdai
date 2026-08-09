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
fqdn="$(jq -r '.fqdn // ""' "$work_dir/service.json")"
health_deadline=$((SECONDS + 900))
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
  if jq -e '.properties.provisioningState == "Provisioned" and .properties.healthState == "Healthy" and .properties.active == true' \
      "$work_dir/revision.json" >/dev/null; then
    break
  fi
  sleep 5
done
python3 "$control_root/deployment_recovery.py" verify \
    --context "$context_path" \
    --service-output "$work_dir/service.json" \
    --account "$work_dir/account.json" \
    --app "$work_dir/app.json" \
    --revision "$work_dir/revision.json" \
    --previous-revision "$previous_revision"

if [[ -n "$fqdn" ]]; then
  readiness_path="$(HEALTH_JSON="$health_json" python3 -c 'import json, os; print(json.loads(os.environ["HEALTH_JSON"])["readiness_path"])')"
  timeout 60s curl --fail --silent --show-error --retry 5 --retry-delay 2 \
    "https://${fqdn}${readiness_path}" >/dev/null
fi
