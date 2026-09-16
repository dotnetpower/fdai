#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
terraform_root="$repo_root/infra/scenario-lab"
output_dir="${1:-}"
chaos_mesh_version="${SCENARIO_LAB_CHAOS_MESH_CHART_VERSION:-}"

if [[ -z "$output_dir" || "$output_dir" != /* || "$output_dir" == "/" ]]; then
  echo "prepare-runner: an absolute non-root output directory is required." >&2
  exit 2
fi
if [[ ! "$chaos_mesh_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "prepare-runner: SCENARIO_LAB_CHAOS_MESH_CHART_VERSION must be an exact semantic version." >&2
  exit 2
fi
for command_name in az helm jq kubectl kubelogin python3 terraform timeout; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "prepare-runner: required command is unavailable: $command_name" >&2
    exit 1
  }
done

umask 077
mkdir -p "$output_dir"
chmod 700 "$output_dir"
kubeconfig="$output_dir/kubeconfig"
password_file="$output_dir/mysql-password"
environment_file="$output_dir/enforce.env"
store_manifest="$output_dir/aks-store-demo.yaml"
store_front_url_file="$output_dir/store-front-url"
terraform_output="$(terraform -chdir="$terraform_root" output -json enforce_environment)"

subscription_id="$(jq -er '.subscription_id' <<<"$terraform_output")"
resource_group="$(jq -er '.resource_group' <<<"$terraform_output")"
aks_cluster_name="$(jq -er '.aks_cluster_name' <<<"$terraform_output")"
vm_name="$(jq -er '.vm_name' <<<"$terraform_output")"
store_front_dns_label="$(jq -er '.store_front_dns_label' <<<"$terraform_output")"
store_front_hostname="$(jq -er '.store_front_hostname' <<<"$terraform_output")"

active_subscription="$(az account show --query id --output tsv --only-show-errors)"
if [[ "$active_subscription" != "$subscription_id" ]]; then
  echo "prepare-runner: active Azure subscription does not match the Terraform output." >&2
  exit 1
fi

az aks get-credentials \
  --resource-group "$resource_group" \
  --name "$aks_cluster_name" \
  --file "$kubeconfig" \
  --overwrite-existing \
  --public-fqdn \
  --only-show-errors
export KUBECONFIG="$kubeconfig"
kubelogin convert-kubeconfig --kubeconfig "$kubeconfig" -l msi

helm repo add chaos-mesh https://charts.chaos-mesh.org --force-update >/dev/null
helm show chart chaos-mesh/chaos-mesh --version "$chaos_mesh_version" >/dev/null
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --version "$chaos_mesh_version" \
  --namespace chaos-mesh \
  --create-namespace \
  --set dashboard.create=false \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
  --wait \
  --timeout 15m

kubectl create namespace fdai-sre-demo --dry-run=client --output=json \
  | kubectl apply --filename=-
python3 "$repo_root/scripts/deployment/scenario-lab/render_aks_store_demo.py" \
  "$store_manifest" \
  "$store_front_dns_label"
kubectl --namespace fdai-sre-demo apply --filename="$store_manifest"
kubectl --namespace fdai-sre-demo delete deployment,service api-backend \
  --ignore-not-found=true
kubectl --namespace fdai-sre-demo rollout status statefulset/documentdb --timeout=15m
kubectl --namespace fdai-sre-demo rollout status statefulset/rabbitmq --timeout=15m
kubectl --namespace fdai-sre-demo wait --for=condition=available deployment \
  --all --timeout=15m
kubectl --namespace fdai-sre-demo wait \
  --for=jsonpath='{.status.loadBalancer.ingress[0].ip}' \
  service/store-front \
  --timeout=15m
store_front_ip="$(
  kubectl --namespace fdai-sre-demo get service/store-front \
    --output=jsonpath='{.status.loadBalancer.ingress[0].ip}'
)"
python3 "$repo_root/scripts/deployment/scenario-lab/verify_store_front_domain.py" \
  "$store_front_hostname" \
  "$store_front_ip"
printf 'http://%s\n' "$store_front_hostname" >"$store_front_url_file"
chmod 600 "$store_front_url_file"

readonly vm_run_command_max_attempts=20
readonly vm_run_command_retry_seconds=15
readonly vm_run_command_deadline_seconds=300

run_vm_cloud_init_check() {
  local attempt=1
  local command_output=""
  local deadline=$((SECONDS + vm_run_command_deadline_seconds))

  while ((attempt <= vm_run_command_max_attempts)); do
    local remaining_seconds=$((deadline - SECONDS))
    local command_status=0
    if ((remaining_seconds <= 0)); then
      echo "prepare-runner: private stress VM readiness authorization did not propagate within five minutes." >&2
      return 1
    fi
    if command_output="$(timeout --foreground "${remaining_seconds}s" az vm run-command invoke \
      --resource-group "$resource_group" \
      --name "$vm_name" \
      --command-id RunShellScript \
      --scripts 'cloud-init status --wait --long' \
      --query 'value[0].message' \
      --output tsv \
      --only-show-errors 2>&1)"; then
      printf '%s' "$command_output"
      return 0
    else
      command_status=$?
    fi
    if ((command_status == 124)); then
      echo "prepare-runner: private stress VM readiness command exceeded its five-minute deadline." >&2
      return 1
    fi
    if ! grep -Eq '\(AuthorizationFailed\)|Code:[[:space:]]*AuthorizationFailed' \
      <<<"$command_output"; then
      echo "prepare-runner: private stress VM readiness command failed." >&2
      return 1
    fi
    if ((attempt == vm_run_command_max_attempts || SECONDS + vm_run_command_retry_seconds >= deadline)); then
      echo "prepare-runner: private stress VM readiness authorization did not propagate within five minutes." >&2
      return 1
    fi
    printf 'prepare-runner: waiting for private stress VM readiness authorization (%s/%s).\n' \
      "$attempt" "$vm_run_command_max_attempts" >&2
    command_output=""
    sleep "$vm_run_command_retry_seconds"
    ((attempt += 1))
  done
}

cloud_init_status="$(run_vm_cloud_init_check)"
grep -Fq 'status: done' <<<"$cloud_init_status" || {
  echo "prepare-runner: private stress VM cloud-init did not complete." >&2
  exit 1
}

jq -er '.mysql_password' <<<"$terraform_output" >"$password_file"
chmod 600 "$password_file"

write_export() {
  local key="$1"
  local value="$2"
  printf 'export %s=%q\n' "$key" "$value" >>"$environment_file"
}

: >"$environment_file"
write_export KUBECONFIG "$kubeconfig"
write_export FDAI_ENFORCE_SUB_ID "$subscription_id"
write_export FDAI_ENFORCE_RG "$resource_group"
write_export FDAI_ENFORCE_AKS_CONTEXT "$(kubectl config current-context)"
write_export FDAI_ENFORCE_NS "$(jq -er '.workload_namespace' <<<"$terraform_output")"
write_export FDAI_ENFORCE_CHAOS_NS "$(jq -er '.chaos_namespace' <<<"$terraform_output")"
write_export FDAI_ENFORCE_BACKEND_DEPLOY "$(jq -er '.backend_deployment' <<<"$terraform_output")"
write_export FDAI_ENFORCE_BACKEND_SVC "$(jq -er '.backend_service' <<<"$terraform_output")"
write_export FDAI_ENFORCE_BACKEND_LABEL "$(jq -er '.backend_label' <<<"$terraform_output")"
write_export FDAI_ENFORCE_BACKEND_CONTAINER "$(jq -er '.backend_container' <<<"$terraform_output")"
write_export FDAI_ENFORCE_BACKEND_REPLICAS "$(jq -er '.backend_replicas' <<<"$terraform_output")"
write_export FDAI_ENFORCE_BACKEND_IMAGE "$(jq -er '.backend_image' <<<"$terraform_output")"
write_export FDAI_STORE_FRONT_URL "http://$store_front_hostname"
write_export FDAI_ENFORCE_VM "$vm_name"
write_export FDAI_ENFORCE_MYSQL_HOST "$(jq -er '.mysql_host' <<<"$terraform_output")"
write_export FDAI_ENFORCE_MYSQL_USER "$(jq -er '.mysql_user' <<<"$terraform_output")"
write_export FDAI_ENFORCE_MYSQL_SERVER "$(jq -er '.mysql_server' <<<"$terraform_output")"
write_export FDAI_ENFORCE_MYSQL_PW_FILE "$password_file"
write_export FDAI_ENFORCE_AOAI_ENDPOINT "$(jq -er '.azure_openai_endpoint' <<<"$terraform_output")"
write_export FDAI_ENFORCE_AOAI_DEPLOYMENT "$(jq -er '.azure_openai_deployment' <<<"$terraform_output")"
chmod 600 "$environment_file"

printf '%s\n' "$environment_file"
