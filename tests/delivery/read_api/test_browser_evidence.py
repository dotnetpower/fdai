from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.browser_evidence.service import InMemoryBrowserEvidenceArtifactStore
from fdai.delivery.read_api.routes.browser_evidence import BrowserEvidencePanel
from fdai.delivery.read_api.routes.panels import PanelQueryError
from fdai.shared.providers.browser_evidence import (
    BrowserEvidenceArtifact,
    BrowserEvidencePayload,
    BrowserRedactionEntry,
    BrowserRuntimeIsolation,
    StoredBrowserEvidence,
)


async def _panel() -> BrowserEvidencePanel:
    store = InMemoryBrowserEvidenceArtifactStore()
    captured_at = datetime(2026, 7, 21, 12, tzinfo=UTC)
    await store.put(
        StoredBrowserEvidence(
            artifact=BrowserEvidenceArtifact(
                artifact_id="sha256:" + "a" * 64,
                policy_id="dashboard",
                policy_version=1,
                canonical_source_url="https://dashboard.example/evidence",
                canonical_final_url="https://dashboard.example/evidence",
                captured_at=captured_at,
                selectors=("main",),
                screenshot_hash=None,
                text_hash=None,
                snapshot_hash=None,
                redaction_manifest=(
                    BrowserRedactionEntry(
                        surface="visible_text",
                        rule="secret-canary-1",
                        replacements=2,
                    ),
                ),
                browser_version="chromium-test",
                chain_of_custody_audit_ref="audit:browser:1",
                content_digest="a" * 64,
                prompt_injection_findings=("instruction_override",),
                isolation=BrowserRuntimeIsolation(
                    executor_identity_present=False,
                    host_filesystem_mounted=False,
                    environment_scrubbed=True,
                    restricted_egress=True,
                    ephemeral_profile=True,
                ),
                expires_at=captured_at + timedelta(days=7),
            ),
            payload=BrowserEvidencePayload(
                screenshot=None,
                visible_text=None,
                aria_snapshot=None,
            ),
        )
    )
    return BrowserEvidencePanel(store)


async def test_panel_exposes_bounded_metadata_without_capture_content_or_controls() -> None:
    result = await (await _panel()).render(params={"limit": "10"})

    assert result["read_only"] is True
    assert result["shadow_only"] is True
    assert result["capture_controls"] is False
    assert result["promotion_controls"] is False
    assert result["mutation_controls"] is False
    artifact = result["artifacts"][0]
    assert artifact["redaction_count"] == 2
    assert artifact["isolation_verified"] is True
    assert artifact["can_authorize_action"] is False
    assert "screenshot" not in artifact
    assert "visible_text" not in artifact
    assert "aria_snapshot" not in artifact


@pytest.mark.parametrize("limit", ["0", "201", "invalid"])
async def test_panel_rejects_invalid_limit(limit: str) -> None:
    with pytest.raises(PanelQueryError):
        await (await _panel()).render(params={"limit": limit})
