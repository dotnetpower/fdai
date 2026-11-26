#!/usr/bin/env bash
#
# airgap-drill.sh - prove the disconnected provisioning path end to end.
#
# The repository can assert contracts with unit tests, but it could not show
# that a real kit provisions with no network at all. This drill does, in the
# same two phases a customer handover uses:
#
#   stage   (needs network)  build the wheel, the signed deployment bundle, and
#                            a Terraform provider mirror, then assemble and sign
#                            one offline kit.
#   verify  (no network)     run every disconnected step inside a network
#                            namespace with no route and no DNS.
#
# The drill consumes existing artifacts only. Terraform stays the execution
# engine and source of truth, and nothing here becomes an alternate path around
# the signed bundle (docs/roadmap/deployment/installable-deployment-cli.md).
#
# What the verify phase proves:
#   1. the namespace really has no egress and no name resolution;
#   2. the signed kit verifies offline;
#   3. the signed deployment bundle verifies offline;
#   4. `terraform init` succeeds from the kit's filesystem mirror alone;
#   5. `terraform validate` accepts the bundle's infrastructure;
#   6. `terraform test` evaluates the plan graph through mocked providers;
#   7. the same init FAILS without the mirror, so step 4 is not a cached
#      plugin directory quietly doing the work;
#   8. `fdaictl license inspect` resolves entitlement offline;
#   9. `fdaictl provision plan` drives the whole disconnected sequence itself -
#      kit verification, mirror-pinned CLI configuration, and `terraform init` -
#      and gets far enough that the only thing still missing is deployment
#      input, not a provider and not a network.
#  10. when a complete runtime v2 release is supplied, installed `fdaictl`
#      snapshots all five service images, ClamAV, Console, and deployment support
#      without a route or DNS and reports prepared, never subscription-ready.
#  11. the same authenticated kit installs all runtime support distributions
#      from hash-pinned wheels with indexes, downloads, builds, and caches disabled.
#
# What it does NOT prove: a real `terraform apply` still needs the tenant's
# approved private path to the Azure management plane. This drill stops at plan
# evaluation, which is the last step that is honest to simulate locally.
#
# Keys created here are throwaway drill keys under the work directory. They are
# never repository material and never leave the machine.
#
# Usage:
#   bash scripts/deployment/release/airgap-drill.sh [--workdir DIR] [--skip-stage]
#     [--runtime-release DIR] \
#     [--runtime-descriptor FILE --runtime-source-root DIR] [--require-runtime]

set -euo pipefail

WORKDIR="${TMPDIR:-/tmp}/fdai-airgap-drill"
SKIP_STAGE=0
RUNTIME_RELEASE=""
RUNTIME_DESCRIPTOR=""
RUNTIME_SOURCE_ROOT=""
REQUIRE_RUNTIME=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) WORKDIR="$2"; shift 2 ;;
    --skip-stage) SKIP_STAGE=1; shift ;;
    --runtime-release) RUNTIME_RELEASE="$2"; shift 2 ;;
    --runtime-descriptor) RUNTIME_DESCRIPTOR="$2"; shift 2 ;;
    --runtime-source-root) RUNTIME_SOURCE_ROOT="$2"; shift 2 ;;
    --require-runtime) REQUIRE_RUNTIME=1; shift ;;
    *) echo "airgap-drill: unknown argument: $1" >&2; exit 2 ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
