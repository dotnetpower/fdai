#!/usr/bin/env bash
#
# azd-up.sh - guarded public-development deployment over azd + Terraform.
#
# This path is deliberately limited to a clean checkout, Azure public cloud,
# one public-network dev environment, and the independently owned Core service.
# Private subscription genesis and production continue to use fdaictl plus the
# protected VNet runner.
#
# Behavior:
#   - Interactive default: read the active `az login` context and ask one
#     fail-closed region/deployment question before running the confirmed flow.
#   - FDAI_AZD_CONFIRM=0: perform read-only discovery and preview the platform.
#   - FDAI_AZD_CONFIRM=1: register prerequisites, preview and provision the
#     platform, build an exact Core image in deployment-owned ACR, migrate the
#     database and catalogs, apply an exact Core plan, enable scheduled jobs,
#     and verify Core, canary, and inventory health.
#
# Generated state and inputs stay under the gitignored, mode-0700 .fdai tree.
# The script never accepts a password: Terraform creates the initial password
# in private local state and stores the application DSN in Key Vault.
# Non-interactive callers supply both target axes and a confirmation mode.

set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
PLATFORM_ROOT="$REPO_ROOT/infra"
CORE_ROOT="$PLATFORM_ROOT/services/core-control-plane"
log() { printf 'azd-up: %s\n' "$*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

# shellcheck source=scripts/deployment/azure/contributor-target.sh
source "$HERE/contributor-target.sh"
# shellcheck source=scripts/deployment/azure/contributor-terraform.sh
source "$HERE/contributor-terraform.sh"
TARGET_HAS_TERMINAL=0
if [[ -t 0 && -t 2 ]]; then
  TARGET_HAS_TERMINAL=1
fi
resolve_contributor_target "$TARGET_HAS_TERMINAL"
if [[ "$TARGET_STATUS" == "cancel" ]]; then
  log "deployment cancelled before any Azure mutation"
  exit 0
fi

AZD_ENVIRONMENT="${FDAI_AZD_ENVIRONMENT:-fdai-dev}"
REGION_SHORT="${FDAI_AZURE_REGION_SHORT:-}"
if [[ -z "$REGION_SHORT" ]]; then
  case "$REGION" in
    centralus) REGION_SHORT="cus" ;;
    eastasia) REGION_SHORT="ea" ;;
    eastus) REGION_SHORT="eus" ;;
    eastus2) REGION_SHORT="eus2" ;;
    koreacentral) REGION_SHORT="krc" ;;
    northeurope) REGION_SHORT="neu" ;;
    westus2) REGION_SHORT="wus2" ;;
    westeurope) REGION_SHORT="weu" ;;
    *) REGION_SHORT="${REGION:0:5}" ;;
  esac
fi
SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
RESOURCE_NAME_SUFFIX="$(printf '%s' "${EXPECTED_SUBSCRIPTION,,}" | sha256sum | cut -c1-6)"
WORK_DIR="${FDAI_AZD_WORK_DIR:-$REPO_ROOT/.fdai/deploy/public-dev-$RESOURCE_NAME_SUFFIX}"
LOCK_ROOT="$REPO_ROOT/.fdai/deploy"
PLATFORM_OVERRIDE="$PLATFORM_ROOT/contributor_override.tf.json"
CORE_OVERRIDE="$CORE_ROOT/contributor_override.tf.json"
PLATFORM_STATE="$REPO_ROOT/.azure/$AZD_ENVIRONMENT/infra/terraform.tfstate"
CORE_STATE="$WORK_DIR/core-control-plane.tfstate"
PLATFORM_TF_DATA="$REPO_ROOT/.azure/$AZD_ENVIRONMENT/infra/.terraform"
CORE_TF_DATA="$WORK_DIR/core-terraform-data"
RESOLVED_MODELS="$WORK_DIR/resolved-models.json"
CORE_TFVARS="$WORK_DIR/core.auto.tfvars.json"
CORE_PLAN="$WORK_DIR/core.tfplan"
LICENSE_TOKEN_FILE="$WORK_DIR/license.token"
LICENSE_SECRET_ID=""
LICENSE_IMAGE_DIGEST=""
LICENSE_DEPLOYMENT_DIGEST=""
LICENSE_TOKEN_REVISION=""
BUILD_CONTEXT=""
MODEL_ROLE_CREATED=0
FIREWALL_OPEN=0
PLATFORM_OVERRIDE_CREATED=0
CORE_OVERRIDE_CREATED=0
FIREWALL_RESOURCE_GROUP=""
FIREWALL_SERVER=""
FIREWALL_RULE=""

