#!/usr/bin/env bash
#
# stage-offline-kit.sh - assemble and sign one offline deployment kit.
#
# This is the connected-host half of a disconnected handover. It collects the
# artifacts a closed network cannot fetch for itself - the `fdai-deployment-cli` wheel, the
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
#     [--platform linux_amd64] [--runtime-release DIR] \
#     [--runtime-descriptor FILE --runtime-source-root DIR] [--with-runtime-wheels]
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
PLATFORM_TAG=""
PLATFORM=""
RUNTIME_RELEASE=""
RUNTIME_DESCRIPTOR=""
RUNTIME_SOURCE_ROOT=""
WITH_RUNTIME_WHEELS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --release-key) RELEASE_KEY="$2"; shift 2 ;;
    --bundle-key) BUNDLE_KEY="$2"; shift 2 ;;
    --bundle-version) BUNDLE_VERSION="$2"; shift 2 ;;
    --platform-tag) PLATFORM_TAG="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --runtime-release) RUNTIME_RELEASE="$2"; shift 2 ;;
    --runtime-descriptor) RUNTIME_DESCRIPTOR="$2"; shift 2 ;;
    --runtime-source-root) RUNTIME_SOURCE_ROOT="$2"; shift 2 ;;
    --with-runtime-wheels) WITH_RUNTIME_WHEELS=1; shift ;;
    *) echo "stage-offline-kit: unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ -n "$RUNTIME_RELEASE" && -n "$RUNTIME_DESCRIPTOR" ]]; then
  echo "stage-offline-kit: --runtime-release and --runtime-descriptor are mutually exclusive." >&2
  exit 2
fi
if [[ -n "$RUNTIME_DESCRIPTOR" && -z "$RUNTIME_SOURCE_ROOT" ]]; then
  echo "stage-offline-kit: --runtime-descriptor requires --runtime-source-root." >&2
  exit 2
fi
if [[ -n "$RUNTIME_SOURCE_ROOT" && -z "$RUNTIME_DESCRIPTOR" ]]; then
  echo "stage-offline-kit: --runtime-source-root requires --runtime-descriptor." >&2
  exit 2
