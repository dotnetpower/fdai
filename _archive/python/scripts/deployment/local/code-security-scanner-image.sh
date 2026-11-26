#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
image_label="org.fdai.code-security.build-input-digest"
dockerfile="services/core-control-plane/docker/code-security-scanner.Dockerfile"
image_inputs=(
  .dockerignore
  "$dockerfile"
  services/core-control-plane/docker/code-security-scanner-entrypoint.sh
  pyproject.toml
  uv.lock
  LICENSE
  README.md
  evaluation-sdk/pyproject.toml
  benchmarks/sregym/pyproject.toml
  benchmarks/cybergym/pyproject.toml
  extensions/code-assurance/pyproject.toml
  extensions/cost-governance/pyproject.toml
  services/operator-service/pyproject.toml
  services/document-ingestion-api/pyproject.toml
  services/document-processing-worker/pyproject.toml
  services/isolated-executor/pyproject.toml
  services/system-knowledge-service/pyproject.toml
  packages/github-app-auth
  packages/service-contracts
  packages/runtime-diagnostics
  services/core-control-plane
  rule-catalog/code-security
  config
)

usage() {
  echo "Usage: $0 inputs | digest | verify IMAGE DIGEST | ensure IMAGE DIGEST" >&2
  exit 2
}

valid_digest() {
  [[ "$1" =~ ^[0-9a-f]{64}$ ]]
}

valid_image() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]]
}

image_digest_label() {
  local image="$1"
  docker image inspect \
    --format "{{ index .Config.Labels \"$image_label\" }}" \
    "$image" 2>/dev/null || true
}

verify_image() {
  local image="$1"
  local expected="$2"
  local actual
  actual="$(image_digest_label "$image")"
  if [[ -z "$actual" || "$actual" == "<no value>" ]]; then
    echo "code-security scanner image is absent or missing its build-input label: $image" >&2
    return 1
  fi
  if [[ "$actual" != "$expected" ]]; then
    echo "code-security scanner image is stale: $image (expected=$expected actual=$actual)" >&2
    return 1
  fi
}

command="${1:-}"
case "$command" in
  inputs)
    printf '%s\n' "${image_inputs[@]}"
    ;;
  digest)
    [[ $# -eq 1 ]] || usage
    exec "$repo_root/.venv/bin/python" \
      "$repo_root/scripts/automation/local-service-input-digest.py" \
      --paths-only \
      "${image_inputs[@]}"
    ;;
  verify)
    [[ $# -eq 3 ]] || usage
    valid_image "$2" || {
      echo "code-security scanner image reference is invalid" >&2
      exit 2
    }
    valid_digest "$3" || {
      echo "code-security scanner build-input digest is invalid" >&2
      exit 2
    }
    verify_image "$2" "$3"
    ;;
  ensure)
    [[ $# -eq 3 ]] || usage
    image="$2"
    expected="$3"
    valid_image "$image" || {
      echo "code-security scanner image reference is invalid" >&2
      exit 2
    }
    valid_digest "$expected" || {
      echo "code-security scanner build-input digest is invalid" >&2
      exit 2
    }
    if verify_image "$image" "$expected" 2>/dev/null; then
      exit 0
    fi
    echo "code-security scanner image rebuild required: $image" >&2
    if ! docker build \
      -f "$repo_root/$dockerfile" \
      --target runtime \
      --build-arg "FDAI_CODE_SECURITY_BUILD_INPUT_DIGEST=$expected" \
      -t "$image" \
      "$repo_root"; then
      echo "code-security scanner image rebuild failed: $image" >&2
      exit 1
    fi
    if ! verify_image "$image" "$expected"; then
      echo "code-security scanner image post-build label verification failed: $image" >&2
      exit 1
    fi
    ;;
  *)
    usage
    ;;
esac