cleanup() {
  local status=$?
  local cleanup_failed=0
  trap - EXIT
  if [[ "$FIREWALL_OPEN" == "1" ]]; then
    timeout 60s az postgres flexible-server firewall-rule delete \
      --subscription "$EXPECTED_SUBSCRIPTION" \
      --resource-group "$FIREWALL_RESOURCE_GROUP" \
      --name "$FIREWALL_SERVER" \
      --rule-name "$FIREWALL_RULE" \
      --yes --only-show-errors --output none || cleanup_failed=1
  fi
  if [[ "$MODEL_ROLE_CREATED" == "1" ]]; then
    timeout 60s az role assignment delete \
      --subscription "$EXPECTED_SUBSCRIPTION" \
      --assignee-object-id "$DEPLOYER_OBJECT_ID" \
      --role "Cognitive Services Contributor" \
      --scope "/subscriptions/$EXPECTED_SUBSCRIPTION" \
      --only-show-errors || cleanup_failed=1
  fi
  if [[ "$PLATFORM_OVERRIDE_CREATED" == "1" ]]; then
    rm -f -- "$PLATFORM_OVERRIDE"
  fi
  if [[ "$CORE_OVERRIDE_CREATED" == "1" ]]; then
    rm -f -- "$CORE_OVERRIDE"
  fi
  if [[ -n "$BUILD_CONTEXT" ]]; then
    rm -rf -- "$BUILD_CONTEXT"
  fi
  rm -f -- "$LICENSE_TOKEN_FILE"
  if ((status == 0 && cleanup_failed != 0)); then
    log "ERROR: temporary Azure access cleanup failed"
    status=1
  fi
  exit "$status"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

write_local_backend_override() {
  local destination="$1"
  local state_path="$2"
  [[ ! -e "$destination" && ! -L "$destination" ]] || {
    fail "refusing to replace existing Terraform override: $destination"
  }
  DESTINATION="$destination" STATE_PATH="$state_path" python3 - <<'PY'
import json
import os

destination = os.environ["DESTINATION"]
payload = {
    "terraform": {
        "backend": {
            "local": {
                "path": os.environ["STATE_PATH"],
            }
        }
    }
}
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(destination, flags, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
    stream.write("\n")
PY
}

set_scheduled_jobs() {
  local enabled="$1"
  if [[ "$enabled" == "true" ]]; then
    export TF_VAR_enable_legacy_oob_job=true
    export TF_VAR_canary_cron_expression="${FDAI_CANARY_CRON_EXPRESSION:-*/5 * * * *}"
    export TF_VAR_rule_watcher_cron_expression="${FDAI_RULE_WATCHER_CRON_EXPRESSION:-0 3 * * *}"
    export TF_VAR_provider_schema_cron_expression="${FDAI_PROVIDER_SCHEMA_CRON_EXPRESSION:-0 4 * * *}"
    export TF_VAR_analyzer_tick_cron_expression="${FDAI_ANALYZER_TICK_CRON_EXPRESSION:-* * * * *}"
    export TF_VAR_inventory_cron_expression="${FDAI_INVENTORY_CRON_EXPRESSION:-* * * * *}"
    export TF_VAR_observation_campaign_cron_expression="${FDAI_OBSERVATION_CAMPAIGN_CRON_EXPRESSION:-* * * * *}"
    export TF_VAR_operational_history_lifecycle_cron_expression="${FDAI_OPERATIONAL_HISTORY_LIFECYCLE_CRON_EXPRESSION:-0 * * * *}"
  else
    export TF_VAR_enable_legacy_oob_job=false
    export TF_VAR_canary_cron_expression=""
    export TF_VAR_rule_watcher_cron_expression=""
    export TF_VAR_provider_schema_cron_expression=""
    export TF_VAR_analyzer_tick_cron_expression=""
    export TF_VAR_inventory_cron_expression=""
    export TF_VAR_observation_campaign_cron_expression=""
    export TF_VAR_operational_history_lifecycle_cron_expression=""
  fi
}

ensure_resource_providers() {
  local provider_timeout="${FDAI_RESOURCE_PROVIDER_TIMEOUT_SECONDS:-900}"
  [[ "$provider_timeout" =~ ^[0-9]+$ ]] \
    && ((provider_timeout >= 30 && provider_timeout <= 1800)) || {
    fail "FDAI_RESOURCE_PROVIDER_TIMEOUT_SECONDS must be from 30 through 1800"
  }
  local -a arguments=(
    python3 "$HERE/resource_provider_reconcile.py"
    --subscription-id "$EXPECTED_SUBSCRIPTION"
    --profile application
    --timeout-seconds "$provider_timeout"
    --output text
  )
  local status=0
  if [[ "$CONFIRM" == "1" ]]; then
    arguments+=(--apply)
  fi
  "${arguments[@]}" || status=$?
  if ((status == 2)); then
    log "preview stopped: Azure resource providers require registration, which is a mutation"
  elif ((status != 0)); then
    log "ERROR: Azure resource provider reconciliation failed"
  fi
  return "$status"
}

ensure_model_deployer_role() {
  local count
  count="$(timeout 60s az role assignment list \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --scope "/subscriptions/$EXPECTED_SUBSCRIPTION" \
    --assignee-object-id "$DEPLOYER_OBJECT_ID" \
    --role "Cognitive Services Contributor" \
    --include-inherited \
    --query 'length(@)' --output tsv --only-show-errors)"
  [[ "$count" =~ ^[0-9]+$ ]] || fail "could not verify the model deployer role"
  if ((count > 0)); then
    return
  fi
  log "granting the signed-in deployer the temporary model provisioning role"
  timeout 60s az role assignment create \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --assignee-object-id "$DEPLOYER_OBJECT_ID" \
    --role "Cognitive Services Contributor" \
    --scope "/subscriptions/$EXPECTED_SUBSCRIPTION" \
    --only-show-errors --output none
  MODEL_ROLE_CREATED=1
  for _ in $(seq 1 12); do
    count="$(timeout 30s az role assignment list \
      --subscription "$EXPECTED_SUBSCRIPTION" \
      --scope "/subscriptions/$EXPECTED_SUBSCRIPTION" \
      --assignee-object-id "$DEPLOYER_OBJECT_ID" \
      --role "Cognitive Services Contributor" \
      --include-inherited \
      --query 'length(@)' --output tsv --only-show-errors || true)"
    ((count > 0)) && return
    sleep 5
  done
  fail "the temporary model provisioning role did not become visible"
}

resolve_models() {
  local verified_at capabilities_json resolved_json
  verified_at="$(git -C "$REPO_ROOT" show -s --format=%cI "$SOURCE_COMMIT")"
  PYTHONPATH="$REPO_ROOT/services/core-control-plane/src:$REPO_ROOT/packages/service-contracts/src" \
    uv run --frozen --package fdai-core-control-plane python \
      -m fdai.rule_catalog.schema.llm_resolver_cli \
      --registry "$REPO_ROOT/rule-catalog/llm-registry.yaml" \
      --environment dev \
      --region "$REGION" \
      --subscription-id "$EXPECTED_SUBSCRIPTION" \
      --deployer-object-id "$DEPLOYER_OBJECT_ID" \
      --use-azure-cli \
      --azure-cli-timeout-seconds 90 \
      --assess-fail-on none \
      --out "$RESOLVED_MODELS"
  PYTHONPATH="$REPO_ROOT/services/core-control-plane/src:$REPO_ROOT/packages/service-contracts/src" \
    uv run --frozen --package fdai-core-control-plane python \
      "$HERE/seal_model_endpoint_bindings.py" \
      --input "$RESOLVED_MODELS" \
      --output "$RESOLVED_MODELS" \
      --partner-account-name "aif-fdai-models-dev-${REGION_SHORT}-${RESOURCE_NAME_SUFFIX}" \
      --verified-at "$verified_at"
  chmod 0600 "$RESOLVED_MODELS"
  capabilities_json="$(python3 - "$RESOLVED_MODELS" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    capabilities = json.load(stream)["capabilities"]
print(json.dumps(
    [item for item in capabilities if item.get("status") != "hil-only"],
    separators=(",", ":"),
    sort_keys=True,
))
PY
)"
  resolved_json="$(python3 - "$RESOLVED_MODELS" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
PY
)"
  export TF_VAR_resolved_capabilities="$capabilities_json"
  export TF_VAR_resolved_models_json="$resolved_json"
  export TF_VAR_resolved_models_sha256
  TF_VAR_resolved_models_sha256="$(sha256sum "$RESOLVED_MODELS" | cut -d' ' -f1)"
}

