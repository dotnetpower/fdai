from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fdai_service_contracts.rule_activation_transport import RuleActivationRequestNotice


def test_notice_binds_proposal_identity_without_content() -> None:
    notice = RuleActivationRequestNotice(
        proposal_ref="operator-proposal:workflow:" + "b" * 64,
        proposal_id="operator-" + "a" * 32,
        request_id="operator-" + "a" * 32,
        proposal_digest="a" * 64,
        operation="rule.activation-request",
        accepted_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert notice.activation_authority is False
    assert "changes" not in notice.model_dump()
    assert "reason" not in notice.model_dump()


def test_notice_rejects_mismatched_proposal_identity() -> None:
    with pytest.raises(ValidationError, match="identity does not match"):
        RuleActivationRequestNotice(
            proposal_ref="operator-proposal:workflow:" + "b" * 64,
            proposal_id="operator-" + "c" * 32,
            request_id="operator-" + "c" * 32,
            proposal_digest="a" * 64,
            operation="rule.activation-request",
            accepted_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
