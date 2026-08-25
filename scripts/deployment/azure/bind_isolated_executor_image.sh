#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_ACTOR:?GITHUB_ACTOR is required}"
: "${GHCR_TOKEN:?GHCR_TOKEN is required}"
: "${GITHUB_ENV:?GITHUB_ENV is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"

terraform_dir="${1:-infra}"
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

source_repository="${GITHUB_REPOSITORY,,}/fdai-core-control-plane"
netrc_file="$(mktemp "$RUNNER_TEMP/fdai-ghcr-netrc.XXXXXX")"
import_body="$(mktemp "$RUNNER_TEMP/fdai-acr-import.XXXXXX.json")"
chmod 0600 "$netrc_file" "$import_body"
trap 'rm -f -- "$netrc_file" "$import_body"' EXIT
printf 'machine ghcr.io\nlogin %s\npassword %s\n' \
  "$GITHUB_ACTOR" "$GHCR_TOKEN" > "$netrc_file"
registry_token="$(
  curl --fail --silent --show-error --retry 3 --retry-delay 2 \
    --retry-all-errors --retry-max-time 60 --connect-timeout 5 --max-time 30 \
    --netrc-file "$netrc_file" \
    "https://ghcr.io/token?scope=repository:${source_repository}:pull" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])'
)"
echo "::add-mask::$registry_token"
source_digest="$(
  curl --fail --silent --show-error --head --retry 3 --retry-delay 2 \
    --retry-all-errors --retry-max-time 60 --connect-timeout 5 --max-time 30 \
    -H "Authorization: Bearer $registry_token" \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
    "https://ghcr.io/v2/${source_repository}/manifests/sha-${revision}" \
    | tr -d '\r' \
    | awk -F': ' 'tolower($1) == "docker-content-digest" {print $2}'
)"
unset registry_token
if [[ ! "$source_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "verified runtime image tag did not resolve to one manifest digest." >&2
  exit 1
fi
timeout 60s gh attestation verify \
  "oci://ghcr.io/${source_repository}@${source_digest}" \
  --repo "$GITHUB_REPOSITORY" >/dev/null

login_server="$(terraform -chdir="$terraform_dir" output -raw container_registry_login_server)"
registry_name="${login_server%%.*}"
if [[ ! "$registry_name" =~ ^[a-z0-9]+$ ]]; then
  echo "Terraform returned an invalid ACR login server." >&2
  exit 1
fi
if [[ "${PROMOTE_RUNTIME_IMAGE:-false}" == "true" ]]; then
  registry_id="$(az acr show --name "$registry_name" --query id --output tsv)"
  SOURCE_REPOSITORY="$source_repository" SOURCE_DIGEST="$source_digest" \
    TARGET_REVISION="$revision" python3 - "$import_body" <<'PY'
import json
import os
import sys

payload = {
    "source": {
        "sourceImage": f"{os.environ['SOURCE_REPOSITORY']}@{os.environ['SOURCE_DIGEST']}",
        "registryUri": "https://ghcr.io",
        "credentials": {
            "username": os.environ["GITHUB_ACTOR"],
            "password": os.environ["GHCR_TOKEN"],
        },
    },
    "targetTags": [f"fdai:sha-{os.environ['TARGET_REVISION']}"],
    "mode": "Force",
}
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
PY
  timeout 600s az rest --method post \
    --uri "https://management.azure.com${registry_id}/importImage?api-version=2023-01-01-preview" \
    --body "@$import_body" --output none
  : > "$import_body"
fi

target_digest=""
readback_deadline=$((SECONDS + 600))
while ((SECONDS < readback_deadline)); do
  target_digest="$(
    timeout 30s az acr manifest list-metadata \
      --registry "$registry_name" \
      --name fdai \
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
{
  echo "TF_VAR_core_image=${login_server}/fdai@${target_digest}"
  echo "FDAI_RUNTIME_IMAGE_REVISION=${revision}"
  echo "FDAI_RUNTIME_IMAGE_DIGEST=${target_digest}"
} >> "$GITHUB_ENV"