platform_preview() {
  log "previewing the public development platform; no Azure resource change is allowed"
  azd provision \
    --environment "$AZD_ENVIRONMENT" \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --location "$REGION" \
    --preview --no-prompt
}

verify_private_state_file() {
  local state_file="$1"
  local label="$2"
  [[ -f "$state_file" && ! -L "$state_file" && -s "$state_file" ]] || {
    fail "$label did not retain a regular local Terraform state file"
  }
  [[ "$(stat -c '%a:%u' "$state_file")" == "600:$EUID" ]] || {
    fail "$label Terraform state is not owner-only"
  }
}

platform_apply() {
  log "applying the reviewed public development platform"
  azd provision \
    --environment "$AZD_ENVIRONMENT" \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --location "$REGION" \
    --no-prompt
  verify_private_state_file "$PLATFORM_STATE" "platform apply"
  terraform -chdir="$PLATFORM_ROOT" state list >/dev/null || {
    fail "platform Terraform state is unreadable"
  }
}

build_core_image() {
  local registry_name login_server tag digest=""
  registry_name="$(terraform -chdir="$PLATFORM_ROOT" output -raw container_registry_name)"
  login_server="$(terraform -chdir="$PLATFORM_ROOT" output -raw container_registry_login_server)"
  [[ "$registry_name" =~ ^[a-z0-9]{5,50}$ ]] || fail "Terraform returned an invalid ACR name"
  [[ "$login_server" == "$registry_name.azurecr.io" ]] || fail "Terraform returned an unexpected ACR login server"
  tag="sha-$SOURCE_COMMIT"
  BUILD_CONTEXT="$(mktemp -d "$WORK_DIR/core-build.XXXXXX")"
  git -C "$REPO_ROOT" archive "$SOURCE_COMMIT" | tar -x -C "$BUILD_CONTEXT"
  install -m 0600 "$RESOLVED_MODELS" "$BUILD_CONTEXT/services/assets/resolved-models.json"
  log "building the exact Core source and resolved model manifest in deployment-owned ACR"
  timeout "${FDAI_AZD_IMAGE_BUILD_TIMEOUT_SECONDS:-3600}s" az acr build \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --registry "$registry_name" \
    --image "fdai-core-control-plane:$tag" \
    --file services/core-control-plane/docker/Dockerfile \
    --only-show-errors \
    "$BUILD_CONTEXT"
  for _ in $(seq 1 6); do
    digest="$(timeout 60s az acr manifest show-metadata \
      --subscription "$EXPECTED_SUBSCRIPTION" \
      --registry "$registry_name" \
      --name "fdai-core-control-plane:$tag" \
      --query digest --output tsv --only-show-errors 2>/dev/null || true)"
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] && break
    sleep 5
  done
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "ACR did not return one immutable Core image digest"
  CORE_IMAGE="$login_server/fdai-core-control-plane@$digest"
  export TF_VAR_core_image="$CORE_IMAGE"
  rm -rf -- "$BUILD_CONTEXT"
  BUILD_CONTEXT=""
}

