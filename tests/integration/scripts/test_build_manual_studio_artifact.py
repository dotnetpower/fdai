"""Tests for the allowlisted Manual Studio deployment artifact."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MODULE_PATH = _ROOT / "scripts" / "deployment" / "azure" / "build_manual_studio_artifact.py"
_PUBLISHER_PATH = _ROOT / "scripts" / "deployment" / "azure" / "publish-console.sh"
_WORKFLOW_PATH = _ROOT / ".github" / "workflows" / "publish-console.yml"
_SPEC = importlib.util.spec_from_file_location("build_manual_studio_artifact", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_build_artifact_copies_only_publishable_manual_files(tmp_path: Path) -> None:
    output = tmp_path / "manuals"

    copied = _MODULE.build_artifact(_ROOT, output)

    copied_names = {path.relative_to(output).as_posix() for path in copied}
    assert {
        "app.js",
        "catalog.json",
        "executive-deck.css",
        "executive-story.css",
        "library.html",
        "manual-content.js",
        "manual-decks.css",
        "presentation-standard.css",
        "sre-incident-response.css",
        "sre-incident-response.js",
        "styles.css",
    } <= copied_names
    assert "assets/executive-briefing.jpeg" in copied_names
    assert "assets/provenance.json" in copied_names
    assert "server.mjs" not in copied_names
    assert "package.json" not in copied_names
    assert not any(name.startswith("test/") for name in copied_names)
    assert (output / "catalog.json").read_bytes() == (
        _ROOT / "tools" / "manual-studio" / "catalog.json"
    ).read_bytes()


def test_console_publisher_binds_and_verifies_same_origin_manuals() -> None:
    publisher = _PUBLISHER_PATH.read_text(encoding="utf-8")

    assert 'VITE_MANUAL_STUDIO_URL="https://$hostname/manuals"' in publisher
    assert "build_manual_studio_artifact.py" in publisher
    assert '"https://$hostname/manuals/$manual_file"' in publisher
    assert "sha256sum --check --status" in publisher
    assert "resolve_service_fqdn operator-service" in publisher
    assert "resolve_service_fqdn document-ingestion-api" in publisher
    assert 'state_key="services/$service/$FDAI_DEPLOY_ENVIRONMENT.tfstate"' in publisher
    assert "jq -er '.fqdn | select(type == \"string\" and length > 0)'" in publisher
    assert "DEPLOY_OPERATOR_API" not in publisher
    assert "DEPLOY_DOCUMENT_INGESTION" not in publisher


def test_console_static_publish_workflow_requires_exact_green_main_revision() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "inputs.commit_sha == github.sha" in workflow
    assert "runs-on: [self-hosted, fdai-deploy]" in workflow
    assert 'select(.name == "required")' in workflow
    assert "verify-github-environment.py" in workflow
    assert "login-deploy-identity.sh" in workflow
    assert "terraform init -input=false" in workflow
    assert "CONSOLE_DEFAULT_HOSTNAME: ${{ vars.CONSOLE_DEFAULT_HOSTNAME }}" in workflow
    assert "CONSOLE_STATIC_WEB_APP_ID: ${{ vars.CONSOLE_STATIC_WEB_APP_ID }}" in workflow
    assert "FDAI_DEPLOY_ENVIRONMENT: ${{ inputs.environment }}" in workflow
    assert (
        "STATE_RESOURCE_GROUP: ${{ vars.STATE_RESOURCE_GROUP || vars.OPS_RESOURCE_GROUP_NAME }}"
        in workflow
    )
    assert "STATE_STORAGE_ACCOUNT: ${{ vars.STATE_STORAGE_ACCOUNT }}" in workflow
    assert "publish-console.sh infra" in workflow
