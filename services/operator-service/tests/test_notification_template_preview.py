"""Focused checks for service-owned notification template previews."""

from pathlib import Path

from fdai_operator_service.notification_template_preview import (
    incident_opened_template_preview,
)
from fdai_operator_service.redaction import redact_projection

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_incident_opened_preview_matches_the_reviewed_design_specimen() -> None:
    preview = incident_opened_template_preview()
    design = (REPO_ROOT / "mocks/email-template/incident-opened.html").read_text(encoding="utf-8")

    assert preview == {
        "key": "incident-opened",
        "subject": "[SEV2] Incident opened - API latency after configuration rollout",
        "plain_text": (
            "SEV2 incident opened at 06:03 UTC. Eight signals were correlated. "
            "No recovery action has run."
        ),
        "html": design,
    }


def test_incident_opened_preview_preserves_the_safe_email_boundary() -> None:
    preview = incident_opened_template_preview()
    html = preview["html"]

    assert isinstance(html, str)
    assert 'class="wrap" width="640"' in html
    assert "FDAI / FIELD DISPATCH" in html
    assert "Fail-closed" in html
    assert "approval and execution stay in the console" in html
    assert "<script" not in html.lower()
    assert "<form" not in html.lower()
    assert redact_projection(preview) == preview
