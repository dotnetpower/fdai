#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_ACTOR:?GITHUB_ACTOR is required}"
: "${GHCR_TOKEN:?GHCR_TOKEN is required}"
: "${GITHUB_ENV:?GITHUB_ENV is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"

operation="verify-and-bind"
terraform_dir="infra"
case "${1:-}" in
  --verify-only)
    operation="verify-only"
    terraform_dir="${2:-infra}"
    (( $# <= 2 )) || {
      echo "usage: bind_core_runtime_image.sh [--verify-only|--bind-verified] [terraform-dir]" >&2
      exit 2
    }
    ;;
  --bind-verified)
    operation="bind-verified"
    terraform_dir="${2:-infra}"
    (( $# <= 2 )) || {
      echo "usage: bind_core_runtime_image.sh [--verify-only|--bind-verified] [terraform-dir]" >&2
      exit 2
    }
    ;;
  "") ;;
  *)
    (( $# == 1 )) || {
      echo "usage: bind_core_runtime_image.sh [--verify-only|--bind-verified] [terraform-dir]" >&2
      exit 2
    }
    terraform_dir="$1"
    ;;
esac

if [[ ! "$GITHUB_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "GITHUB_REPOSITORY must be an owner/repository pair." >&2
  exit 1
fi
checkout_revision="$(git rev-parse HEAD)"
revision="${RUNTIME_IMAGE_REVISION:-$checkout_revision}"
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "runtime_image_revision must be a lowercase git SHA." >&2
  exit 1
fi
if ! git merge-base --is-ancestor "$revision" "$checkout_revision"; then
  echo "runtime image revision must be an ancestor of the workflow checkout." >&2
  exit 1
fi

runtime_image_profile="${RUNTIME_IMAGE_PROFILE:-core-control-plane}"
source_repository="${GITHUB_REPOSITORY,,}/fdai-core-control-plane"
target_image="fdai"
case "$runtime_image_profile" in
  core-control-plane) ;;
  cost-governance)
    source_repository="${GITHUB_REPOSITORY,,}/fdai-cost-governance"
    target_image="fdai-cost-governance"
    ;;
  *)
    echo "runtime image profile must be core-control-plane or cost-governance." >&2
    exit 1
    ;;
esac
expected_signer_workflow="${GITHUB_REPOSITORY}/.github/workflows/container-supply-chain.yml"
attestation_signer_workflow="${ATTESTATION_SIGNER_WORKFLOW:-$expected_signer_workflow}"
if [[ "$attestation_signer_workflow" != "$expected_signer_workflow" ]]; then
  echo "Core runtime attestations must use the container supply-chain signer workflow." >&2
  exit 1
fi
provenance_predicate_type="https://slsa.dev/provenance/v1"

umask 077
private_dir="$(mktemp -d "$RUNNER_TEMP/fdai-core-image.XXXXXX")"
docker_config="$(mktemp -d "$RUNNER_TEMP/fdai-ghcr-docker.XXXXXX")"
chmod 0700 "$private_dir"
chmod 0700 "$docker_config"
trap 'rm -rf -- "$private_dir"; rm -rf -- "$docker_config"' EXIT
verified_source_digest=""

