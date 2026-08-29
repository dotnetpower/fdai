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

set -euo pipefail

WORKDIR="${TMPDIR:-/tmp}/fdai-airgap-drill"
SKIP_STAGE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) WORKDIR="$2"; shift 2 ;;
    --skip-stage) SKIP_STAGE=1; shift ;;
    *) echo "airgap-drill: unknown argument: $1" >&2; exit 2 ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
SENTINEL=".fdai-airgap-workdir"
if [[ "$WORKDIR" != /* || "$WORKDIR" == "/" || "$WORKDIR" == "$HOME" || "$WORKDIR" == "$repo_root" ]]; then
  echo "airgap-drill: workdir must be a safe absolute path outside the repository and home." >&2
  exit 2
fi
if [[ -L "$WORKDIR" ]]; then
  echo "airgap-drill: workdir must not be a symbolic link." >&2
  exit 2
fi
if [[ "$SKIP_STAGE" -eq 0 ]]; then
  if [[ -e "$WORKDIR" ]]; then
    echo "airgap-drill: a fresh workdir is required." >&2
    exit 2
  fi
  mkdir -m 700 "$WORKDIR"
  printf 'fdai-airgap-drill-v1\n' > "$WORKDIR/$SENTINEL"
  chmod 600 "$WORKDIR/$SENTINEL"
else
  sentinel_value=""
  if [[ -f "$WORKDIR/$SENTINEL" && ! -L "$WORKDIR/$SENTINEL" ]]; then
    IFS= read -r sentinel_value < "$WORKDIR/$SENTINEL" || true
  fi
  if [[ ! -d "$WORKDIR" || "$sentinel_value" != "fdai-airgap-drill-v1" ]]; then
    echo "airgap-drill: --skip-stage requires an owned drill workdir." >&2
    exit 2
  fi
fi

for tool in az curl git openssl unshare uv; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "airgap-drill: BLOCKED - $tool is required." >&2
    exit 2
  }
done
PYTHON="$repo_root/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo "airgap-drill: BLOCKED - .venv is missing." >&2; exit 2; }

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
  openssl genpkey -algorithm ed25519 -out "$WORKDIR/bundle-key.pem" 2>/dev/null
  openssl genpkey -algorithm ed25519 -out "$WORKDIR/release-key.pem" 2>/dev/null
  chmod 600 "$WORKDIR"/*.pem

  # The drill runs the real release staging script, so a green drill exercises
  # the release path itself rather than a second copy of it.
  bash scripts/deployment/release/stage-offline-kit.sh \
    --out "$WORKDIR" \
    --release-key "$WORKDIR/release-key.pem" \
    --bundle-key "$WORKDIR/bundle-key.pem" \
    --bundle-version "$BUNDLE_VERSION" \
    --platform-tag "$PLATFORM_TAG" >/dev/null

  echo "-- issue a drill license"
  PYTHONPATH=services/core-control-plane/src:packages/service-contracts/src \
    "$PYTHON" scripts/deployment/release/issue-license.py \
    --private-key "$WORKDIR/release-key.pem" --public-key "$WORKDIR/release-root.pub" \
    --license-id lic-drill-0001 --distribution-id example-distribution \
    --capability cost.metering --valid-days 30 \
    --output "$WORKDIR/license.token" >/dev/null

  cat > "$WORKDIR/offline.tfrc" <<EOF
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
rm -rf "$WORKDIR/work" "$WORKDIR/negative" "$WORKDIR/authenticated-kit" \
  "$WORKDIR/cli-venv" "$WORKDIR/empty-azure"
mkdir -m 700 "$WORKDIR/empty-azure"

# The kit declares which CLI it was built for; verification binds that exact
# value, so read it rather than assume the local environment matches.
CLI_VERSION="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["cli_version"])' "$KIT/offline-kit.json")"
cat > "$WORKDIR/plan-input.tfvars.json" <<'EOF'
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
chmod 600 "$WORKDIR/plan-input.tfvars.json"
cat > "$WORKDIR/offline-profile.json" <<'EOF'
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
chmod 600 "$WORKDIR/offline-profile.json"

echo "== verify (network namespace, no route, no DNS) =="
REPO_ROOT="$repo_root" WORKDIR="$WORKDIR" KIT="$KIT" PYTHON="$PYTHON" UV="$(command -v uv)" \
  CLI_VERSION="$CLI_VERSION" PLATFORM_TAG="$PLATFORM_TAG" BUNDLE_VERSION="$BUNDLE_VERSION" \
  unshare -rn -- bash -euo pipefail -c '
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
from fdai_deployment_cli.offline_kit import materialize_verified_artifacts, verify_offline_kit
result = verify_offline_kit(
    Path(sys.argv[1]),
    release_root_pem=Path(sys.argv[2]).read_bytes(),
    cli_version=sys.argv[3],
    platform_tag=sys.argv[4],
)
artifacts = materialize_verified_artifacts(Path(sys.argv[1]), result, Path(sys.argv[5]))
bundle_root = extract_bundle_archive(artifacts.deployment_bundle, Path(sys.argv[6]))
verify_bundle(
    bundle_root,
    public_key_pem=Path(sys.argv[7]).read_bytes(),
    cli_version=sys.argv[3],
)
print(f\"   verified {result.file_count} files, {result.total_bytes} bytes\")
" "$KIT" "$WORKDIR/release-root.pub" "$CLI_VERSION" "$PLATFORM_TAG" \
  "$WORKDIR/authenticated-kit" "$WORKDIR/work" "$WORKDIR/bundle-key.pub"
cp -r "$BUNDLE/infra" "$WORKDIR/negative"

echo "-- install authenticated shipped CLI from kit wheels"
"$UV" venv --python "$PYTHON" "$WORKDIR/cli-venv" >/dev/null
"$UV" pip install --python "$WORKDIR/cli-venv/bin/python" \
  --no-index --find-links "$WORKDIR/authenticated-kit/python" \
  "fdai-deployment-cli==$CLI_VERSION" >/dev/null
CLI="$WORKDIR/cli-venv/bin/fdaictl"
CLI_PYTHON="$WORKDIR/cli-venv/bin/python"
"$CLI" version --output json >/dev/null

# Recheck through the installed distribution so the shipped import path is also exercised.
"$CLI_PYTHON" -c "
import sys
from pathlib import Path
from fdai_deployment_cli.offline_kit import verify_offline_kit
verify_offline_kit(
    Path(sys.argv[1]),
    release_root_pem=Path(sys.argv[2]).read_bytes(),
    cli_version=sys.argv[3],
    platform_tag=sys.argv[4],
)
" "$KIT" "$WORKDIR/release-root.pub" "$CLI_VERSION" "$PLATFORM_TAG"
# Kit verification proves the SBOM has not been tampered with; it cannot notice
# that the SBOM describes nothing. An empty components array reads as compliant
# and gives a recipient no supply-chain visibility, so assert the content too.
"$PYTHON" - "$KIT" <<'"'"'PY'"'"'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "offline-kit.json").read_text(encoding="utf-8"))
sbom = json.loads((root / manifest["sbom_path"]).read_text(encoding="utf-8"))
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
'

echo "== airgap-drill: OK - every disconnected step passed with no network =="
