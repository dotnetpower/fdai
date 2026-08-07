#!/usr/bin/env bash
set -euo pipefail

service_json="$(terraform output -json service)"
health_json="$(terraform output -json health_contract)"

readarray -t service_fields < <(
  SERVICE_JSON="$service_json" python3 - <<'PY'
import json
import os

service = json.loads(os.environ["SERVICE_JSON"])
resource_id = service.get("id", "")
parts = resource_id.split("/")
try:
    resource_group = parts[parts.index("resourceGroups") + 1]
except (ValueError, IndexError) as exc:
    raise SystemExit("service output has an invalid Azure resource id") from exc
for field in (resource_group, service.get("name", ""), service.get("latest_revision_name", ""), service.get("fqdn") or ""):
    if "\n" in field or "\r" in field:
        raise SystemExit("service output contains an invalid line break")
    print(field)
PY
)

resource_group="${service_fields[0]}"
service_name="${service_fields[1]}"
revision_name="${service_fields[2]}"
fqdn="${service_fields[3]}"

revision_json="$(
  timeout 60s az containerapp revision show \
    --resource-group "$resource_group" \
    --name "$service_name" \
    --revision "$revision_name" \
    --only-show-errors \
    --output json
)"
REVISION_JSON="$revision_json" python3 - <<'PY'
import json
import os

revision = json.loads(os.environ["REVISION_JSON"])
properties = revision.get("properties", {})
if properties.get("provisioningState") != "Provisioned":
    raise SystemExit("latest service revision is not Provisioned")
if properties.get("healthState") != "Healthy":
    raise SystemExit("latest service revision is not Healthy")
if properties.get("active") is not True:
    raise SystemExit("latest service revision is not active")
PY

if [[ -n "$fqdn" ]]; then
  readiness_path="$(HEALTH_JSON="$health_json" python3 -c 'import json, os; print(json.loads(os.environ["HEALTH_JSON"])["readiness_path"])')"
  timeout 60s curl --fail --silent --show-error --retry 5 --retry-delay 2 \
    "https://${fqdn}${readiness_path}" >/dev/null
fi