PYTHON="$repo_root/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo "airgap-drill: BLOCKED - .venv is missing." >&2; exit 2; }
SAFE_WRITER="scripts/deployment/release/secure_work_file.py"
SENTINEL=".fdai-airgap-workdir"
if [[ "$WORKDIR" != /* || "$WORKDIR" == "/" || "$WORKDIR" == "$HOME" || "$WORKDIR" == "$repo_root" ]]; then
  echo "airgap-drill: workdir must be a safe absolute path outside the repository and home." >&2
  exit 2
fi
if [[ -L "$WORKDIR" ]]; then
  echo "airgap-drill: workdir must not be a symbolic link." >&2
  exit 2
fi
if [[ -n "$RUNTIME_RELEASE" ]] && {
  [[ "$RUNTIME_RELEASE" != /* ]] || [[ ! -d "$RUNTIME_RELEASE" ]] || [[ -L "$RUNTIME_RELEASE" ]];
}; then
  echo "airgap-drill: --runtime-release must be an absolute real directory." >&2
  exit 2
fi
if [[ -n "$RUNTIME_RELEASE" && -n "$RUNTIME_DESCRIPTOR" ]]; then
  echo "airgap-drill: --runtime-release and --runtime-descriptor are mutually exclusive." >&2
  exit 2
fi
if [[ -n "$RUNTIME_DESCRIPTOR" ]] && {
  [[ "$RUNTIME_DESCRIPTOR" != /* ]] || [[ ! -f "$RUNTIME_DESCRIPTOR" ]] || [[ -L "$RUNTIME_DESCRIPTOR" ]];
}; then
  echo "airgap-drill: --runtime-descriptor must be an absolute regular file." >&2
  exit 2
fi
if [[ -n "$RUNTIME_DESCRIPTOR" && -z "$RUNTIME_SOURCE_ROOT" ]]; then
  echo "airgap-drill: --runtime-descriptor requires --runtime-source-root." >&2
  exit 2
fi
if [[ -n "$RUNTIME_SOURCE_ROOT" ]] && {
  [[ -z "$RUNTIME_DESCRIPTOR" ]] || [[ "$RUNTIME_SOURCE_ROOT" != /* ]] || [[ ! -d "$RUNTIME_SOURCE_ROOT" ]] || [[ -L "$RUNTIME_SOURCE_ROOT" ]];
}; then
  echo "airgap-drill: --runtime-source-root requires a descriptor and an absolute real directory." >&2
  exit 2
fi
if [[ "$SKIP_STAGE" -eq 0 ]]; then
  if [[ -e "$WORKDIR" ]]; then
    echo "airgap-drill: a fresh workdir is required." >&2
    exit 2
  fi
  "$PYTHON" scripts/deployment/release/workdir-guard.py create \
    --path "$WORKDIR" --sentinel "$SENTINEL" --value fdai-airgap-drill-v1
else
  if ! "$PYTHON" scripts/deployment/release/workdir-guard.py verify \
    --path "$WORKDIR" --sentinel "$SENTINEL" --value fdai-airgap-drill-v1; then
    echo "airgap-drill: --skip-stage requires an owned drill workdir." >&2
    exit 2
  fi
fi

for tool in az curl git mount openssl unshare uv; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "airgap-drill: BLOCKED - $tool is required." >&2
    exit 2
  }
done
KIT="$WORKDIR/kit"
BUNDLE_VERSION="0.1.0"
case "$(uname -m)" in
  x86_64) PLATFORM_TAG="linux-x86_64" ;;
  aarch64|arm64) PLATFORM_TAG="linux-aarch64" ;;
  *) echo "airgap-drill: BLOCKED - unsupported host architecture." >&2; exit 2 ;;
esac
BUNDLE_IN_KIT="deployment/fdai-deployment-bundle-${BUNDLE_VERSION}.tar.gz"

stage() {
  echo "== stage (network allowed) =="
  openssl genpkey -algorithm ed25519 2>/dev/null |
    "$PYTHON" "$SAFE_WRITER" --path "$WORKDIR/bundle-key.pem" --mode 600
  openssl genpkey -algorithm ed25519 2>/dev/null |
    "$PYTHON" "$SAFE_WRITER" --path "$WORKDIR/release-key.pem" --mode 600

  # The drill runs the real release staging script, so a green drill exercises
  # the release path itself rather than a second copy of it.
  stage_arguments=(
    --out "$WORKDIR"
    --release-key "$WORKDIR/release-key.pem"
    --bundle-key "$WORKDIR/bundle-key.pem"
    --bundle-version "$BUNDLE_VERSION"
    --platform-tag "$PLATFORM_TAG"
  )
  if [[ -n "$RUNTIME_RELEASE" ]]; then
    stage_arguments+=(--runtime-release "$RUNTIME_RELEASE" --with-runtime-wheels)
  elif [[ -n "$RUNTIME_DESCRIPTOR" ]]; then
    stage_arguments+=(
      --runtime-descriptor "$RUNTIME_DESCRIPTOR"
      --runtime-source-root "$RUNTIME_SOURCE_ROOT"
      --with-runtime-wheels
    )
  fi
  bash scripts/deployment/release/stage-offline-kit.sh \
    "${stage_arguments[@]}" >/dev/null

  echo "-- issue a drill license"
  PYTHONPATH=services/core-control-plane/src:packages/service-contracts/src \
    "$PYTHON" scripts/deployment/release/issue-license.py \
    --private-key "$WORKDIR/release-key.pem" --public-key "$WORKDIR/release-root.pub" \
    --license-id lic-drill-0001 --distribution-id example-distribution \
    --capability cost.metering --valid-days 30 \
    --output "$WORKDIR/license.token" >/dev/null

  "$PYTHON" "$SAFE_WRITER" --path "$WORKDIR/offline.tfrc" --mode 600 <<EOF
provider_installation {
  filesystem_mirror {
    path    = "$WORKDIR/authenticated-kit/terraform/providers"
    include = ["*/*"]
  }
  direct {
    exclude = ["*/*"]
  }
}
EOF
}

