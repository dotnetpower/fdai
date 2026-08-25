#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
terraform_root="$repo_root/infra/scenario-lab"
output_dir="${1:-}"
backend_image="${SCENARIO_LAB_BACKEND_IMAGE:-}"
chaos_mesh_version="${SCENARIO_LAB_CHAOS_MESH_CHART_VERSION:-}"

if [[ -z "$output_dir" || "$output_dir" != /* || "$output_dir" == "/" ]]; then
  echo "prepare-runner: an absolute non-root output directory is required." >&2
  exit 2
fi
if [[ ! "$backend_image" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "prepare-runner: SCENARIO_LAB_BACKEND_IMAGE must be pinned by sha256 digest." >&2
  exit 2
fi
if [[ ! "$chaos_mesh_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "prepare-runner: SCENARIO_LAB_CHAOS_MESH_CHART_VERSION must be an exact semantic version." >&2
  exit 2
fi
for command_name in az helm jq kubectl kubelogin terraform; do
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
terraform_output="$(terraform -chdir="$terraform_root" output -json enforce_environment)"

subscription_id="$(jq -er '.subscription_id' <<<"$terraform_output")"
resource_group="$(jq -er '.resource_group' <<<"$terraform_output")"
aks_cluster_name="$(jq -er '.aks_cluster_name' <<<"$terraform_output")"
vm_name="$(jq -er '.vm_name' <<<"$terraform_output")"

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
kubectl --namespace fdai-sre-demo create deployment api-backend \
  --image="$backend_image" \
  --replicas=3 \
  --dry-run=client \
  --output=json \
  | jq '
      .spec.template.spec.containers[0].name = "web"
      | .spec.template.spec.containers[0].ports = [{"containerPort": 80}]
      | .spec.template.spec.containers[0].resources = {
          "requests": {"cpu": "50m", "memory": "64Mi"},
          "limits": {"cpu": "500m", "memory": "512Mi"}
        }
    ' \
  | kubectl apply --filename=-
kubectl --namespace fdai-sre-demo expose deployment api-backend \
  --name=api-backend \
  --port=80 \
  --target-port=80 \
  --type=ClusterIP \
  --dry-run=client \
  --output=json \
  | kubectl apply --filename=-
kubectl --namespace fdai-sre-demo rollout status deployment/api-backend --timeout=10m

cloud_init_status="$(az vm run-command invoke \
  --resource-group "$resource_group" \
  --name "$vm_name" \
  --command-id RunShellScript \
  --scripts 'cloud-init status --wait --long' \
  --query 'value[0].message' \
  --output tsv \
  --only-show-errors)"
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
write_export FDAI_ENFORCE_VM "$vm_name"
write_export FDAI_ENFORCE_MYSQL_HOST "$(jq -er '.mysql_host' <<<"$terraform_output")"
write_export FDAI_ENFORCE_MYSQL_USER "$(jq -er '.mysql_user' <<<"$terraform_output")"
write_export FDAI_ENFORCE_MYSQL_SERVER "$(jq -er '.mysql_server' <<<"$terraform_output")"
write_export FDAI_ENFORCE_MYSQL_PW_FILE "$password_file"
write_export FDAI_ENFORCE_AOAI_ENDPOINT "$(jq -er '.azure_openai_endpoint' <<<"$terraform_output")"
write_export FDAI_ENFORCE_AOAI_DEPLOYMENT "$(jq -er '.azure_openai_deployment' <<<"$terraform_output")"
chmod 600 "$environment_file"

printf '%s\n' "$environment_file"
