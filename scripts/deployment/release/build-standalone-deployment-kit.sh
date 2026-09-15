#!/usr/bin/env bash
# Build one complete signed deployment kit for online publication or offline media.
set -euo pipefail
umask 077

repo_root="$(git rev-parse --show-toplevel)"
out=""
release_key="${FDAI_DEPLOYMENT_RELEASE_SIGNING_KEY:-$repo_root/secrets/deployment-release-signing-key.pem}"
bundle_key="${FDAI_DEPLOYMENT_BUNDLE_SIGNING_KEY:-$repo_root/secrets/deployment-bundle-signing-key.pem}"
appliance_base_image=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) out="$2"; shift 2 ;;
    --release-key) release_key="$2"; shift 2 ;;
    --bundle-key) bundle_key="$2"; shift 2 ;;
    --appliance-base-image) appliance_base_image="$2"; shift 2 ;;
    *) echo "build-standalone-kit: unsupported argument" >&2; exit 64 ;;
  esac
done

# Preserve caller-relative key references when assembly moves to its private source tree.
[[ "$release_key" = /* ]] || release_key="$PWD/$release_key"
[[ "$bundle_key" = /* ]] || bundle_key="$PWD/$bundle_key"

[[ -n "$out" && "$out" = /* ]] || {
  echo "build-standalone-kit: --out must be an absolute path" >&2
  exit 64
}
[[ ! -e "$out" && ! -L "$out" ]] || {
  echo "build-standalone-kit: a fresh output directory is required; preserve previous releases" >&2
  exit 3
}
python="$repo_root/.venv/bin/python"
[[ -x "$python" ]] || {
  echo "build-standalone-kit: repository development environment is required" >&2
  exit 3
}
release_deadline=$((SECONDS + 10800))
release_runner="$repo_root/scripts/automation/run-bounded-command.py"
# Share the remaining release budget without retrying or detaching child processes.
bounded_stage() {
  local label="$1" limit="$2" idle="$3" remaining=$((release_deadline - SECONDS))
  shift 3
  ((remaining > 0)) || {
    echo "build-standalone-kit: total build deadline exceeded" >&2
    return 124
  }
  ((limit <= remaining)) || limit="$remaining"
  "$python" "$release_runner" \
    --label "$label" --timeout-seconds "$limit" --no-progress-seconds "$idle" -- "$@"
}
[[ -f "$release_key" && ! -L "$release_key" && "$(stat -c '%a' "$release_key")" == "600" ]] || {
  echo "build-standalone-kit: release signing key must be a mode-0600 regular file" >&2
  exit 3
}
[[ -f "$bundle_key" && ! -L "$bundle_key" && "$(stat -c '%a' "$bundle_key")" == "600" ]] || {
  echo "build-standalone-kit: bundle signing key must be a mode-0600 regular file" >&2
  exit 3
}
[[ -z "$(git -C "$repo_root" status --porcelain --untracked-files=all)" ]] || {
  echo "build-standalone-kit: a complete release requires a clean checkout" >&2
  exit 3
}
for tool in docker git node npm sha256sum tar; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "build-standalone-kit: $tool is required" >&2
    exit 3
  }
done

RELEASE_KEY="$release_key" BUNDLE_KEY="$bundle_key" REPO_ROOT="$repo_root" \
  bounded_stage signing-prerequisites 30 30 "$python" - <<'PY'
from __future__ import annotations

import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
  Ed25519PrivateKey,
  Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
  load_pem_private_key,
  load_pem_public_key,
)

root = Path(os.environ["REPO_ROOT"])
for environment, public_name in (
  ("RELEASE_KEY", "deployment-release-root.pub"),
  ("BUNDLE_KEY", "deployment-bundle-root.pub"),
):
  private_path = Path(os.environ[environment])
  details = private_path.lstat()
  if (
    not stat.S_ISREG(details.st_mode)
    or stat.S_IMODE(details.st_mode) != 0o600
    or details.st_uid != os.geteuid()
    or details.st_nlink != 1
  ):
    raise SystemExit("build-standalone-kit: signing key metadata is invalid")
  private = load_pem_private_key(private_path.read_bytes(), password=None)
  public = load_pem_public_key(
    (root / "packages/deployment-cli/src/fdai_deployment_cli/trust" / public_name).read_bytes()
  )
  if (
    not isinstance(private, Ed25519PrivateKey)
    or not isinstance(public, Ed25519PublicKey)
    or private.public_key().public_bytes_raw() != public.public_bytes_raw()
  ):
    raise SystemExit("build-standalone-kit: signing key differs from packaged trust root")
PY

source_commit="$(git -C "$repo_root" rev-parse HEAD)"
source_epoch="$(git -C "$repo_root" show -s --format=%ct "$source_commit")"
"$python" "$repo_root/scripts/deployment/release/workdir-guard.py" create \
  --path "$out" --sentinel .fdai-standalone-release --value fdai-standalone-release-v1
bounded_stage source-checkout 300 120 git -C "$repo_root" worktree add --detach \
  "$out/source" "$source_commit"
repo_root="$out/source"
cd "$repo_root"
UV_PROJECT_ENVIRONMENT="$repo_root/.venv" \
  bounded_stage source-environment 900 300 uv sync --offline --frozen --extra dev --python "$python"
python="$repo_root/.venv/bin/python"
release_runner="$repo_root/scripts/automation/run-bounded-command.py"
source_guard="$repo_root/scripts/deployment/release/release_source.py"
source_fingerprint="$(bounded_stage source-pin 300 300 "$python" "$source_guard" \
  --repo-root "$repo_root" --source-commit "$source_commit")"
source_boundary() {
  bounded_stage "$1" 300 300 "$python" "$source_guard" \
    --repo-root "$repo_root" --source-commit "$source_commit" \
    --source-fingerprint "$source_fingerprint" >/dev/null
}
cli_version="$(PYTHONPATH="$repo_root/packages/deployment-cli/src" "$python" -c \
  'from fdai_deployment_cli.__about__ import __version__; print(__version__)')"
[[ "$source_epoch" =~ ^[0-9]+$ && "$cli_version" =~ ^[0-9]+[.][0-9]+[.][0-9]+$ ]] || {
  echo "build-standalone-kit: release version or source epoch is invalid" >&2
  exit 3
}
release_input="$out/release-input"
stage="$out/stage"
archive="$out/fdai-deployment-kit-${cli_version}-linux-x86_64.tar.gz"
install -d -m 0700 "$release_input" "$release_input/images" "$release_input/metadata"

mapfile -t services < <(
  PYTHONPATH="$repo_root/packages/deployment-cli/src" "$python" -c \
    'from fdai_deployment_cli.runtime_release import RUNTIME_SERVICES; print(*sorted(RUNTIME_SERVICES), sep="\n")'
)
[[ "${#services[@]}" -gt 0 ]] || {
  echo "build-standalone-kit: runtime service inventory is empty" >&2
  exit 3
}

for service in "${services[@]}"; do
  [[ -f "$repo_root/services/$service/docker/Dockerfile" ]] || {
    echo "build-standalone-kit: runtime service Dockerfile is unavailable" >&2
    exit 3
  }
  echo "-- build OCI image: $service"
  bounded_stage "image-$service" 1800 300 docker buildx build \
    --progress=plain \
    --platform linux/amd64 \
    --provenance=false \
    --sbom=false \
    --file "$repo_root/services/$service/docker/Dockerfile" \
    --label "org.opencontainers.image.revision=$source_commit" \
    --output "type=oci,dest=$release_input/images/$service.oci.tar" \
    "$repo_root"
  source_boundary "source-after-$service"
done

cat >"$release_input/metadata/clamav.Dockerfile" <<'EOF'
FROM clamav/clamav@sha256:0af8760cd96f9ab67d07977af36e155431581a9fe9f0ec8b256c9f855fda183e
EOF
echo "-- build OCI image: clamav"
bounded_stage image-clamav 1800 300 docker buildx build \
  --progress=plain \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  --file "$release_input/metadata/clamav.Dockerfile" \
  --output "type=oci,dest=$release_input/images/clamav.oci.tar" \
  "$release_input/metadata"

cat >"$release_input/metadata/pgvector.Dockerfile" <<'EOF'
FROM pgvector/pgvector@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b
EOF
echo "-- build OCI image: pgvector"
bounded_stage image-pgvector 1800 300 docker buildx build \
  --progress=plain \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  --file "$release_input/metadata/pgvector.Dockerfile" \
  --output "type=oci,dest=$release_input/images/pgvector.oci.tar" \
  "$release_input/metadata"

echo "-- build Console artifact"
bounded_stage console-dependencies 600 180 npm --prefix "$repo_root/console" ci --ignore-scripts
bounded_stage console-build 900 300 npm --prefix "$repo_root/console" run build:offline
bounded_stage console-archive 120 120 tar --sort=name --mtime="@$source_epoch" --owner=0 --group=0 --numeric-owner \
  --transform='s,^offline,dist,' \
  -czf "$release_input/console.tar.gz" -C "$repo_root/console/dist" offline
source_boundary source-after-console
printf '{"schema_version":"fdai.deployment-support.v1","source_commit":"%s"}\n' \
  "$source_commit" >"$release_input/metadata/deployment-support.json"
bounded_stage support-archive 120 120 tar --sort=name --mtime="@$source_epoch" --owner=0 --group=0 --numeric-owner \
  -czf "$release_input/deployment-support.tar.gz" \
  -C "$release_input/metadata" deployment-support.json

RELEASE_INPUT="$release_input" SOURCE_COMMIT="$source_commit" \
PYTHONPATH="$repo_root/packages/deployment-cli/src" bounded_stage runtime-metadata 600 600 "$python" - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import tarfile
from pathlib import Path

from fdai_deployment_cli.oci_archive import validate_dependency_oci_archive, validate_oci_archive

root = Path(os.environ["RELEASE_INPUT"])
source_commit = os.environ["SOURCE_COMMIT"]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def declared_manifest(path: Path) -> str:
    with tarfile.open(path, "r:") as archive:
        member = archive.getmember("index.json")
        if member.size > 65536:
            raise SystemExit("OCI index exceeds its bound")
        stream = archive.extractfile(member)
        if stream is None:
            raise SystemExit("OCI index is unavailable")
        value = json.loads(stream.read())
    manifests = value.get("manifests") if isinstance(value, dict) else None
    if not isinstance(manifests, list) or len(manifests) != 1:
        raise SystemExit("OCI archive must declare one manifest")
    result = manifests[0].get("digest") if isinstance(manifests[0], dict) else None
    if not isinstance(result, str):
        raise SystemExit("OCI manifest digest is unavailable")
    return result


def metadata(name: str, archive: Path, image_digest: str) -> dict[str, str]:
    directory = root / "metadata" / name
    directory.mkdir(mode=0o700)
    sbom = directory / "sbom.cdx.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "components": [
                    {
                        "type": "container",
                        "name": name,
                        "hashes": [{"alg": "SHA-256", "content": image_digest.removeprefix("sha256:")}],
                    }
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    provenance = directory / "provenance.jsonl"
    provenance.write_text(
        json.dumps(
            {
                "_type": "https://in-toto.io/Statement/v1",
                "subject": [{"name": name, "digest": {"sha256": image_digest.removeprefix("sha256:")}}],
                "predicateType": "https://slsa.dev/provenance/v1",
                "predicate": {"buildDefinition": {"externalParameters": {"source_commit": source_commit}}},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "archive": archive.relative_to(root).as_posix(),
        "archive_sha256": digest(archive),
        "sbom": sbom.relative_to(root).as_posix(),
        "sbom_sha256": digest(sbom),
        "provenance": provenance.relative_to(root).as_posix(),
        "provenance_sha256": digest(provenance),
        "image_digest": image_digest,
    }


services = {}
for name in (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
):
    archive = root / "images" / f"{name}.oci.tar"
    verified = validate_oci_archive(
        archive,
        expected_source_commit=source_commit,
        expected_archive_sha256=digest(archive),
        expected_manifest_digest=declared_manifest(archive),
        expected_platform_tag="linux-x86_64",
    )
    services[name] = metadata(name, archive, verified.manifest.digest)
clamav_archive = root / "images/clamav.oci.tar"
clamav = validate_dependency_oci_archive(
    clamav_archive,
    expected_archive_sha256=digest(clamav_archive),
    expected_manifest_digest=declared_manifest(clamav_archive),
    expected_platform_tag="linux-x86_64",
)
pgvector_archive = root / "images/pgvector.oci.tar"
pgvector = validate_dependency_oci_archive(
  pgvector_archive,
  expected_archive_sha256=digest(pgvector_archive),
  expected_manifest_digest=declared_manifest(pgvector_archive),
  expected_platform_tag="linux-x86_64",
)

def artifact(name: str) -> dict[str, str]:
    path = root / name
    sbom = root / "metadata" / f"{name}.sbom.cdx.json"
    sbom.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "version": 1,
                "components": [{"type": "file", "name": name, "hashes": [{"alg": "SHA-256", "content": digest(path)}]}],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "archive": path.relative_to(root).as_posix(),
        "archive_sha256": digest(path),
        "sbom": sbom.relative_to(root).as_posix(),
        "sbom_sha256": digest(sbom),
    }

payload = {
    "schema_version": "fdai.runtime-release-build.v1",
    "source_commit": source_commit,
    "platform_tag": "linux-x86_64",
    "services": services,
    "sidecars": {
      "clamav": metadata("clamav", clamav_archive, clamav.manifest.digest),
      "pgvector": metadata("pgvector", pgvector_archive, pgvector.manifest.digest),
    },
    "console": artifact("console.tar.gz"),
    "deployment_support": artifact("deployment-support.tar.gz"),
}
(root / "runtime-release-build.json").write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY

SOURCE_DATE_EPOCH="$source_epoch" bounded_stage kit-staging 7200 900 \
  bash "$repo_root/scripts/deployment/release/stage-offline-kit.sh" \
  --source-commit "$source_commit" --source-fingerprint "$source_fingerprint" \
  --out "$stage" \
  --release-key "$release_key" \
  --bundle-key "$bundle_key" \
  --bundle-version "$cli_version" \
  --runtime-descriptor "$release_input/runtime-release-build.json" \
  --runtime-source-root "$release_input"

source_boundary source-before-archive
bounded_stage kit-archive 1800 900 tar --sort=name --mtime="@$source_epoch" --owner=0 --group=0 --numeric-owner \
  -czf "$archive" -C "$stage" kit
chmod 0600 "$archive"
archive_digest="$(bounded_stage kit-checksum 600 600 sha256sum "$archive" | cut -d' ' -f1)"
[[ "$archive_digest" =~ ^[0-9a-f]{64}$ ]] || {
  echo "build-standalone-kit: archive checksum is unavailable" >&2
  exit 3
}
if [[ -n "$appliance_base_image" ]]; then
  appliance="$out/fdai-deployment-appliance-${cli_version}-linux-x86_64.oci.tar"
  bounded_stage deployment-appliance 1800 300 \
    bash "$repo_root/scripts/deployment/release/build-deployment-appliance.sh" \
    --kit "$archive" \
    --base-image "$appliance_base_image" \
    --output "$appliance"
fi
printf 'standalone-kit: OK archive=%s sha256=%s\n' "$archive" "$archive_digest"