if [[ "$SKIP_STAGE" -eq 0 ]]; then
  stage
else
  [[ -d "$KIT" ]] || { echo "airgap-drill: --skip-stage needs an existing kit." >&2; exit 2; }
fi
HAS_RUNTIME=0
if [[ -f "$KIT/runtime/release.json" ]]; then
  HAS_RUNTIME=1
fi
if [[ "$REQUIRE_RUNTIME" -eq 1 && "$HAS_RUNTIME" -ne 1 ]]; then
  echo "airgap-drill: --require-runtime needs a complete staged runtime release." >&2
  exit 2
fi
rm -rf "$WORKDIR/work" "$WORKDIR/negative" "$WORKDIR/authenticated-kit" \
  "$WORKDIR/cli-venv" "$WORKDIR/empty-azure" "$WORKDIR/preparation" \
  "$WORKDIR/support-install"
mkdir -m 700 "$WORKDIR/empty-azure"

# The kit declares which CLI it was built for; verification binds that exact
# value, so read it rather than assume the local environment matches.
CLI_VERSION="$(PYTHONPATH=packages/deployment-cli/src "$PYTHON" -c '
import json
import sys
from pathlib import Path
from fdai_deployment_cli.offline_kit import _read_regular

print(json.loads(_read_regular(Path(sys.argv[1]), 4 * 1024 * 1024))["cli_version"])
' "$KIT/offline-kit.json")"
"$PYTHON" "$SAFE_WRITER" --path "$WORKDIR/plan-input.tfvars.json" --mode 600 --replace <<'EOF'
{
  "core_image": "ghcr.io/example/fdai:plan-only",
  "postgres_admin_login": "fdaiadmin",
  "postgres_admin_password": "FDAI-PLAN-ONLY-NOT-A-SECRET",
  "region": "koreacentral",
  "subscription_id": "00000000-0000-0000-0000-000000000001",
  "target_binding": "34159426193cae792732df54bbe5872aa3b33468cff3834a5cc32d140b9e5257",
  "tenant_id": "00000000-0000-0000-0000-000000000000"
}
EOF
"$PYTHON" "$SAFE_WRITER" --path "$WORKDIR/offline-profile.json" --mode 600 --replace <<'EOF'
{
  "access_method": "internal_ssh",
  "approval_quorum": 1,
  "connectivity": "offline",
  "environment": "dev",
  "host": "existing-host",
  "monthly_cost_ceiling": 500,
  "region": "koreacentral",
  "schema_version": "fdai.provision-profile.v1",
  "shadow_only": true,
  "target_binding": "34159426193cae792732df54bbe5872aa3b33468cff3834a5cc32d140b9e5257",
  "transport": "manual"
}
EOF

