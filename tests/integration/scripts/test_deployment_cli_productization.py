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

    assert "uv build --wheel --project packages/deployment-cli" in stage
    assert "uv export --project packages/deployment-cli --no-dev --no-emit-project" in stage
    assert 'uvx --python "$PYTHON" --from pip pip download' in stage
    assert "pip download --only-binary=:all: --require-hashes" in stage
    assert 'cp "$OUT/wheels"/*.whl "$KIT/python/"' in stage
    assert 'PLATFORM" != "$HOST_PLATFORM"' in stage
    assert 'PLATFORM_TAG" != "$HOST_PLATFORM_TAG"' in stage
    assert 'PLATFORM="${PLATFORM:-$HOST_PLATFORM}"' in stage
    assert 'PLATFORM_TAG="${PLATFORM_TAG:-$HOST_PLATFORM_TAG}"' in stage
    assert "cross-platform kit staging is not supported" in stage
    assert 'aarch64|arm64) PLATFORM_TAG="linux-aarch64"' in drill
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
    assert "fdai_deployment_cli.offline_kit" in signer
    assert "fdai.deployment_cli" not in stage + drill + signer


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
