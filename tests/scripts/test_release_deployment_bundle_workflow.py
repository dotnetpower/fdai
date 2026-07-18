"""Static safety contract for deployment-bundle release automation."""

from pathlib import Path


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
    assert "uv run bash scripts/verify.sh --full" in workflow
    assert "bash scripts/deployment/release/verify-productization.sh" in workflow
    assert "git diff --exit-code" in workflow
    assert "pypa/gh-action-pip-audit@v1.0.8" in workflow
    assert "needs: [verify, dependency-audit]" in workflow
    assert workflow.count("runs-on: ubuntu-24.04") == 3
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
    assert "actions/upload-artifact@v4" in workflow
    assert "if: ${{ inputs.publish_release }}" in workflow
    assert "gh release create" in workflow
    assert "private-key" not in workflow.split("path: release-artifacts/", 1)[1]