echo "== verify (network namespace, no route, no DNS) =="
REPO_ROOT="$repo_root" HOST_WORKDIR="$WORKDIR" PYTHON="$PYTHON" UV="$(command -v uv)" \
  CLI_VERSION="$CLI_VERSION" PLATFORM_TAG="$PLATFORM_TAG" BUNDLE_VERSION="$BUNDLE_VERSION" \
  HAS_RUNTIME="$HAS_RUNTIME" \
  unshare -rmn --propagation private -- bash -euo pipefail -c '
mount --bind "$HOST_WORKDIR" /mnt
WORKDIR=/mnt
KIT="$WORKDIR/kit"
ip link set lo up 2>/dev/null || true
export TF_IN_AUTOMATION=1
export AZURE_CONFIG_DIR="$WORKDIR/empty-azure"
unset ARM_USE_MSI ARM_CLIENT_ID ARM_TENANT_ID TF_CLI_ARGS TF_CLI_ARGS_plan \
  TF_WORKSPACE TF_DATA_DIR TF_CLI_CONFIG_FILE
unset PYTHONPATH PYTHONHOME
TFBIN="$WORKDIR/authenticated-kit/terraform/terraform"
BUNDLE="$WORKDIR/work/fdai-deployment-bundle-${BUNDLE_VERSION}"
fail() { echo "airgap-drill: FAIL - $*" >&2; exit 1; }

echo "-- 1. isolation"
if timeout 5 curl -sI https://registry.terraform.io -o /dev/null 2>/dev/null; then
  fail "the namespace still reaches the public registry"
fi
if timeout 5 getent hosts registry.terraform.io >/dev/null 2>&1; then
  fail "the namespace still resolves public names"
fi
echo "   no egress, no DNS"

