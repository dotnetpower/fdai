"""Static safety contract for deployment-bundle release automation."""

import subprocess
from pathlib import Path

import yaml

PIP_AUDIT_SHA = "1220774d901786e6f652ae159f7b6bc8fea6d266"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWNLOAD_ARTIFACT_SHA = "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
PYPI_PUBLISH_SHA = "2834a314042ef964da07689278dd1e9d773e8afd"


def test_release_workflow_is_approval_gated_reproducible_and_secret_safe() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "release-deployment-bundle.yml"
    ).read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in workflow
    assert "image: pgvector/pgvector:pg16" in workflow
    assert "FDAI_DATABASE_URL:" in workflow
    assert "npm --prefix console ci --no-audit --no-fund" in workflow
    assert "uv run alembic upgrade head" in workflow
    assert "uv run bash scripts/verify.sh --all" in workflow
    assert "bash scripts/deployment/release/verify-productization.sh" in workflow
    assert "git diff --exit-code" in workflow
    assert f"pypa/gh-action-pip-audit@{PIP_AUDIT_SHA}" in workflow
    assert "needs: [verify, dependency-audit]" in workflow
    assert workflow.count("runs-on: ubuntu-24.04") == 6
    assert "environment: release" in workflow
    assert "contents: write" in workflow
    assert "FDAI_BUNDLE_SIGNING_KEY_PEM" in workflow
    assert "release_channel:" in workflow
    assert '--release-channel "$RELEASE_CHANNEL"' in workflow
    assert "umask 077" in workflow
    assert "trap 'rm -f \"$signing_key\"' EXIT" in workflow
    assert "export SOURCE_DATE_EPOCH=" in workflow
    assert workflow.count("build_bundle ") == 2
    assert "diff -qr first/bundle second/bundle" in workflow
    assert "cmp first/bundle.tar.gz second/bundle.tar.gz" in workflow
    assert "fdaictl bundle verify" in workflow
    assert f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}" in workflow
    assert "if: ${{ inputs.publish_release }}" in workflow
    assert "gh release create" in workflow
    assert "private-key" not in workflow.split("path: release-artifacts/", 1)[1]


def test_release_workflow_publishes_the_verified_python_artifact_with_oidc() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "release-deployment-bundle.yml"
    ).read_text(encoding="utf-8")

    assert "publish_pypi:" in workflow
    assert "inputs.publish_pypi && !inputs.publish_release" in workflow
    assert 'project["version"]' in workflow
    assert "uv build --out-dir python-dist" in workflow
    assert "uvx --from twine twine check python-dist/*" in workflow
    assert "fdai-python-${{ inputs.bundle_version }}" in workflow
    assert "needs: [python-package, bundle]" in workflow
    assert "environment:\n      name: pypi" in workflow
    assert "id-token: write" in workflow
    assert f"actions/download-artifact@{DOWNLOAD_ARTIFACT_SHA}" in workflow
    assert f"pypa/gh-action-pypi-publish@{PYPI_PUBLISH_SHA}" in workflow
    assert "if: ${{ inputs.publish_pypi }}" in workflow
    assert "PYPI_API_TOKEN" not in workflow


def test_python_distribution_jobs_are_structurally_executable() -> None:
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "release-deployment-bundle.yml"
    )
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    workflow_dispatch = workflow[True]["workflow_dispatch"]
    inputs = workflow_dispatch["inputs"]
    assert set(inputs) == {
        "commit_sha",
        "bundle_version",
        "release_channel",
        "min_cli_version",
        "max_cli_version",
        "publish_release",
        "publish_pypi",
    }
    assert set(inputs["max_cli_version"]) == {
        "description",
        "type",
        "required",
    }
    package_job = workflow["jobs"]["python-package"]
    publish_job = workflow["jobs"]["publish-pypi"]
    version_step = next(
        step
        for step in package_job["steps"]
        if step.get("name") == "Validate package and bundle versions"
    )

    subprocess.run(
        ["/usr/bin/bash", "-n"],
        input=version_step["run"],
        text=True,
        check=True,
    )
    assert package_job["permissions"] == {"contents": "read"}
    assert publish_job["permissions"] == {"contents": "read", "id-token": "write"}
    assert all("run" not in step for step in publish_job["steps"])