fi
if [[ -n "$RUNTIME_DESCRIPTOR" ]] && {
  [[ "$RUNTIME_DESCRIPTOR" != /* ]] || [[ ! -f "$RUNTIME_DESCRIPTOR" ]] || [[ -L "$RUNTIME_DESCRIPTOR" ]];
}; then
  echo "stage-offline-kit: --runtime-descriptor must be an absolute regular file." >&2
  exit 2
fi
if [[ -n "$RUNTIME_SOURCE_ROOT" ]] && {
  [[ "$RUNTIME_SOURCE_ROOT" != /* ]] || [[ ! -d "$RUNTIME_SOURCE_ROOT" ]] || [[ -L "$RUNTIME_SOURCE_ROOT" ]];
}; then
  echo "stage-offline-kit: --runtime-source-root must be an absolute real directory." >&2
  exit 2
fi

for required in OUT RELEASE_KEY BUNDLE_KEY; do
  if [[ -z "${!required}" ]]; then
    echo "stage-offline-kit: --${required,,} is required." >&2
    exit 2
  fi
done
for key in "$RELEASE_KEY" "$BUNDLE_KEY"; do
  [[ -f "$key" && ! -L "$key" ]] || {
    echo "stage-offline-kit: signing key must be a regular non-symlink file: $key" >&2
    exit 2
  }
done

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
if [[ ( -n "$RUNTIME_RELEASE" || -n "$RUNTIME_DESCRIPTOR" || "$WITH_RUNTIME_WHEELS" -eq 1 ) && -n "$(git status --porcelain)" ]]; then
  echo "stage-offline-kit: runtime releases require a clean exact-revision checkout." >&2
  exit 2
fi
PYTHON="$repo_root/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo "stage-offline-kit: BLOCKED - .venv is missing." >&2; exit 2; }
SAFE_WRITER="scripts/deployment/release/secure_work_file.py"
STAGE_SENTINEL=".fdai-offline-stage"
if [[ "$OUT" != /* || "$OUT" == "/" || "$OUT" == "$HOME" || "$OUT" == "$repo_root" ]]; then
  echo "stage-offline-kit: --out must be a safe absolute path outside the repository and home." >&2
  exit 2
fi
if [[ -L "$OUT" ]]; then
  echo "stage-offline-kit: --out must not be a symbolic link." >&2
  exit 2
fi
if [[ ! -e "$OUT" ]]; then
  "$PYTHON" scripts/deployment/release/workdir-guard.py create \
    --path "$OUT" --sentinel "$STAGE_SENTINEL" --value fdai-offline-stage-v1
else
  if ! "$PYTHON" scripts/deployment/release/workdir-guard.py verify \
    --path "$OUT" --sentinel "$STAGE_SENTINEL" --value fdai-offline-stage-v1 &&
    ! "$PYTHON" scripts/deployment/release/workdir-guard.py verify \
      --path "$OUT" --sentinel .fdai-airgap-workdir --value fdai-airgap-drill-v1; then
    echo "stage-offline-kit: existing --out is not owned by offline staging." >&2
    exit 2
  fi
fi

for tool in curl git sha256sum timeout uv; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "stage-offline-kit: BLOCKED - $tool is required to assemble a kit." >&2
    exit 2
  }
done
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)
    HOST_PLATFORM="linux_amd64"
    HOST_PLATFORM_TAG="linux-x86_64"
    ;;
  Linux-aarch64|Linux-arm64)
    HOST_PLATFORM="linux_arm64"
    HOST_PLATFORM_TAG="linux-aarch64"
    ;;
  *)
    echo "stage-offline-kit: unsupported staging host platform." >&2
    exit 2
    ;;
esac
PLATFORM="${PLATFORM:-$HOST_PLATFORM}"
PLATFORM_TAG="${PLATFORM_TAG:-$HOST_PLATFORM_TAG}"
if [[ "$PLATFORM" != "$HOST_PLATFORM" || "$PLATFORM_TAG" != "$HOST_PLATFORM_TAG" ]]; then
  echo "stage-offline-kit: cross-platform kit staging is not supported." >&2
  exit 2
fi
TERRAFORM_VERSION="1.9.8"
OPA_VERSION="0.68.0"
case "$HOST_PLATFORM" in
  linux_amd64)
    TERRAFORM_SHA256="186e0145f5e5f2eb97cbd785bc78f21bae4ef15119349f6ad4fa535b83b10df8"
    OPA_SHA256="dfd5081fc6f930dfeaf2a225e31e616fc227dc0c7b43019b73d6f8fb8a1de1aa"
    OPA_ASSET="opa_linux_amd64_static"
    ;;
  linux_arm64)
    TERRAFORM_SHA256="f85868798834558239f6148834884008f2722548f84034c9b0f62934b2d73ebb"
    OPA_SHA256="1a583e593cdf4931c0b0bbedd3c9f585012953449115bcc3e15b3806d0f5ee68"
    OPA_ASSET="opa_linux_arm64_static"
    ;;
esac

CLI_VERSION=""
KIT="$OUT/kit"
BUNDLE_IN_KIT="deployment/fdai-deployment-bundle-${BUNDLE_VERSION}.tar.gz"
ACTIVE_PIDS=()

remember_background() {
  ACTIVE_PIDS+=("$1")
}

forget_background() {
  local completed="$1" retained=() pid
  for pid in "${ACTIVE_PIDS[@]}"; do
    [[ "$pid" == "$completed" ]] || retained+=("$pid")
  done
  ACTIVE_PIDS=("${retained[@]}")
}

wait_background() {
  local pid="$1" status=0
  wait "$pid" || status=$?
  forget_background "$pid"
  return "$status"
}

stop_background() {
  local pid
  for pid in "${ACTIVE_PIDS[@]}"; do
    kill -TERM "$pid" >/dev/null 2>&1 || true
  done
  for pid in "${ACTIVE_PIDS[@]}"; do
    wait "$pid" >/dev/null 2>&1 || true
  done
  ACTIVE_PIDS=()
}

drain_background() {
  local pid
  for pid in "${ACTIVE_PIDS[@]}"; do
    wait "$pid" >/dev/null 2>&1 || true
  done
  ACTIVE_PIDS=()
}

wait_or_stop() {
  local pid="$1" status=0
  wait_background "$pid" || status=$?
  if ((status != 0)); then
    drain_background
    return "$status"
  fi
}

trap stop_background EXIT
trap 'stop_background; exit 130' INT
trap 'stop_background; exit 143' TERM

rm -rf "$KIT" "$OUT/bundle" "$OUT/wheels" "$OUT/mirror" "$OUT/mirror-src" \
  "$OUT/toolchain" "$OUT/runtime-build" "$OUT/runtime-python"
rm -f "$OUT/bundle.tar.gz" "$OUT/cli-requirements.txt"
mkdir -p "$OUT/toolchain" "$KIT"/{python,deployment,terraform,bin,sbom}
chmod 700 "$OUT/toolchain" "$KIT"

PYTHONPATH=scripts/deployment/release:services/core-control-plane/src "$PYTHON" -c '
import sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from secure_key_file import read_key_file

key = load_pem_private_key(read_key_file(Path(sys.argv[1]), private=True), password=None)
if not isinstance(key, Ed25519PrivateKey):
    raise SystemExit("release signing key MUST be Ed25519")
sys.stdout.buffer.write(
    key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
)
' "$RELEASE_KEY" |
  "$PYTHON" "$SAFE_WRITER" --path "$OUT/release-root.pub" --mode 644 --replace

TERRAFORM_BIN="$OUT/toolchain/terraform"

download_terraform() {
  curl -fsSL --retry 3 --retry-delay 2 --retry-all-errors \
    --retry-max-time 120 --connect-timeout 10 --max-time 90 \
    -o "$OUT/toolchain/terraform.zip" \
    "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_${HOST_PLATFORM}.zip"
  echo "$TERRAFORM_SHA256  $OUT/toolchain/terraform.zip" | sha256sum -c -
  timeout --signal=TERM --kill-after=15 120 \
    "$PYTHON" scripts/deployment/release/extract-terraform-archive.py \
    --archive "$OUT/toolchain/terraform.zip" --output "$TERRAFORM_BIN"
  chmod 755 "$TERRAFORM_BIN"
}

download_opa() {
  curl -fsSL --retry 3 --retry-delay 2 --retry-all-errors \
    --retry-max-time 120 --connect-timeout 10 --max-time 90 \
    -o "$OUT/toolchain/opa" \
    "https://github.com/open-policy-agent/opa/releases/download/v${OPA_VERSION}/${OPA_ASSET}"
  echo "$OPA_SHA256  $OUT/toolchain/opa" | sha256sum -c -
  chmod 755 "$OUT/toolchain/opa"
}

build_bundle() {
  timeout --signal=TERM --kill-after=15 900 env \
    SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1700000000}" \
    PYTHONPATH=services/core-control-plane/src "$PYTHON" \
    scripts/deployment/release/build-deployment-bundle.py \
    --destination "$OUT/bundle" --archive "$OUT/bundle.tar.gz" \
    --private-key "$BUNDLE_KEY" --public-key-output "$OUT/bundle-key.pub" \
    --bundle-version "$BUNDLE_VERSION" --release-channel development \
    --min-cli-version 0.1.0 >/dev/null
}

build_cli_wheels() {
  timeout --signal=TERM --kill-after=15 300 \
    uv lock --check --project packages/deployment-cli >/dev/null
  timeout --signal=TERM --kill-after=15 600 \
    uv build --wheel --project packages/deployment-cli --out-dir "$OUT/wheels" >/dev/null
  timeout --signal=TERM --kill-after=15 300 \
    uv export --project packages/deployment-cli --locked --no-dev --no-emit-project \
    --format requirements-txt --output-file "$OUT/cli-requirements.txt" >/dev/null
  timeout --signal=TERM --kill-after=15 900 \
    uv run --project packages/deployment-cli --locked --no-dev --group release \
    --python "$PYTHON" python -m pip download --only-binary=:all: --require-hashes \
    --dest "$OUT/wheels" --requirement "$OUT/cli-requirements.txt" >/dev/null
}

echo "-- pinned release toolchain"
echo "   terraform"
download_terraform &
terraform_pid=$!
remember_background "$terraform_pid"
echo "   OPA"
download_opa &
opa_pid=$!
remember_background "$opa_pid"
echo "-- signed deployment bundle"
build_bundle &
bundle_pid=$!
remember_background "$bundle_pid"
echo "-- fdai deployment CLI wheel"
build_cli_wheels &
cli_pid=$!
remember_background "$cli_pid"

wait_or_stop "$terraform_pid"
wait_or_stop "$bundle_pid"

if [[ -n "$RUNTIME_DESCRIPTOR" ]]; then
  echo "-- runtime release bound to signed deployment bundle"
  PYTHONPATH=packages/deployment-cli/src "$PYTHON" \
    scripts/deployment/release/build-runtime-release.py \
    --source-root "$RUNTIME_SOURCE_ROOT" --descriptor "$RUNTIME_DESCRIPTOR" \
    --deployment-bundle "$OUT/bundle.tar.gz" --output "$OUT/runtime-build" >/dev/null
  RUNTIME_RELEASE="$OUT/runtime-build"
fi
if [[ -n "$RUNTIME_RELEASE" ]]; then
  WITH_RUNTIME_WHEELS=1
fi

echo "-- terraform provider mirror"
bash scripts/deployment/release/mirror-locked-providers.sh \
  "$OUT/bundle" "$OUT" "$TERRAFORM_BIN" "$PLATFORM" &
mirror_pid=$!
remember_background "$mirror_pid"

wait_or_stop "$opa_pid"
wait_or_stop "$cli_pid"
wait_or_stop "$mirror_pid"
# The kit's CLI version is the version of the wheel it actually carries. Reading
# it from the installed package instead would silently disagree whenever the
# source tree has moved ahead of the environment.
wheel_path="$(find "$OUT/wheels" -maxdepth 1 -name 'fdai_deployment_cli-*-py3-none-any.whl' | head -1)"
[[ -n "$wheel_path" ]] || { echo "stage-offline-kit: no wheel was built." >&2; exit 1; }
wheel_name="$(basename "$wheel_path")"
CLI_VERSION="${wheel_name#fdai_deployment_cli-}"
CLI_VERSION="${CLI_VERSION%-py3-none-any.whl}"
WHEEL="python/$wheel_name"

echo "-- assemble kit"
cp "$OUT/wheels"/*.whl "$KIT/python/"
cp "$OUT/bundle.tar.gz" "$KIT/$BUNDLE_IN_KIT"
cp "$TERRAFORM_BIN" "$KIT/terraform/terraform"
cp -r "$OUT/mirror" "$KIT/terraform/providers"
cp "$OUT/toolchain/opa" "$KIT/bin/opa"

if [[ -n "$RUNTIME_RELEASE" ]]; then
  echo "-- prebuilt runtime release"
  PYTHONPATH=packages/deployment-cli/src "$PYTHON" \
    scripts/deployment/release/stage-runtime-release.py \
    --source "$RUNTIME_RELEASE" --kit "$KIT" \
    --deployment-bundle "$KIT/$BUNDLE_IN_KIT" \
    --source-commit "$(git rev-parse HEAD)" --platform-tag "$PLATFORM_TAG"
fi

if [[ "$WITH_RUNTIME_WHEELS" -eq 1 ]]; then
  echo "-- locked runtime support wheels"
  "$PYTHON" scripts/deployment/release/stage-runtime-wheelhouse.py \
    --repo-root "$repo_root" --out-dir "$OUT/runtime-python"
  install -d -m 0700 "$KIT/support/python"
  cp -r "$OUT/runtime-python/build" "$OUT/runtime-python/requirements" \
    "$OUT/runtime-python/wheels" "$OUT/runtime-python/inventory.json" "$KIT/support/python/"
fi

echo "-- kit SBOM"
# The deployment bundle already ships a real CycloneDX document listing every
# file it carries with a SHA-256. The kit shipped an empty components array,
# which reads as compliant while describing nothing - and the kit is the half
# that carries the outside supply chain: the Terraform binary, the OPA binary,
# and every mirrored provider. A recipient who cannot enumerate those has no
# supply-chain visibility at all.
"$PYTHON" - "$KIT" "sbom/offline-kit.cdx.json" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
sbom_relative = sys.argv[2]


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


components = []
for directory, _subdirectories, names in os.walk(root):
    for name in names:
        entry = Path(directory) / name
        relative = entry.relative_to(root).as_posix()
        # The SBOM cannot contain its own digest; the kit manifest covers it.
        if relative == sbom_relative:
            continue
        components.append(
            {
                "type": "file",
                "name": relative,
                "hashes": [{"alg": "SHA-256", "content": digest(entry)}],
            }
        )
components.sort(key=lambda component: component["name"])
if not components:
    raise SystemExit("stage-offline-kit: refusing to write an SBOM describing nothing")
sbom_path = root / sbom_relative
sbom_path.parent.mkdir(parents=True, exist_ok=True)
sbom_path.write_text(
    json.dumps(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "components": components,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n",
    encoding="utf-8",
)
print(f"   {len(components)} components")
PY

echo "-- sign kit"
PYTHONPATH=packages/deployment-cli/src:services/core-control-plane/src "$PYTHON" \
  scripts/deployment/release/build-offline-kit.py \
  --kit "$KIT" --private-key "$RELEASE_KEY" --release-root "$OUT/release-root.pub" \
  --kit-version "$CLI_VERSION" --cli-version "$CLI_VERSION" \
  --bundle-version "$BUNDLE_VERSION" --platform-tag "$PLATFORM_TAG" \
  --python-wheel "$WHEEL" --deployment-bundle "$BUNDLE_IN_KIT" \
  --terraform-binary terraform/terraform --provider-mirror-prefix terraform/providers \
  --opa-binary bin/opa --sbom-path sbom/offline-kit.cdx.json

echo "stage-offline-kit: OK - signed kit at $KIT (cli_version=$CLI_VERSION)"