echo "-- 2. externally verify offline kit before executing it"
cd "$REPO_ROOT"
PYTHONPATH=packages/deployment-cli/src "$PYTHON" -c "
import sys
from pathlib import Path
from fdai_deployment_cli.bundle import extract_bundle_archive, verify_bundle
from fdai_deployment_cli.cli import _read_public_key
from fdai_deployment_cli.offline_kit import materialize_verified_artifacts, verify_offline_kit
result = verify_offline_kit(
    Path(sys.argv[1]),
    release_root_pem=_read_public_key(Path(sys.argv[2])),
    cli_version=sys.argv[3],
    platform_tag=sys.argv[4],
)
artifacts = materialize_verified_artifacts(
  Path(sys.argv[1]),
  result,
  Path(sys.argv[5]),
  include_all=\"runtime/release.json\" in dict(result.file_digests),
)
bundle_root = extract_bundle_archive(artifacts.deployment_bundle, Path(sys.argv[6]))
verify_bundle(
    bundle_root,
    public_key_pem=_read_public_key(Path(sys.argv[7])),
    cli_version=sys.argv[3],
)
print(f\"   verified {result.file_count} files, {result.total_bytes} bytes\")
" "$KIT" "$WORKDIR/release-root.pub" "$CLI_VERSION" "$PLATFORM_TAG" \
  "$WORKDIR/authenticated-kit" "$WORKDIR/work" "$WORKDIR/bundle-key.pub"
cp -r "$BUNDLE/infra" "$WORKDIR/negative"

echo "-- install authenticated shipped CLI from kit wheels"
"$UV" venv --python "$PYTHON" "$WORKDIR/cli-venv" >/dev/null
UV_NO_CACHE=1 "$UV" pip install --python "$WORKDIR/cli-venv/bin/python" \
  --no-index --find-links "$WORKDIR/authenticated-kit/python" \
  "fdai-deployment-cli==$CLI_VERSION" >/dev/null
CLI="$WORKDIR/cli-venv/bin/fdaictl"
CLI_PYTHON="$WORKDIR/cli-venv/bin/python"
"$CLI" version --output json >/dev/null

# Recheck through the installed distribution so the shipped import path is also exercised.
"$CLI_PYTHON" -c "
import sys
from pathlib import Path
from fdai_deployment_cli.cli import _read_public_key
from fdai_deployment_cli.offline_kit import verify_offline_kit
verify_offline_kit(
    Path(sys.argv[1]),
    release_root_pem=_read_public_key(Path(sys.argv[2])),
    cli_version=sys.argv[3],
    platform_tag=sys.argv[4],
)
" "$KIT" "$WORKDIR/release-root.pub" "$CLI_VERSION" "$PLATFORM_TAG"
# Kit verification proves the SBOM has not been tampered with; it cannot notice
# that the SBOM describes nothing. An empty components array reads as compliant
# and gives a recipient no supply-chain visibility, so assert the content too.
PYTHONPATH=packages/deployment-cli/src "$PYTHON" - "$KIT" <<'"'"'PY'"'"'
import json
import sys
from pathlib import Path
from fdai_deployment_cli.offline_kit import _read_regular

root = Path(sys.argv[1])
manifest = json.loads(_read_regular(root / "offline-kit.json", 4 * 1024 * 1024))
sbom = json.loads(_read_regular(root / manifest["sbom_path"], 16 * 1024 * 1024))
described = {component["name"] for component in sbom["components"]}
missing = sorted(set(manifest["files"]) - described - {manifest["sbom_path"]})
if missing:
    raise SystemExit(f"airgap-drill: FAIL - the kit SBOM omits {missing}")
print(f"   SBOM describes {len(described)} kit files")
PY

echo "-- 3. signed deployment bundle"
"$CLI" bundle verify \
  --bundle "$BUNDLE" --public-key "$WORKDIR/bundle-key.pub" --output json >/dev/null \
  || fail "bundle verification failed"
echo "   verified"

echo "-- 4. terraform init from the kit mirror"
cd "$BUNDLE/infra"
TF_CLI_CONFIG_FILE="$WORKDIR/offline.tfrc" "$TFBIN" init -backend=false -input=false >/dev/null \
  || fail "init could not resolve providers from the kit mirror"
echo "   providers resolved"

echo "-- 5. terraform validate"
TF_CLI_CONFIG_FILE="$WORKDIR/offline.tfrc" "$TFBIN" validate >/dev/null \
  || fail "validate rejected the bundle"
echo "   configuration valid"

echo "-- 6. terraform test (plan graph, mocked providers)"
TF_CLI_CONFIG_FILE="$WORKDIR/offline.tfrc" "$TFBIN" test 2>&1 | tail -2

echo "-- 7. negative control: init without the mirror MUST fail"
cd "$WORKDIR/negative"
rm -rf .terraform .terraform.lock.hcl
if env -u TF_CLI_CONFIG_FILE timeout 120 "$TFBIN" init -backend=false -input=false >/dev/null 2>&1; then
  fail "init succeeded without the kit mirror; the drill is not proving isolation"
fi
echo "   failed as required"

echo "-- 8. license inspection"
cd "$REPO_ROOT"
"$CLI" license inspect \
  --token "$WORKDIR/license.token" --public-key "$WORKDIR/release-root.pub" --output json \
  || fail "license inspection did not report an active entitlement"

echo "-- 9. fdaictl provision plan (the operator-facing disconnected path)"
# Steps 4-6 drive Terraform by hand. This step proves the command an operator
# actually runs reaches the same place on its own. It stops where the drill has
# always stopped - short of the tenant management plane - so the pass condition
# is that the verified configuration reaches provider authentication without
# resolving anything from the public registry.
rm -rf "$WORKDIR/provision"
set +e
plan_output="$("$CLI" provision plan \
  --offline-kit "$KIT" --release-root "$WORKDIR/release-root.pub" \
  --bundle-public-key "$WORKDIR/bundle-key.pub" --work-dir "$WORKDIR/provision" \
  --variables-file "$WORKDIR/plan-input.tfvars.json" \
  --profile "$WORKDIR/offline-profile.json" \
  --output json 2>&1)"
set -e
case "$plan_output" in
  *"terraform_provider_authentication_unavailable"*) ;;
  *) fail "provision plan did not reach provider authentication: $plan_output" ;;
