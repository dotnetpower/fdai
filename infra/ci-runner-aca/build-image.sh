#!/usr/bin/env bash
# Build the ephemeral CI runner image in Azure Container Registry from the declared toolchain.
#
# Usage: build-image.sh REGISTRY_NAME [TAG]
# Uses the signed-in Azure identity; no credential is read or printed. The build context is a
# small temporary directory so only the manifest-owned files leave this checkout.
set -euo pipefail

registry="${1:?registry name is required}"
repository_root="$(git rev-parse --show-toplevel)"
tag="${2:-$(git -C "$repository_root" rev-parse --short=12 HEAD)}"
[[ "$registry" =~ ^[a-z0-9]{5,50}$ ]] || { echo "invalid registry name" >&2; exit 1; }
[[ "$tag" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || { echo "invalid image tag" >&2; exit 1; }

context="$(mktemp -d)"
trap 'rm -rf "$context"' EXIT
cp "$repository_root"/infra/ci-runner/{toolchain.json,verify-toolchain.py,provision-toolchain.sh} "$context/"
cp "$repository_root"/infra/ci-runner-aca/{Dockerfile,entrypoint.sh} "$context/"

az acr build --registry "$registry" --image "fdai-ci-runner:${tag}" --platform linux/amd64 "$context"
echo "fdai-ci-runner:${tag}"