prepare_capability_license() {
  local private_key="$REPO_ROOT/secrets/license-signing-key.pem"
  local vault_uri vault_name app_name license_id secret_name
  if [[ ! -e "$private_key" && ! -L "$private_key" ]]; then
    log "dedicated license issuer key is absent; Core will run in observation-only Trial mode"
    return
  fi

  LICENSE_IMAGE_DIGEST="${CORE_IMAGE##*@sha256:}"
  [[ "$LICENSE_IMAGE_DIGEST" =~ ^[0-9a-f]{64}$ ]] || {
    fail "the Core image does not carry one license-bindable SHA-256 digest"
  }
  app_name="$(terraform -chdir="$PLATFORM_ROOT" output -raw core_app_name)"
  LICENSE_DEPLOYMENT_DIGEST="$(
    printf '%s\0%s\0%s' "$EXPECTED_TENANT" "$EXPECTED_SUBSCRIPTION" "$app_name" | sha256sum | cut -d' ' -f1
  )"
  [[ "$LICENSE_DEPLOYMENT_DIGEST" =~ ^[0-9a-f]{64}$ ]] || {
    fail "the deployment license binding is invalid"
  }
  license_id="lic-${RESOURCE_NAME_SUFFIX}-$(date -u +%Y%m%d)"
  rm -f -- "$LICENSE_TOKEN_FILE"
  uv run python "$REPO_ROOT/scripts/deployment/release/issue-license.py" \
    --private-key "$private_key" \
    --license-id "$license_id" \
    --distribution-id fdai-upstream \
    --all-capabilities \
    --valid-days 30 \
    --image-digest "$LICENSE_IMAGE_DIGEST" \
    --tenant-binding "$LICENSE_DEPLOYMENT_DIGEST" \
    --output "$LICENSE_TOKEN_FILE"
  [[ -f "$LICENSE_TOKEN_FILE" && ! -L "$LICENSE_TOKEN_FILE" ]] || {
    fail "license issuance did not create a regular private token file"
  }
  [[ "$(stat -c '%a' "$LICENSE_TOKEN_FILE")" == "600" ]] || {
    fail "license token output must use mode 0600"
  }
  LICENSE_TOKEN_REVISION="$(sha256sum "$LICENSE_TOKEN_FILE" | cut -d' ' -f1)"
  secret_name="fdai-license-$LICENSE_TOKEN_REVISION"
  [[ "$secret_name" =~ ^[a-z0-9-]{1,127}$ ]] || {
    fail "the derived capability-license secret name is invalid"
  }

  vault_uri="$(terraform -chdir="$PLATFORM_ROOT" output -raw key_vault_uri)"
  [[ "$vault_uri" =~ ^https://([a-z0-9-]{3,24})\.vault\.azure\.net/?$ ]] || {
    fail "Terraform returned an invalid public-Azure Key Vault URI"
  }
  vault_name="${BASH_REMATCH[1]}"
  log "storing the 30-day capability license through a Key Vault file input"
  timeout 120s az keyvault secret set \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --vault-name "$vault_name" \
    --name "$secret_name" \
    --file "$LICENSE_TOKEN_FILE" \
    --only-show-errors --output none
  LICENSE_SECRET_ID="${vault_uri%/}/secrets/$secret_name"
  rm -f -- "$LICENSE_TOKEN_FILE"
}

