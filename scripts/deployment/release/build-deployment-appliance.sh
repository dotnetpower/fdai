#!/usr/bin/env bash
# Build one OCI deployment appliance from a verified complete signed kit.
set -euo pipefail
umask 077

repo_root="$(git rev-parse --show-toplevel)"
kit=""
base_image=""
output=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kit) kit="$2"; shift 2 ;;
    --base-image) base_image="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    *) echo "build-deployment-appliance: unsupported argument" >&2; exit 64 ;;
  esac
done

[[ "$kit" = /* && "$output" = /* ]] || {
  echo "build-deployment-appliance: --kit and --output must be absolute paths" >&2
  exit 64
}
[[ "$base_image" =~ ^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$ ]] || {
  echo "build-deployment-appliance: --base-image must use an immutable sha256 digest" >&2
  exit 64
}
[[ ! -e "$output" && ! -L "$output" ]] || {
  echo "build-deployment-appliance: output already exists" >&2
  exit 3
}
for tool in docker git sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "build-deployment-appliance: required tool is unavailable: $tool" >&2
    exit 3
  }
done
python="$repo_root/.venv/bin/python"
[[ -x "$python" ]] || {
  echo "build-deployment-appliance: repository development environment is required" >&2
  exit 3
}
docker buildx version >/dev/null 2>&1 || {
  echo "build-deployment-appliance: Docker buildx is unavailable" >&2
  exit 3
}
docker image inspect "$base_image" >/dev/null 2>&1 || {
  echo "build-deployment-appliance: digest-pinned base image is not available locally" >&2
  exit 3
}

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
chmod 0700 "$work"
context="$work/context"
verify="$work/verify"
install -d -m 0700 "$context" "$verify"

verification="$({
  KIT="$kit" VERIFY="$verify" CONTEXT="$context" \
    PYTHONPATH="$repo_root/packages/deployment-cli/src" "$python" - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

from fdai_deployment_cli.deployment_kit import acquire_deployment_kit, archive_verified_kit

kit = acquire_deployment_kit(
    work_dir=Path(os.environ["VERIFY"]),
    online=False,
    offline_kit=Path(os.environ["KIT"]),
)
archive = Path(os.environ["CONTEXT"]) / "kit.tar.gz"
archive_verified_kit(kit, archive)
copied_work = Path(os.environ["VERIFY"]) / "copied"
copied_work.mkdir(mode=0o700)
copied = acquire_deployment_kit(
  work_dir=copied_work,
    online=False,
    offline_kit=archive,
)
if (
    copied.verification.manifest_digest != kit.verification.manifest_digest
    or copied.runtime.digest != kit.runtime.digest
    or copied.source_commit != kit.source_commit
):
    raise SystemExit("copied appliance kit identity differs")
print(
  copied.verification.cli_version,
  copied.source_commit,
  copied.verification.manifest_digest,
)
PY
} 2>"$work/verification.err")" || {
  cat "$work/verification.err" >&2
  exit 3
}
read -r cli_version source_commit kit_manifest_digest <<<"$verification"
[[ "$cli_version" =~ ^[0-9]+[.][0-9]+[.][0-9]+$ \
  && "$source_commit" =~ ^[0-9a-f]{40}$ \
  && "$kit_manifest_digest" =~ ^[0-9a-f]{64}$ ]] || {
  echo "build-deployment-appliance: verified kit identity is invalid" >&2
  exit 3
}

cp "$repo_root/scripts/deployment/azure/run-deployment-appliance.sh" "$context/entrypoint.sh"
chmod 0755 "$context/entrypoint.sh"
cat >"$context/Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
ARG CLI_VERSION
ARG SOURCE_COMMIT
ARG KIT_MANIFEST_DIGEST
LABEL org.opencontainers.image.revision="${SOURCE_COMMIT}"
LABEL io.fdai.deployment-kit-manifest="${KIT_MANIFEST_DIGEST}"
COPY kit.tar.gz /opt/fdai/kit.tar.gz
COPY entrypoint.sh /usr/local/bin/fdai-deploy
RUN install -d -m 0700 /opt/fdai/kit \
  && tar -xzf /opt/fdai/kit.tar.gz -C /opt/fdai/kit --strip-components=1 \
  && python3 -m pip install --no-cache-dir --no-index \
      --find-links=/opt/fdai/kit/python "fdai-deployment-cli==${CLI_VERSION}" \
    && command -v az >/dev/null \
    && command -v fdaictl >/dev/null \
    && command -v scp >/dev/null \
    && command -v ssh >/dev/null \
    && command -v tar >/dev/null \
    && chmod 0755 /usr/local/bin/fdai-deploy
ENV FDAI_DEPLOYMENT_APPLIANCE=1
ENTRYPOINT ["/usr/local/bin/fdai-deploy"]
EOF

docker buildx build \
  --platform linux/amd64 \
  --network none \
  --pull=false \
  --provenance=true \
  --sbom=true \
  --build-arg "BASE_IMAGE=$base_image" \
  --build-arg "CLI_VERSION=$cli_version" \
  --build-arg "SOURCE_COMMIT=$source_commit" \
  --build-arg "KIT_MANIFEST_DIGEST=$kit_manifest_digest" \
  --output "type=oci,dest=$work/appliance.oci.tar" \
  "$context"
BUILT="$work/appliance.oci.tar" OUTPUT="$output" \
  PYTHONPATH="$repo_root/packages/deployment-cli/src" "$python" - <<'PY'
import os
from pathlib import Path

from fdai_deployment_cli.private_output import copy_private_file

copy_private_file(
    Path(os.environ["BUILT"]),
    Path(os.environ["OUTPUT"]),
    max_bytes=16 * 1024 * 1024 * 1024,
)
PY
printf 'deployment-appliance: OK image=%s sha256=%s\n' \
  "$output" "$(sha256sum "$output" | cut -d' ' -f1)"