esac
case "$plan_output" in
  *registry.terraform.io*|*"Failed to install provider"*|*"could not query provider"*)
    fail "provision plan tried to reach the public registry: $plan_output" ;;
esac
grep -q '"\*/\*"' "$WORKDIR/provision/offline.tfrc" \
  || fail "provision plan did not pin provider installation to the kit mirror"
grep -q "exclude" "$WORKDIR/provision/offline.tfrc" \
  || fail "provision plan left a direct installation path open"
echo "   kit verified, mirror pinned, init resolved every provider offline"

echo "-- 10. complete runtime preparation"
if [[ "$HAS_RUNTIME" == "1" ]]; then
  source_commit="$("$CLI_PYTHON" -c "
import json
import sys
from pathlib import Path
from fdai_deployment_cli.offline_kit import _read_regular

value = json.loads(_read_regular(Path(sys.argv[1]), 1024 * 1024))
print(value[\"source_commit\"])
" "$WORKDIR/authenticated-kit/runtime/release.json")"
  [[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] \
    || fail "runtime release source revision is invalid"
  prepare_output="$("$CLI" offline prepare \
    --offline-kit "$KIT" --release-root "$WORKDIR/release-root.pub" \
    --bundle-public-key "$WORKDIR/bundle-key.pub" \
    --profile "$WORKDIR/offline-profile.json" --source-commit "$source_commit" \
    --work-dir "$WORKDIR/preparation" --output json)" \
    || fail "installed CLI could not prepare the complete runtime release"
  "$CLI_PYTHON" -c "
import json
import sys

value = json.loads(sys.argv[1])
if (
    value.get(\"schema_version\") != \"fdai.offline-preparation.v2\"
    or value.get(\"state\") != \"prepared\"
    or value.get(\"subscription_ready\") is not False
    or value.get(\"mutation_performed\") is not False
    or len(value.get(\"binding\", {}).get(\"image_content_digests\", {})) != 6
):
    raise SystemExit(\"airgap-drill: FAIL - complete preparation receipt is invalid\")
" "$prepare_output"
  echo "   six images and deployment payload prepared without network"

  echo "-- 11. offline deployment-support installation"
  support_output="$("$CLI" offline install-support \
    --offline-kit "$KIT" --release-root "$WORKDIR/release-root.pub" \
    --work-dir "$WORKDIR/support-install" --output json)" \
    || fail "installed CLI could not install deployment support from the signed wheelhouse"
  "$CLI_PYTHON" -c "
import json
import sys

value = json.loads(sys.argv[1])
if (
    value.get(\"schema_version\") != \"fdai.support-installation.v1\"
    or value.get(\"dependencies_verified\") is not True
    or value.get(\"services_started\") is not False
    or value.get(\"cloud_mutation_performed\") is not False
    or value.get(\"subscription_ready\") is not False
    or len(value.get(\"packages\", {})) < 6
):
    raise SystemExit(\"airgap-drill: FAIL - support installation receipt is invalid\")
" "$support_output"
  echo "   runtime support distributions installed and read back without network"
else
  echo "   skipped: no runtime release supplied (toolchain-only drill)"
fi
'

if [[ "$HAS_RUNTIME" -eq 1 ]]; then
  echo "== airgap-drill: OK - complete runtime release prepared with no network =="
else
  echo "== airgap-drill: OK - toolchain path passed; runtime preparation was not exercised =="
fi
