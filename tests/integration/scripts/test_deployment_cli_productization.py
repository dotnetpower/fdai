from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/deployment-cli"


def test_workspace_registers_installable_fdaictl_distribution() -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))

    assert "packages/deployment-cli" not in root["tool"]["uv"]["workspace"]["members"]
    assert package["project"]["scripts"]["fdaictl"] == "fdai_deployment_cli.cli:main"
    assert package["project"]["name"] == "fdai-deployment-cli"


def test_release_scripts_use_the_installable_distribution() -> None:
    stage = (ROOT / "scripts/deployment/release/stage-offline-kit.sh").read_text(encoding="utf-8")
    drill = (ROOT / "scripts/deployment/release/airgap-drill.sh").read_text(encoding="utf-8")
    signer = (ROOT / "scripts/deployment/release/build-offline-kit.py").read_text(encoding="utf-8")
    issuer = (ROOT / "scripts/deployment/release/issue-license.py").read_text(encoding="utf-8")

    assert "uv lock --check --project packages/deployment-cli" in stage
    assert "uv build --wheel --project packages/deployment-cli" in stage
    assert "uv export --project packages/deployment-cli --locked --no-dev" in stage
    assert "uv run --project packages/deployment-cli --locked --no-dev --group release" in stage
    assert '--python "$PYTHON" python -m pip download' in stage
    assert "pip download --only-binary=:all: --require-hashes" in stage
    assert 'cp "$OUT/wheels"/*.whl "$KIT/python/"' in stage
    assert 'PLATFORM" != "$HOST_PLATFORM"' in stage
    assert 'PLATFORM_TAG" != "$HOST_PLATFORM_TAG"' in stage
    assert 'PLATFORM="${PLATFORM:-$HOST_PLATFORM}"' in stage
    assert 'PLATFORM_TAG="${PLATFORM_TAG:-$HOST_PLATFORM_TAG}"' in stage
    assert "cross-platform kit staging is not supported" in stage
    assert 'STAGE_SENTINEL=".fdai-offline-stage"' in stage
    assert "workdir-guard.py verify" in stage
    assert "--out must be a safe absolute path" in stage
    assert "existing --out is not owned by offline staging" in stage
    assert 'rm -f "$OUT/bundle.tar.gz" "$OUT/cli-requirements.txt"' in stage
    assert 'aarch64|arm64) PLATFORM_TAG="linux-aarch64"' in drill
    assert 'TERRAFORM_VERSION="1.9.8"' in stage
    assert 'OPA_VERSION="0.68.0"' in stage
    assert "186e0145f5e5f2eb97cbd785bc78f21bae4ef15119349f6ad4fa535b83b10df8" in stage
    assert "f85868798834558239f6148834884008f2722548f84034c9b0f62934b2d73ebb" in stage
    assert "dfd5081fc6f930dfeaf2a225e31e616fc227dc0c7b43019b73d6f8fb8a1de1aa" in stage
    assert "1a583e593cdf4931c0b0bbedd3c9f585012953449115bcc3e15b3806d0f5ee68" in stage
    assert 'cp "$(command -v terraform)"' not in stage
    assert 'cp "$(command -v opa)"' not in stage
    assert "fdai_deployment_cli-*-py3-none-any.whl" in stage
    assert "PYTHONPATH=packages/deployment-cli/src" in stage
    assert '"$UV" pip install --python "$WORKDIR/cli-venv/bin/python"' in drill
    assert '--no-index --find-links "$WORKDIR/authenticated-kit/python"' in drill
    assert 'CLI="$WORKDIR/cli-venv/bin/fdaictl"' in drill
    external_verify = drill.index("externally verify offline kit before executing it")
    install = drill.index("install authenticated shipped CLI from kit wheels")
    assert external_verify < install
    assert "PYTHONPATH=packages/deployment-cli/src" in drill[external_verify:install]
    assert "materialize_verified_artifacts" in drill[external_verify:install]
    assert "extract_bundle_archive" in drill[external_verify:install]
    assert "verify_bundle" in drill[external_verify:install]
    assert "tar -xzf" not in drill
    assert 'TFBIN="$WORKDIR/authenticated-kit/terraform/terraform"' in drill
    assert 'path    = "$WORKDIR/authenticated-kit/terraform/providers"' in drill
    assert 'TFBIN="$KIT/terraform/terraform"' not in drill
    assert '--variables-file "$WORKDIR/plan-input.tfvars.json"' in drill
    assert '--profile "$WORKDIR/offline-profile.json"' in drill
    assert "FDAI-PLAN-ONLY-NOT-A-SECRET" in drill
    assert "No value for required variable" not in drill
    assert "terraform_provider_authentication_unavailable" in drill
    assert "PYTHONPATH=services/core-control-plane/src:packages/service-contracts/src" in drill
    assert 'mkdir -m 700 "$WORKDIR/empty-azure"' in drill
    assert '"$WORKDIR/cli-venv" "$WORKDIR/empty-azure"' in drill
    assert 'export AZURE_CONFIG_DIR="$WORKDIR/empty-azure"' in drill
    assert "unset PYTHONPATH PYTHONHOME" in drill
    assert "for tool in az curl git openssl unshare uv" in drill
    assert "for tool in az terraform" not in drill
    assert 'SENTINEL=".fdai-airgap-workdir"' in drill
    assert "workdir-guard.py create" in drill
    assert "workdir-guard.py verify" in drill
    assert "a fresh workdir is required" in drill
    assert "--skip-stage requires an owned drill workdir" in drill
    assert "sentinel_value" not in drill
    assert 'rm -rf "$WORKDIR"' not in drill
    assert "fdai_deployment_cli.offline_kit" in signer
    assert "fdai.deployment_cli" not in stage + drill + signer
    assert "fdai.delivery.trust.ed25519" not in issuer
    assert "load_pem_public_key" in issuer


def test_source_entrypoint_reports_stable_version_json() -> None:
    uv = shutil.which("uv")
    assert uv is not None
    completed = subprocess.run(  # noqa: S603 - fixed local uv executable and arguments
        [
            uv,
            "run",
            "--project",
            "packages/deployment-cli",
            "fdaictl",
            "version",
            "--output",
            "json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.stdout == ('{"schema_version":"fdai.version.v1","version":"0.1.0"}\n')


def test_release_tooling_is_exactly_pinned() -> None:
    package = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    assert package["build-system"]["requires"] == ["hatchling==1.31.0"]
    assert package["dependency-groups"]["release"] == ["pip==26.2.1"]
