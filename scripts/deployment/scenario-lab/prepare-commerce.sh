#!/usr/bin/env bash
set -euo pipefail

readonly default_aks_store_commit="61b033448904a930f01d497ce7139aca87a1b12d"
readonly source_url="https://github.com/Azure-Samples/aks-store-demo.git"

repo_root="$(git rev-parse --show-toplevel)"
terraform_root="$repo_root/infra/scenario-lab"
output_dir="${1:-}"
storefront_hostname="${SCENARIO_LAB_STOREFRONT_HOSTNAME:-}"
tls_secret_name="${SCENARIO_LAB_STOREFRONT_TLS_SECRET_NAME:-}"
aks_store_commit="${SCENARIO_LAB_AKS_STORE_COMMIT:-$default_aks_store_commit}"
synthetic_authorization_ref="${SCENARIO_LAB_SYNTHETIC_AUTHORIZATION_REF:-}"
synthetic_authorization_expires_at="${SCENARIO_LAB_SYNTHETIC_AUTHORIZATION_EXPIRES_AT:-}"

if [[ -z "$output_dir" || "$output_dir" != /* || "$output_dir" == "/" ]]; then
  echo "prepare-commerce: an absolute non-root output directory is required." >&2
  exit 2
fi
if [[ ! "$storefront_hostname" =~ ^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$ ]]; then
  echo "prepare-commerce: SCENARIO_LAB_STOREFRONT_HOSTNAME must be a bounded DNS name." >&2
  exit 2
fi
if [[ ! "$tls_secret_name" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]]; then
  echo "prepare-commerce: SCENARIO_LAB_STOREFRONT_TLS_SECRET_NAME must be a Kubernetes name." >&2
  exit 2
fi
if [[ ! "$aks_store_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "prepare-commerce: SCENARIO_LAB_AKS_STORE_COMMIT must be an exact commit." >&2
  exit 2
fi
if [[ ! "$synthetic_authorization_ref" =~ ^[a-z0-9][a-z0-9._:/-]{7,191}$ ]]; then
  echo "prepare-commerce: SCENARIO_LAB_SYNTHETIC_AUTHORIZATION_REF must be a bounded reference." >&2
  exit 2
fi
if [[ ! "$synthetic_authorization_expires_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
  echo "prepare-commerce: SCENARIO_LAB_SYNTHETIC_AUTHORIZATION_EXPIRES_AT must use UTC RFC 3339." >&2
  exit 2
fi
for command_name in curl git helm jq kubectl terraform; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "prepare-commerce: required command is unavailable: $command_name" >&2
    exit 1
  }
done

umask 077
mkdir -p "$output_dir"
chmod 700 "$output_dir"
source_dir="$output_dir/aks-store-demo-$aks_store_commit"
commerce_file="$output_dir/commerce.env"
terraform_output="$(terraform -chdir="$terraform_root" output -json enforce_environment)"

commerce_enabled="$(jq -er '.commerce_enabled' <<<"$terraform_output")"
if [[ "$commerce_enabled" != "true" ]]; then
  echo "prepare-commerce: scenario-lab commerce dependencies are not enabled." >&2
  exit 1
fi
namespace="$(jq -er '.commerce_namespace' <<<"$terraform_output")"
identity_client_id="$(jq -er '.commerce_identity_client_id' <<<"$terraform_output")"
servicebus_hostname="$(jq -er '.commerce_servicebus_hostname' <<<"$terraform_output")"
cosmos_endpoint="$(jq -er '.commerce_cosmos_endpoint' <<<"$terraform_output")"

if [[ -d "$source_dir/.git" ]]; then
  resolved_commit="$(git -C "$source_dir" rev-parse HEAD)"
  if [[ "$resolved_commit" != "$aks_store_commit" ]]; then
    echo "prepare-commerce: retained AKS Store source has the wrong commit." >&2
    exit 1
  fi
else
  git clone --filter=blob:none --no-checkout "$source_url" "$source_dir"
  git -C "$source_dir" fetch --depth 1 origin "$aks_store_commit"
  git -C "$source_dir" checkout --detach "$aks_store_commit"
fi

kubectl create namespace "$namespace" --dry-run=client --output=json \
  | kubectl apply --filename=-
kubectl --namespace "$namespace" create serviceaccount aks-store-demo \
  --dry-run=client \
  --output=json \
  | jq --arg client_id "$identity_client_id" '
      .metadata.annotations["azure.workload.identity/client-id"] = $client_id
    ' \
  | kubectl apply --filename=-

helm upgrade --install aks-store-demo "$source_dir/charts/aks-store-demo" \
  --namespace "$namespace" \
  --set namespace="$namespace" \
  --set replicaCount=2 \
  --set useRabbitMQ=false \
  --set useDocumentDB=false \
  --set useAzureAd=true \
  --set managedIdentityName=aks-store-demo \
  --set managedIdentityClientId="$identity_client_id" \
  --set orderService.queueHost="$servicebus_hostname" \
  --set orderService.queueName=orders \
  --set makelineService.orderQueueHost="$servicebus_hostname" \
  --set makelineService.orderQueueName=orders \
  --set makelineService.orderDBApi=cosmosdbsql \
  --set makelineService.orderDBUri="$cosmos_endpoint" \
  --set makelineService.orderDBName=orderdb \
  --set makelineService.orderDBContainerName=orders \
  --set storeFront.serviceType=ClusterIP \
  --set storeAdmin.serviceType=ClusterIP \
  --set virtualCustomer.ordersPerHour=100 \
  --set virtualWorker.ordersPerHour=100 \
  --wait \
  --timeout 15m

jq -n \
  --arg namespace "$namespace" \
  --arg hostname "$storefront_hostname" \
  --arg tls_secret "$tls_secret_name" \
  '{
    apiVersion: "networking.k8s.io/v1",
    kind: "Ingress",
    metadata: {
      name: "aks-store-front",
      namespace: $namespace
    },
    spec: {
      ingressClassName: "webapprouting.kubernetes.azure.com",
      tls: [{hosts: [$hostname], secretName: $tls_secret}],
      rules: [{
        host: $hostname,
        http: {
          paths: [{
            path: "/",
            pathType: "Prefix",
            backend: {service: {name: "store-front", port: {number: 80}}}
          }]
        }
      }]
    }
  }' \
  | kubectl apply --filename=-

jq -n --arg namespace "$namespace" '{
  apiVersion: "networking.k8s.io/v1",
  kind: "NetworkPolicy",
  metadata: {name: "protect-store-admin", namespace: $namespace},
  spec: {
    podSelector: {matchLabels: {app: "store-admin"}},
    policyTypes: ["Ingress"],
    ingress: [{from: [{podSelector: {}}]}]
  }
}' | kubectl apply --filename=-

kubectl --namespace "$namespace" label service product-service \
  app=product-service \
  --overwrite
kubectl wait \
  --for=condition=Established \
  crd/servicemonitors.azmonitoring.coreos.com \
  --timeout=5m
kubectl --namespace "$namespace" apply \
  --filename="$source_dir/kustomize/overlays/kaito/product-service-monitor.yaml"
kubectl --namespace "$namespace" rollout status deployment/store-front --timeout=10m
kubectl --namespace "$namespace" rollout status deployment/order-service --timeout=10m
kubectl --namespace "$namespace" rollout status deployment/makeline-service --timeout=10m

storefront_url="https://$storefront_hostname"
curl --fail --silent --show-error \
  --proto '=https' \
  --tlsv1.2 \
  --connect-timeout 10 \
  --max-time 30 \
  "$storefront_url/health" >/dev/null

printf 'export FDAI_AKS_COMMERCE_STOREFRONT_URL=%q\n' "$storefront_url" >"$commerce_file"
printf 'export FDAI_AKS_COMMERCE_QUEUE_NAME=%q\n' "orders" >>"$commerce_file"
printf 'export FDAI_AKS_COMMERCE_NAMESPACE=%q\n' "$namespace" >>"$commerce_file"
printf 'export FDAI_AKS_COMMERCE_SYNTHETIC_AUTHORIZATION_REF=%q\n' \
  "$synthetic_authorization_ref" >>"$commerce_file"
printf 'export FDAI_AKS_COMMERCE_SYNTHETIC_AUTHORIZATION_EXPIRES_AT=%q\n' \
  "$synthetic_authorization_expires_at" >>"$commerce_file"
chmod 600 "$commerce_file"
printf 'prepare-commerce: storefront ready at %s\n' "$storefront_url"
