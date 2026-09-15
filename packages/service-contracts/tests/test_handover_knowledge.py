"""Knowledge transport is a strict bounded source reference with no promotion authority."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.handover_knowledge import (
    HandoverKnowledgeDecision,
    HandoverKnowledgeNotice,
)


def _notice():
    return HandoverKnowledgeNotice(
        source="operator",
        goal_id="goal:example",
        goal_revision=1,
        source_digest="a" * 64,
        check_epoch=100,
    )


@pytest.mark.parametrize("field", ["may_promote", "execution_authority", "review_required"])
@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_authority_flags_are_exact_booleans(field, value):
    with pytest.raises(ValueError):
        HandoverKnowledgeDecision.model_validate(
            {
                "notice": _notice(),
                "disposition": "held",
                "reason": "source_unavailable",
                field: value,
            }
        )


@pytest.mark.parametrize(
    "change",
    [
        {"source": "unknown"},
        {"goal_revision": True},
        {"source_digest": "short"},
        {"goal_id": " "},
        {"check_epoch": -1},
        {"raw_text": "not permitted"},
    ],
)
def test_notice_rejects_ambiguous_identity_and_extra_content(change):
    with pytest.raises(ValueError):
        HandoverKnowledgeNotice.model_validate({**_notice().model_dump(), **change})


@pytest.mark.parametrize(
    "disposition,reason",
    [
        ("admitted", "source_unavailable"),
        ("held", "review_required"),
        ("withdrawn", "source_changed"),
        ("conflict", "check_expired"),
    ],
)
def test_disposition_cannot_misrepresent_the_reason(disposition, reason):
    with pytest.raises(ValueError):
        HandoverKnowledgeDecision(
            notice=_notice(),
            disposition=disposition,
            reason=reason,
            evidence_refs=("doc:example:v1",),
            evidence_digests=("b" * 64,),
        )


def test_source_window_is_fixed_and_exclusive_at_expiry():
    notice = _notice()
    start = datetime.fromtimestamp(30000, UTC)
    notice.require_current(start)
    notice.require_current(start + timedelta(seconds=299))
    for time in (start - timedelta(seconds=1), start + timedelta(minutes=5)):
        with pytest.raises(ValueError):
            notice.require_current(time)
