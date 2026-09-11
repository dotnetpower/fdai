#!/usr/bin/env bash
# Prepare a lock-bound Terraform provider mirror for the public contributor path.

prepare_contributor_terraform() {
  local repo_root="$1"
  local work_dir="$2"
  local platform_root="$repo_root/infra"
  local core_root="$platform_root/services/core-control-plane"
  local platform_lock="$platform_root/.terraform.lock.hcl"
  local core_lock="$core_root/.terraform.lock.hcl"
  local platform_digest core_digest lock_digest mirror_root platform_mirror core_mirror lock_file
  local platform_bootstrap_data core_bootstrap_data platform_verify_data core_verify_data
  local bootstrap_config platform_config core_config temporary

  for lock_file in "$platform_lock" "$core_lock"; do
    [[ -f "$lock_file" && ! -L "$lock_file" ]] || {
      echo "azd-up: ERROR: Terraform provider lock is unavailable" >&2
      return 1
    }
  done
  platform_digest="$(sha256sum "$platform_lock" | cut -d' ' -f1)"
  core_digest="$(sha256sum "$core_lock" | cut -d' ' -f1)"
  [[ "$platform_digest" =~ ^[0-9a-f]{64}$ && "$core_digest" =~ ^[0-9a-f]{64}$ ]] || {
    echo "azd-up: ERROR: Terraform provider lock digest is invalid" >&2
    return 1
  }
  lock_digest="$(printf '%s\n%s\n' "$platform_digest" "$core_digest" | sha256sum | cut -d' ' -f1)"
  mirror_root="$work_dir/provider-mirror-$lock_digest"
  platform_mirror="$mirror_root/platform"
  core_mirror="$mirror_root/core"
  platform_bootstrap_data="$work_dir/provider-bootstrap-platform-$lock_digest"
  core_bootstrap_data="$work_dir/provider-bootstrap-core-$lock_digest"
  platform_verify_data="$work_dir/provider-verify-platform-$lock_digest"
  core_verify_data="$work_dir/provider-verify-core-$lock_digest"
  bootstrap_config="$work_dir/terraformrc-bootstrap-$lock_digest"
  platform_config="$work_dir/terraformrc-platform-$lock_digest"
  core_config="$work_dir/terraformrc-core-$lock_digest"

  rm -rf -- \
    "$mirror_root" "$platform_bootstrap_data" "$core_bootstrap_data" \
    "$platform_verify_data" "$core_verify_data" "$bootstrap_config" \
    "$platform_config" "$core_config"
  install -d -m 0700 \
    "$platform_mirror" "$core_mirror" \
    "$platform_bootstrap_data" "$core_bootstrap_data" \
    "$platform_verify_data" "$core_verify_data"
  temporary="$bootstrap_config.tmp-$$"
  DESTINATION="$temporary" python3 - <<'PY'
import os

flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(os.environ["DESTINATION"], flags, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    stream.write("provider_installation {\n  direct {}\n}\n")
    stream.flush()
    os.fsync(stream.fileno())
PY
  mv -- "$temporary" "$bootstrap_config"
  chmod 0600 "$bootstrap_config"
  export TF_CLI_CONFIG_FILE="$bootstrap_config"

  TF_DATA_DIR="$platform_bootstrap_data" terraform -chdir="$platform_root" init \
    -backend=false -input=false -lockfile=readonly >/dev/null
  TF_DATA_DIR="$platform_bootstrap_data" terraform -chdir="$platform_root" providers mirror \
    "$platform_mirror" >/dev/null
  TF_DATA_DIR="$core_bootstrap_data" terraform -chdir="$core_root" init \
    -backend=false -input=false -lockfile=readonly >/dev/null
  TF_DATA_DIR="$core_bootstrap_data" terraform -chdir="$core_root" providers mirror \
    "$core_mirror" >/dev/null

  PLATFORM_MIRROR="$platform_mirror" CORE_MIRROR="$core_mirror" \
  PLATFORM_DESTINATION="$platform_config.tmp-$$" \
  CORE_DESTINATION="$core_config.tmp-$$" python3 - <<'PY'
import json
import os

platform_mirror = json.dumps(os.environ["PLATFORM_MIRROR"])
core_mirror = json.dumps(os.environ["CORE_MIRROR"])

for destination_key, mirror in (
    ("PLATFORM_DESTINATION", platform_mirror),
    ("CORE_DESTINATION", core_mirror),
):
    content = (
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f"    path    = {mirror}\n"
        '    include = ["registry.terraform.io/*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["registry.terraform.io/*/*"]\n'
        "  }\n"
        "}\n"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(os.environ[destination_key], flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
PY
  mv -- "$platform_config.tmp-$$" "$platform_config"
  mv -- "$core_config.tmp-$$" "$core_config"
  chmod 0600 "$platform_config" "$core_config"
  export PLATFORM_TF_CLI_CONFIG_FILE="$platform_config"
  export CORE_TF_CLI_CONFIG_FILE="$core_config"
  export TF_CLI_CONFIG_FILE="$PLATFORM_TF_CLI_CONFIG_FILE"

  TF_CLI_CONFIG_FILE="$PLATFORM_TF_CLI_CONFIG_FILE" \
  TF_DATA_DIR="$platform_verify_data" terraform -chdir="$platform_root" init \
    -backend=false -input=false -upgrade -lockfile=readonly >/dev/null
  TF_CLI_CONFIG_FILE="$CORE_TF_CLI_CONFIG_FILE" \
  TF_DATA_DIR="$core_verify_data" terraform -chdir="$core_root" init \
    -backend=false -input=false -upgrade -lockfile=readonly >/dev/null
  [[ "$(sha256sum "$platform_lock" | cut -d' ' -f1)" == "$platform_digest" \
    && "$(sha256sum "$core_lock" | cut -d' ' -f1)" == "$core_digest" ]] || {
    echo "azd-up: ERROR: locked provider verification changed the dependency lock" >&2
    return 1
  }
}