open_migration_firewall() {
  local client_ip
  FIREWALL_RESOURCE_GROUP="$(terraform -chdir="$PLATFORM_ROOT" output -raw resource_group_name)"
  FIREWALL_SERVER="$(terraform -chdir="$PLATFORM_ROOT" output -raw postgres_fqdn)"
  FIREWALL_SERVER="${FIREWALL_SERVER%%.*}"
  FIREWALL_RULE="fdai-bootstrap-${SOURCE_COMMIT:0:8}"
  client_ip="${FDAI_AZD_CLIENT_IP:-$(timeout 15s curl --fail --silent --show-error https://api.ipify.org)}"
  CLIENT_IP="$client_ip" python3 - <<'PY'
import ipaddress
import os

value = os.environ["CLIENT_IP"]
address = ipaddress.ip_address(value)
if address.version != 4 or str(address) != value:
    raise SystemExit("FDAI_AZD_CLIENT_IP must be one canonical public IPv4 address")
PY
  log "opening one temporary PostgreSQL /32 rule for schema bootstrap"
  timeout 60s az postgres flexible-server firewall-rule create \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --resource-group "$FIREWALL_RESOURCE_GROUP" \
    --name "$FIREWALL_SERVER" \
    --rule-name "$FIREWALL_RULE" \
    --start-ip-address "$client_ip" \
    --end-ip-address "$client_ip" \
    --only-show-errors --output none
  FIREWALL_OPEN=1
}

close_migration_firewall() {
  [[ "$FIREWALL_OPEN" == "1" ]] || return
  log "removing the temporary PostgreSQL bootstrap rule"
  timeout 60s az postgres flexible-server firewall-rule delete \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --resource-group "$FIREWALL_RESOURCE_GROUP" \
    --name "$FIREWALL_SERVER" \
    --rule-name "$FIREWALL_RULE" \
    --yes --only-show-errors --output none
  FIREWALL_OPEN=0
}

bootstrap_database() {
  open_migration_firewall
  FDAI_MATERIALIZE_AUTHORITATIVE_CATALOGS=1 \
    bash "$HERE/bootstrap-service-migrations.sh" \
      "$PLATFORM_ROOT" "$WORK_DIR/migration-evidence" "$SOURCE_COMMIT"
  close_migration_firewall
}

