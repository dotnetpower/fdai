#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 ]]; then
  printf '%s\n' 'Usage: build-controller-image.sh python:3.13-slim@sha256:<digest> registry/repository:tag' >&2
  exit 2
fi
base_image=$1
target_image=$2
if [[ ! "$base_image" =~ ^(docker.io/library/)?python:3\.13([.][0-9]+)?-slim(-[a-z]+)?@sha256:[0-9a-f]{64}$ ]]; then
  printf '%s\n' 'A reviewed digest-pinned public Python 3.13 slim base image is required.' >&2
  exit 2
fi
if [[ ! "$target_image" =~ ^[a-z0-9][a-z0-9.-]+\.azurecr\.io/[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_.-]+$ || "$target_image" == *:latest ]]; then
  printf '%s\n' 'An explicit Azure registry repository:tag other than latest is required.' >&2
  exit 2
fi
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
# No push, Azure credential, PAT, build secret or local checkout-wide COPY.
docker build --file "$root/infra/ci-runner-controller/Dockerfile" \
  --build-arg "PYTHON_IMAGE=$base_image" --tag "$target_image" "$root"
