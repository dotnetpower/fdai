#!/usr/bin/env bash
#
# stage-offline-kit.sh - assemble and sign one offline deployment kit.
#
# This is the connected-host half of a disconnected handover. It collects the
# artifacts a closed network cannot fetch for itself - the `fdai` wheel, the
# signed deployment bundle, a Terraform provider mirror, the pinned Terraform
# and policy-engine binaries, and a bill of materials - then signs the result
# with `build-offline-kit.py`.
#
# Release-only. The signing keys are operator-held paths; nothing secret is
# written into the kit, and the public halves are derived here so a caller
# never has to pass a key twice.
#
# `airgap-drill.sh` runs this exact script with throwaway keys, so a green
# drill exercises the real release path rather than a copy of it.
#
# Usage:
#   bash scripts/deployment/release/stage-offline-kit.sh \
#     --out DIR --release-key PATH --bundle-key PATH \
#     [--bundle-version X.Y.Z] [--platform-tag linux-x86_64] \
#     [--platform linux_amd64]
#
# Produces:
#   DIR/kit/                 the signed offline kit
#   DIR/release-root.pub     public key that verifies the kit
#   DIR/bundle-key.pub       public key that verifies the deployment bundle

set -euo pipefail

OUT=""
RELEASE_KEY=""
BUNDLE_KEY=""
BUNDLE_VERSION="0.1.0"
PLATFORM_TAG="linux-x86_64"
PLATFORM="linux_amd64"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --release-key) RELEASE_KEY="$2"; shift 2 ;;
    --bundle-key) BUNDLE_KEY="$2"; shift 2 ;;
    --bundle-version) BUNDLE_VERSION="$2"; shift 2 ;;
    --platform-tag) PLATFORM_TAG="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    *) echo "stage-offline-kit: unknown argument: $1" >&2; exit 2 ;;
  esac
done

for required in OUT RELEASE_KEY BUNDLE_KEY; do
  if [[ -z "${!required}" ]]; then
    echo "stage-offline-kit: --${required,,} is required." >&2
    exit 2
  fi
done
for key in "$RELEASE_KEY" "$BUNDLE_KEY"; do
  [[ -f "$key" ]] || { echo "stage-offline-kit: signing key not found: $key" >&2; exit 2; }
done

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

for tool in terraform openssl uv git opa; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "stage-offline-kit: BLOCKED - $tool is required to assemble a kit." >&2
    exit 2
  }
done
PYTHON="$repo_root/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo "stage-offline-kit: BLOCKED - .venv is missing." >&2; exit 2; }

CLI_VERSION=""
KIT="$OUT/kit"
BUNDLE_IN_KIT="deployment/fdai-deployment-bundle-${BUNDLE_VERSION}.tar.gz"

rm -rf "$KIT" "$OUT/bundle" "$OUT/wheels" "$OUT/mirror"
mkdir -p "$OUT" "$KIT"/{python,deployment,terraform,bin,sbom}

openssl pkey -in "$RELEASE_KEY" -pubout -out "$OUT/release-root.pub"

echo "-- signed deployment bundle"
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1700000000}" PYTHONPATH=src "$PYTHON" \
  scripts/deployment/release/build-deployment-bundle.py \
  --destination "$OUT/bundle" --archive "$OUT/bundle.tar.gz" \
  --private-key "$BUNDLE_KEY" --public-key-output "$OUT/bundle-key.pub" \
  --bundle-version "$BUNDLE_VERSION" --release-channel development \
  --min-cli-version 0.1.0 >/dev/null

echo "-- terraform provider mirror"
# Mirror from a scratch copy so `terraform init` never writes .terraform into
# the signed bundle directory.
rm -rf "$OUT/mirror-src"
cp -r "$OUT/bundle/infra" "$OUT/mirror-src"
(cd "$OUT/mirror-src" && terraform init -backend=false -input=false >/dev/null)
(cd "$OUT/mirror-src" && terraform providers mirror -platform="$PLATFORM" "$OUT/mirror" >/dev/null)
rm -rf "$OUT/mirror-src"

echo "-- fdai wheel"
uv build --wheel --out-dir "$OUT/wheels" >/dev/null
# The kit's CLI version is the version of the wheel it actually carries. Reading
# it from the installed package instead would silently disagree whenever the
# source tree has moved ahead of the environment.
wheel_path="$(find "$OUT/wheels" -maxdepth 1 -name 'fdai-*-py3-none-any.whl' | head -1)"
[[ -n "$wheel_path" ]] || { echo "stage-offline-kit: no wheel was built." >&2; exit 1; }
wheel_name="$(basename "$wheel_path")"
CLI_VERSION="${wheel_name#fdai-}"
CLI_VERSION="${CLI_VERSION%-py3-none-any.whl}"
WHEEL="python/$wheel_name"

echo "-- assemble kit"
cp "$wheel_path" "$KIT/python/"
cp "$OUT/bundle.tar.gz" "$KIT/$BUNDLE_IN_KIT"
cp "$(command -v terraform)" "$KIT/terraform/terraform"
cp -r "$OUT/mirror" "$KIT/terraform/providers"
cp "$(command -v opa)" "$KIT/bin/opa"
printf '{"bomFormat":"CycloneDX","specVersion":"1.5","version":1,"components":[]}\n' \
  > "$KIT/sbom/offline-kit.cdx.json"

echo "-- sign kit"
PYTHONPATH=src "$PYTHON" scripts/deployment/release/build-offline-kit.py \
  --kit "$KIT" --private-key "$RELEASE_KEY" --release-root "$OUT/release-root.pub" \
  --kit-version "$CLI_VERSION" --cli-version "$CLI_VERSION" \
  --bundle-version "$BUNDLE_VERSION" --platform-tag "$PLATFORM_TAG" \
  --python-wheel "$WHEEL" --deployment-bundle "$BUNDLE_IN_KIT" \
  --terraform-binary terraform/terraform --provider-mirror-prefix terraform/providers \
  --opa-binary bin/opa --sbom-path sbom/offline-kit.cdx.json

echo "stage-offline-kit: OK - signed kit at $KIT (cli_version=$CLI_VERSION)"