deploy_core() {
  local platform_input="$WORK_DIR/platform-core-input.json"
  local tfvars_tmp="$CORE_TFVARS.tmp"
  terraform -chdir="$PLATFORM_ROOT" output -json contributor_core_service_tfvars \
    >"$platform_input"
  rm -f -- "$tfvars_tmp"
  CORE_IMAGE="$CORE_IMAGE" \
  LICENSE_SECRET_ID="$LICENSE_SECRET_ID" \
  LICENSE_IMAGE_DIGEST="$LICENSE_IMAGE_DIGEST" \
  LICENSE_DEPLOYMENT_DIGEST="$LICENSE_DEPLOYMENT_DIGEST" \
  LICENSE_TOKEN_REVISION="$LICENSE_TOKEN_REVISION" \
    python3 - "$platform_input" "$tfvars_tmp" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
if not isinstance(payload, dict):
    raise SystemExit("platform did not expose contributor Core service inputs")
image = os.environ["CORE_IMAGE"]
payload["image"] = image
payload["rollback"]["previous_image"] = image
secret_id = os.environ["LICENSE_SECRET_ID"]
payload["license"] = (
  {
    "token_secret_id": secret_id,
    "image_digest": os.environ["LICENSE_IMAGE_DIGEST"],
    "deployment_digest": os.environ["LICENSE_DEPLOYMENT_DIGEST"],
    "token_revision": os.environ["LICENSE_TOKEN_REVISION"],
  }
  if secret_id
  else {}
)
with open(sys.argv[2], "x", encoding="utf-8") as stream:
    json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
    stream.write("\n")
PY
  mv -f -- "$tfvars_tmp" "$CORE_TFVARS"
  rm -f -- "$CORE_PLAN"
  log "planning the independent Core service with local development state"
  TF_CLI_CONFIG_FILE="$CORE_TF_CLI_CONFIG_FILE" \
  TF_DATA_DIR="$CORE_TF_DATA" terraform -chdir="$CORE_ROOT" init \
    -reconfigure -input=false -lockfile=readonly
  TF_CLI_CONFIG_FILE="$CORE_TF_CLI_CONFIG_FILE" \
  TF_DATA_DIR="$CORE_TF_DATA" terraform -chdir="$CORE_ROOT" validate
  TF_CLI_CONFIG_FILE="$CORE_TF_CLI_CONFIG_FILE" \
  TF_DATA_DIR="$CORE_TF_DATA" terraform -chdir="$CORE_ROOT" plan \
    -input=false -lock-timeout=5m -out="$CORE_PLAN" -var-file="$CORE_TFVARS"
  log "applying the exact Core service plan"
  TF_CLI_CONFIG_FILE="$CORE_TF_CLI_CONFIG_FILE" \
  TF_DATA_DIR="$CORE_TF_DATA" terraform -chdir="$CORE_ROOT" apply \
    -input=false -lock-timeout=5m "$CORE_PLAN"
  verify_private_state_file "$CORE_STATE" "Core apply"
}

wait_for_core() {
  local resource_group app revision payload ready=false deadline=$((SECONDS + 1200))
  resource_group="$(terraform -chdir="$PLATFORM_ROOT" output -raw resource_group_name)"
  app="$(terraform -chdir="$PLATFORM_ROOT" output -raw core_app_name)"
  while ((SECONDS < deadline)); do
    revision="$(timeout 60s az containerapp show \
      --subscription "$EXPECTED_SUBSCRIPTION" \
      --resource-group "$resource_group" --name "$app" \
      --query properties.latestRevisionName --output tsv --only-show-errors || true)"
    if [[ -n "$revision" ]]; then
      payload="$(timeout 60s az containerapp revision show \
        --subscription "$EXPECTED_SUBSCRIPTION" \
        --resource-group "$resource_group" --name "$app" --revision "$revision" \
        --output json --only-show-errors || true)"
      if REVISION_JSON="$payload" EXPECTED_IMAGE="$CORE_IMAGE" python3 - <<'PY'
import json
import os

try:
    revision = json.loads(os.environ["REVISION_JSON"])
except json.JSONDecodeError:
    raise SystemExit(1)
properties = revision.get("properties", {})
containers = properties.get("template", {}).get("containers", [])
image_matches = bool(containers) and containers[0].get("image") == os.environ["EXPECTED_IMAGE"]
healthy = properties.get("healthState") == "Healthy"
running_without_ingress = (
    properties.get("healthState") is None
    and properties.get("runningState") == "Running"
    and int(properties.get("replicas") or 0) >= 1
)
raise SystemExit(0 if properties.get("provisioningState") == "Provisioned" and image_matches and (healthy or running_without_ingress) else 1)
PY
      then
        ready=true
        break
      fi
    fi
    log "waiting for the independent Core revision to become healthy"
    sleep 10
  done
  [[ "$ready" == "true" ]] || fail "Core did not reach its bounded healthy state"
}

