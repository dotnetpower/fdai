from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[3]
ENTRYPOINT = ROOT / "scripts/deployment/azure/run-deployment-appliance.sh"
BUILDER = ROOT / "scripts/deployment/release/build-deployment-appliance.sh"
RELEASE_BUILDER = ROOT / "scripts/deployment/release/build-standalone-deployment-kit.sh"
_BASH = "/usr/bin/bash"


def test_appliance_scripts_are_valid_and_github_independent() -> None:
    for script in (ENTRYPOINT, BUILDER, RELEASE_BUILDER):
        subprocess.run((_BASH, "-n", str(script)), check=True)  # noqa: S603

    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "fdaictl provision azure" in entrypoint
    assert "--offline-kit" in entrypoint
    assert "--client-id" in entrypoint
    assert "FDAI_DEPLOYMENT_APPLIANCE_MI_CLIENT_ID" in entrypoint
    assert "github" not in entrypoint.casefold()
    assert "gh " not in entrypoint
    release_builder = RELEASE_BUILDER.read_text(encoding="utf-8")
    assert "--appliance-base-image" in release_builder
    assert "build-deployment-appliance.sh" in release_builder
    builder = BUILDER.read_text(encoding="utf-8")
    assert "--network none" in builder
    assert "--pull=false" in builder
    assert 'docker image inspect "$base_image"' in builder
    assert "org.opencontainers.image.revision" in builder
    assert "io.fdai.deployment-kit-manifest" in builder


def test_appliance_builder_requires_digest_pinned_base_image(tmp_path: Path) -> None:
    completed = subprocess.run(  # noqa: S603
        (
            _BASH,
            str(BUILDER),
            "--kit",
            str(tmp_path / "kit"),
            "--base-image",
            "example.invalid/fdai-deployer:latest",
            "--output",
            str(tmp_path / "appliance.oci.tar"),
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 64
    assert "immutable sha256 digest" in completed.stderr
    assert not (tmp_path / "appliance.oci.tar").exists()
