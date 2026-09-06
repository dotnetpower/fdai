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
#     [--platform linux_amd64] [--runtime-release DIR] [--with-runtime-wheels]
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
    --with-runtime-wheels) WITH_RUNTIME_WHEELS=1; shift ;;
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
if [[ ( -n "$RUNTIME_RELEASE" || "$WITH_RUNTIME_WHEELS" -eq 1 ) && -n "$(git status --porcelain)" ]]; then
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

for tool in curl git sha256sum unzip uv; do
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

rm -rf "$KIT" "$OUT/bundle" "$OUT/wheels" "$OUT/mirror" "$OUT/toolchain" "$OUT/runtime-python"
rm -f "$OUT/bundle.tar.gz" "$OUT/cli-requirements.txt"
mkdir -p "$OUT/toolchain" "$KIT"/{python,deployment,terraform,bin,sbom}
chmod 700 "$KIT"

PYTHONPATH=scripts/deployment/release "$PYTHON" -c '
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

echo "-- pinned release toolchain"
curl -fsSL --retry 3 --retry-delay 2 --retry-all-errors \
  --retry-max-time 120 --connect-timeout 10 --max-time 90 \
  -o "$OUT/toolchain/terraform.zip" \
  "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_${HOST_PLATFORM}.zip"
echo "$TERRAFORM_SHA256  $OUT/toolchain/terraform.zip" | sha256sum -c -
unzip -q "$OUT/toolchain/terraform.zip" -d "$OUT/toolchain"
TERRAFORM_BIN="$OUT/toolchain/terraform"
curl -fsSL --retry 3 --retry-delay 2 --retry-all-errors \
  --retry-max-time 120 --connect-timeout 10 --max-time 90 \
  -o "$OUT/toolchain/opa" \
  "https://github.com/open-policy-agent/opa/releases/download/v${OPA_VERSION}/${OPA_ASSET}"
echo "$OPA_SHA256  $OUT/toolchain/opa" | sha256sum -c -
chmod 755 "$TERRAFORM_BIN" "$OUT/toolchain/opa"

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
(cd "$OUT/mirror-src" && "$TERRAFORM_BIN" init -backend=false -input=false >/dev/null)
(cd "$OUT/mirror-src" && "$TERRAFORM_BIN" providers mirror -platform="$PLATFORM" "$OUT/mirror" >/dev/null)
rm -rf "$OUT/mirror-src"

echo "-- fdai deployment CLI wheel"
uv lock --check --project packages/deployment-cli >/dev/null
uv build --wheel --project packages/deployment-cli --out-dir "$OUT/wheels" >/dev/null
uv export --project packages/deployment-cli --locked --no-dev --no-emit-project \
  --format requirements-txt --output-file "$OUT/cli-requirements.txt" >/dev/null
uv run --project packages/deployment-cli --locked --no-dev --group release \
  --python "$PYTHON" python -m pip download --only-binary=:all: --require-hashes \
  --dest "$OUT/wheels" --requirement "$OUT/cli-requirements.txt" >/dev/null
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
  mkdir -m 700 -p "$KIT/support/python"
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
PYTHONPATH=packages/deployment-cli/src "$PYTHON" scripts/deployment/release/build-offline-kit.py \
  --kit "$KIT" --private-key "$RELEASE_KEY" --release-root "$OUT/release-root.pub" \
  --kit-version "$CLI_VERSION" --cli-version "$CLI_VERSION" \
  --bundle-version "$BUNDLE_VERSION" --platform-tag "$PLATFORM_TAG" \
  --python-wheel "$WHEEL" --deployment-bundle "$BUNDLE_IN_KIT" \
  --terraform-binary terraform/terraform --provider-mirror-prefix terraform/providers \
  --opa-binary bin/opa --sbom-path sbom/offline-kit.cdx.json

echo "stage-offline-kit: OK - signed kit at $KIT (cli_version=$CLI_VERSION)"