verify_runtime_image() {
  local bearer_header_file="$private_dir/registry-authorization.header"
  local netrc_file="$private_dir/registry.netrc"
  local registry_token
  local source_digest

  printf 'machine ghcr.io\nlogin %s\npassword %s\n' \
    "$GITHUB_ACTOR" "$GHCR_TOKEN" > "$netrc_file"
  if ! python3 - "$docker_config/config.json" <<'PY'
import base64
import json
import os
import sys

actor = os.environ["GITHUB_ACTOR"]
token = os.environ["GHCR_TOKEN"]
if any(character in actor or character in token for character in "\r\n"):
    raise SystemExit("GHCR credentials must not contain line breaks")
encoded = base64.b64encode((actor + ":" + token).encode()).decode("ascii")
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump({"auths": {"ghcr.io": {"auth": encoded}}}, stream, separators=(",", ":"))
    stream.write("\n")
PY
  then
    echo "temporary GHCR authentication failed." >&2
    exit 1
  fi
  chmod 0600 "$netrc_file" "$docker_config/config.json"

  registry_token="$(
    curl --fail --silent --show-error --retry 3 --retry-delay 2 \
      --retry-all-errors --retry-max-time 60 --connect-timeout 5 --max-time 30 \
      --netrc-file "$netrc_file" \
      "https://ghcr.io/token?scope=repository:${source_repository}:pull" \
      | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])'
  )"
  if [[ -z "$registry_token" || "$registry_token" == *$'\r'* || "$registry_token" == *$'\n'* ]]; then
    echo "GHCR returned an invalid registry access token." >&2
    exit 1
  fi
  printf 'Authorization: Bearer %s\n' "$registry_token" > "$bearer_header_file"
  unset registry_token

  source_digest="$(
    curl --fail --silent --show-error --head --retry 3 --retry-delay 2 \
      --retry-all-errors --retry-max-time 60 --connect-timeout 5 --max-time 30 \
      --header "@$bearer_header_file" \
      --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
      "https://ghcr.io/v2/${source_repository}/manifests/sha-${revision}" \
      | tr -d '\r' \
      | awk -F': ' 'tolower($1) == "docker-content-digest" {print $2}'
  )"
  if [[ ! "$source_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "verified runtime image tag did not resolve to one manifest digest." >&2
    exit 1
  fi
  if ! DOCKER_CONFIG="$docker_config" timeout 60s gh attestation verify \
    "oci://ghcr.io/${source_repository}@${source_digest}" \
    --bundle-from-oci \
    --repo "$GITHUB_REPOSITORY" \
    --source-digest "$revision" \
    --predicate-type "$provenance_predicate_type" \
    --signer-workflow "$attestation_signer_workflow" >/dev/null; then
    echo "verified runtime image attestation check failed. Core runtime image provenance verification failed." >&2
    exit 1
  fi
  echo "Verified exact runtime image provenance."

  verified_source_digest="$source_digest"
  {
    printf 'FDAI_VERIFIED_RUNTIME_IMAGE_REPOSITORY=%s\n' "$source_repository"
    printf 'FDAI_VERIFIED_RUNTIME_IMAGE_REVISION=%s\n' "$revision"
    printf 'FDAI_VERIFIED_RUNTIME_IMAGE_DIGEST=%s\n' "$source_digest"
    printf 'FDAI_VERIFIED_RUNTIME_IMAGE_PROFILE=%s\n' "$runtime_image_profile"
  } >> "$GITHUB_ENV"
}

load_verified_runtime_image() {
  if [[ "${FDAI_VERIFIED_RUNTIME_IMAGE_REPOSITORY:-}" != "$source_repository" ||
        "${FDAI_VERIFIED_RUNTIME_IMAGE_REVISION:-}" != "$revision" ||
        "${FDAI_VERIFIED_RUNTIME_IMAGE_PROFILE:-}" != "$runtime_image_profile" ||
        ! "${FDAI_VERIFIED_RUNTIME_IMAGE_DIGEST:-}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Core runtime image binding requires exact successful provenance verification." >&2
    exit 1
  fi
  verified_source_digest="$FDAI_VERIFIED_RUNTIME_IMAGE_DIGEST"
}

bind_verified_runtime_image() {
  local import_body="$private_dir/acr-import.json"
  local login_server=""
  local readback_deadline
  local registry_id
  local registry_name
  local source_digest="$verified_source_digest"
  local target_digest=""

  if [[ -n "${FDAI_ACR_LOGIN_SERVER:-}" ]]; then
    login_server="$FDAI_ACR_LOGIN_SERVER"
  else
    login_server="$(terraform -chdir="$terraform_dir" output -raw container_registry_login_server)"
  fi
  login_server="${login_server#https://}"
  login_server="${login_server%/}"
  login_server="${login_server,,}"
  if [[ ! "$login_server" =~ ^[a-z0-9]+[.]azurecr[.]io$ ]]; then
    echo "Terraform returned an invalid ACR login server." >&2
    exit 1
  fi
  registry_name="${login_server%%.*}"
  echo "Resolved the target ACR login host."
  if [[ "${PROMOTE_RUNTIME_IMAGE:-false}" == "true" ]]; then
    if ! registry_id="$(
      az acr show \
        --name "$registry_name" \
        --query id \
        --output tsv \
        --only-show-errors
    )"; then
      echo "target ACR lookup failed." >&2
      exit 1
    fi
    if [[ ! "$registry_id" =~ ^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft[.]ContainerRegistry/registries/[^/]+$ ]]; then
      echo "target ACR lookup returned an invalid resource id." >&2
      exit 1
    fi
    echo "Resolved the target ACR resource."
    SOURCE_REPOSITORY="$source_repository" SOURCE_DIGEST="$source_digest" \
      TARGET_IMAGE="$target_image" TARGET_REVISION="$revision" \
      python3 - "$import_body" <<'PY'
import json
import os
import sys

payload = {
    "source": {
        "sourceImage": f"{os.environ['SOURCE_REPOSITORY']}@{os.environ['SOURCE_DIGEST']}",
        "registryUri": "ghcr.io",
        "credentials": {
            "username": os.environ["GITHUB_ACTOR"],
            "password": os.environ["GHCR_TOKEN"],
        },
    },
    "targetTags": [f"{os.environ['TARGET_IMAGE']}:sha-{os.environ['TARGET_REVISION']}"],
    "mode": "Force",
}
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
PY
    if ! timeout 600s az rest --method post \
      --uri "https://management.azure.com${registry_id}/importImage?api-version=2023-01-01-preview" \
      --body "@$import_body" --output none; then
      echo "exact runtime image import request failed." >&2
      exit 1
    fi
    : > "$import_body"
    echo "Accepted the exact runtime image import request."
  fi

  readback_deadline=$((SECONDS + 600))
  while ((SECONDS < readback_deadline)); do
    target_digest="$(
      timeout 30s az acr manifest list-metadata \
        --registry "$registry_name" \
        --name "$target_image" \
        --query "[?tags != null && contains(tags, 'sha-${revision}')].digest | [0]" \
        --output tsv --only-show-errors || true
    )"
    [[ "$target_digest" == "$source_digest" ]] && break
    sleep 10
  done
  if [[ -z "$target_digest" ]]; then
    echo "Verified runtime image is not present in ACR; submit an authorized plan with promote_runtime_image=true." >&2
    exit 1
  fi
  if [[ "$target_digest" != "$source_digest" ]]; then
    echo "ACR runtime image digest does not match the verified GHCR subject." >&2
    exit 1
  fi
  echo "Verified the exact runtime image digest in ACR."
  {
    echo "TF_VAR_core_image=${login_server}/${target_image}@${target_digest}"
    if [[ "$runtime_image_profile" == "cost-governance" ]]; then
      echo "TF_VAR_cost_governance_image=${login_server}/${target_image}@${target_digest}"
    fi
    echo "FDAI_RUNTIME_IMAGE_PROFILE=${runtime_image_profile}"
    echo "FDAI_RUNTIME_IMAGE_REVISION=${revision}"
    echo "FDAI_RUNTIME_IMAGE_DIGEST=${target_digest}"
  } >> "$GITHUB_ENV"
}

case "$operation" in
  verify-only)
    verify_runtime_image
    ;;
  bind-verified)
    load_verified_runtime_image
    bind_verified_runtime_image
    ;;
  verify-and-bind)
    verify_runtime_image
    bind_verified_runtime_image
    ;;
esac