run_job() {
  local job="$1"
  local purpose="$2"
  local budget="$3"
  local resource_group execution="" status deadline prior_names current_names candidate
  local -a discovered=()
  local -A prior_executions=()
  resource_group="$(terraform -chdir="$PLATFORM_ROOT" output -raw resource_group_name)"
  deadline=$((SECONDS + budget))
  prior_names="$(timeout 60s az containerapp job execution list \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --resource-group "$resource_group" --name "$job" \
    --query '[].name' --output tsv --only-show-errors)" || {
    fail "could not establish the existing $purpose Job executions"
  }
  while IFS= read -r candidate; do
    [[ -z "$candidate" ]] && continue
    [[ "$candidate" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || {
      fail "$purpose Job returned an invalid execution name"
    }
    prior_executions["$candidate"]=1
  done <<<"$prior_names"
  execution="$(timeout 60s az containerapp job start \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --resource-group "$resource_group" --name "$job" \
    --query name --output tsv --only-show-errors)"
  if [[ -n "$execution" && ! "$execution" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
    fail "$purpose Job start returned an invalid execution name"
  fi
  while [[ -z "$execution" ]] && ((SECONDS < deadline)); do
    current_names="$(timeout 60s az containerapp job execution list \
      --subscription "$EXPECTED_SUBSCRIPTION" \
      --resource-group "$resource_group" --name "$job" \
      --query '[].name' --output tsv --only-show-errors 2>/dev/null || true)"
    discovered=()
    while IFS= read -r candidate; do
      [[ -z "$candidate" ]] && continue
      [[ "$candidate" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || {
        fail "$purpose Job returned an invalid execution name"
      }
      [[ -z "${prior_executions[$candidate]+present}" ]] && discovered+=("$candidate")
    done <<<"$current_names"
    if ((${#discovered[@]} == 1)); then
      execution="${discovered[0]}"
      break
    fi
    ((${#discovered[@]} <= 1)) || fail "$purpose Job start produced ambiguous executions"
    sleep 5
  done
  [[ -n "$execution" ]] || fail "$purpose Job execution did not become observable"
  while ((SECONDS < deadline)); do
    status="$(timeout 60s az containerapp job execution show \
      --subscription "$EXPECTED_SUBSCRIPTION" \
      --resource-group "$resource_group" --name "$job" \
      --job-execution-name "$execution" \
      --query properties.status --output tsv --only-show-errors 2>/dev/null || true)"
    case "$status" in
      Succeeded) return ;;
      Failed) fail "$purpose Job failed" ;;
    esac
    sleep 10
  done
  fail "$purpose Job did not finish within ${budget}s"
}

for command_name in az azd curl date flock git python3 sha256sum stat tar terraform timeout uv; do
  require_command "$command_name"
done
[[ "$CONFIRM" == "0" || "$CONFIRM" == "1" ]] || fail "FDAI_AZD_CONFIRM must be 0 or 1"
[[ "$AZD_ENVIRONMENT" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]] || fail "FDAI_AZD_ENVIRONMENT must be a lowercase name"
[[ "$REGION" =~ ^[a-z0-9]+$ ]] || fail "FDAI_AZURE_REGION must be an Azure region token"
[[ "$REGION_SHORT" =~ ^[a-z0-9]{2,5}$ ]] || fail "FDAI_AZURE_REGION_SHORT must contain 2-5 lowercase letters or digits"
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "the checkout does not have a full immutable git revision"
[[ "${FDAI_AZD_IMAGE_BUILD_TIMEOUT_SECONDS:-3600}" =~ ^[1-9][0-9]*$ ]] || {
  fail "FDAI_AZD_IMAGE_BUILD_TIMEOUT_SECONDS must be a positive integer"
}

for variable_name in ${!TF_VAR_@} ${!TF_CLI_ARGS@}; do
  fail "clear ambient Terraform control before using the contributor path: $variable_name"
done
[[ -z "${TF_CLI_CONFIG_FILE:-}" ]] || {
  fail "clear ambient Terraform control before using the contributor path: TF_CLI_CONFIG_FILE"
}
for variable_name in ARM_CLIENT_ID ARM_CLIENT_SECRET ARM_CLIENT_CERTIFICATE_PATH ARM_OIDC_TOKEN ARM_USE_MSI ARM_USE_OIDC; do
  [[ -z "${!variable_name:-}" ]] || fail "the direct path requires interactive Azure CLI auth; clear $variable_name"
done

if [[ "$CONFIRM" == "1" && -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]]; then
  fail "apply requires a clean checkout so the built image matches the source revision"
fi

/bin/bash "$HERE/verify-azure-context.sh" "$EXPECTED_SUBSCRIPTION" "$EXPECTED_TENANT"
[[ "$(az cloud show --query name --output tsv --only-show-errors)" == "AzureCloud" ]] || {
  fail "the direct path currently supports Azure public cloud only"
}
ensure_contributor_azd_login "$TARGET_HAS_TERMINAL" "$EXPECTED_TENANT"

if azd env select "$AZD_ENVIRONMENT" --no-prompt >/dev/null 2>&1; then
  AZD_SUBSCRIPTION="$(azd env get-value AZURE_SUBSCRIPTION_ID --environment "$AZD_ENVIRONMENT" --no-prompt 2>/dev/null || true)"
  if [[ -n "$AZD_SUBSCRIPTION" && "$AZD_SUBSCRIPTION" != "$EXPECTED_SUBSCRIPTION" ]]; then
    fail "selected azd environment does not match AZURE_SUBSCRIPTION_ID"
  fi
else
  azd env new "$AZD_ENVIRONMENT" \
    --subscription "$EXPECTED_SUBSCRIPTION" --location "$REGION" --no-prompt >/dev/null
fi
azd env set --environment "$AZD_ENVIRONMENT" AZURE_SUBSCRIPTION_ID "$EXPECTED_SUBSCRIPTION" >/dev/null
azd env set --environment "$AZD_ENVIRONMENT" AZURE_LOCATION "$REGION" >/dev/null
azd env set --environment "$AZD_ENVIRONMENT" AZURE_TENANT_ID "$EXPECTED_TENANT" >/dev/null

DEPLOYER_OBJECT_ID="$(az ad signed-in-user show --query id --output tsv --only-show-errors)"
[[ "$DEPLOYER_OBJECT_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || {
  fail "the direct path requires an interactive Azure user identity"
}

[[ "$WORK_DIR" == /* && "$WORK_DIR" != "/" && ! -L "$WORK_DIR" ]] || {
  fail "FDAI_AZD_WORK_DIR must be an absolute non-symlink path"
}
install -d -m 0700 "$LOCK_ROOT"
exec 9>"$LOCK_ROOT/public-dev.lock"
flock -n 9 || fail "another public development deployment is already running"
install -d -m 0700 "$WORK_DIR"
trap cleanup EXIT
prepare_contributor_terraform "$REPO_ROOT" "$WORK_DIR"
write_local_backend_override "$PLATFORM_OVERRIDE" "$PLATFORM_STATE"
PLATFORM_OVERRIDE_CREATED=1

export TF_DATA_DIR="$PLATFORM_TF_DATA"
export ARM_SUBSCRIPTION_ID="$EXPECTED_SUBSCRIPTION"
export ARM_TENANT_ID="$EXPECTED_TENANT"
export ARM_USE_CLI=true
export TF_VAR_env=dev
export TF_VAR_region="$REGION"
export TF_VAR_region_short="$REGION_SHORT"
export TF_VAR_tenant_id="$EXPECTED_TENANT"
export TF_VAR_resource_name_suffix="$RESOURCE_NAME_SUFFIX"
export TF_VAR_postgres_admin_login=fdaiadmin
export TF_VAR_generate_initial_postgres_password=true
export TF_VAR_enable_private_networking=false
export TF_VAR_enable_private_postgres=false
export TF_VAR_enable_llm=true
export TF_VAR_llm_public_network_access_enabled=true
export TF_VAR_core_image="ghcr.io/dotnetpower/fdai/fdai-core-control-plane:sha-$SOURCE_COMMIT"
set_scheduled_jobs false

ensure_resource_providers
if [[ "$CONFIRM" == "1" ]]; then
  ensure_model_deployer_role
fi
resolve_models
platform_preview

if [[ "$CONFIRM" != "1" ]]; then
  log "preview complete; rerun with FDAI_AZD_CONFIRM=1 to perform the staged deployment"
  exit 0
fi

platform_apply
build_core_image
prepare_capability_license
bootstrap_database
write_local_backend_override "$CORE_OVERRIDE" "$CORE_STATE"
CORE_OVERRIDE_CREATED=1
deploy_core
set_scheduled_jobs true
platform_preview
platform_apply
wait_for_core

canary_job="$(terraform -chdir="$PLATFORM_ROOT" output -raw canary_job_name)"
inventory_job="$(terraform -chdir="$PLATFORM_ROOT" output -raw inventory_job_name)"
[[ -n "$canary_job" && -n "$inventory_job" ]] || fail "post-deploy verification Jobs are unavailable"
log "running the synthetic canary publisher"
run_job "$canary_job" "canary" 180
log "running the initial inventory reconciliation"
run_job "$inventory_job" "inventory" 1800

if [[ "$MODEL_ROLE_CREATED" == "1" ]]; then
  log "removing the temporary model provisioning role"
  timeout 60s az role assignment delete \
    --subscription "$EXPECTED_SUBSCRIPTION" \
    --assignee-object-id "$DEPLOYER_OBJECT_ID" \
    --role "Cognitive Services Contributor" \
    --scope "/subscriptions/$EXPECTED_SUBSCRIPTION" \
    --only-show-errors
  MODEL_ROLE_CREATED=0
fi

log "public development Core deployment and bounded verification completed"
log "local Terraform state is retained privately under $WORK_DIR"
