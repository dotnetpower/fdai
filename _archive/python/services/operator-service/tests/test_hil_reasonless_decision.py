"""An approval decision needs no written reason, and a long parked key never fails with HTTP 500."""

from __future__ import annotations

from typing import Any

import pytest
from fdai_operator_service.families.iam.contracts import MAX_HIL_IDEMPOTENCY_KEY_CHARS
from fdai_operator_service.families.iam.hil_callback_validation import _optional_text, _text
from fdai_operator_service.postgres_hil_decision import (
    _hil_decision_delivery_key,
    _operator_proposal_record,
)
from fdai_service_contracts import OperatorRole

from .test_operator_iam_family import (
    RecordingHilAudit,
    RecordingHilOutbox,
    RecordingHilRegistry,
    _client,
)


def _post(body: dict[str, Any], *, decision_key: str = "console-reasonless-1") -> Any:
    registry = RecordingHilRegistry()
    client = _client(
        hil_registry=registry,
        hil_outbox=RecordingHilOutbox(),
        hil_audit=RecordingHilAudit(),
        hil_context=registry,
    )
    response = client.post(
        "/hil/approval-1/operator-decision",
        headers={
            "x-test-role": OperatorRole.APPROVER.value,
            "x-test-oid": "approver-1",
            "Idempotency-Key": decision_key,
        },
        json=body,
    )
    return response, registry


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize(
    "body_extra",
    [{}, {"justification": ""}, {"justification": "   "}],
    ids=["omitted", "empty", "blank"],
)
def test_console_records_a_decision_without_a_reason(
    decision: str, body_extra: dict[str, str]
) -> None:
    response, registry = _post({"decision": decision, **body_extra})

    assert response.status_code == 200
    assert registry.command is not None
    assert registry.command.justification == ""


def test_console_keeps_a_provided_reason_trimmed_and_bounded() -> None:
    response, registry = _post({"decision": "reject", "justification": "  Not needed.  "})
    assert response.status_code == 200
    assert registry.command is not None
    assert registry.command.justification == "Not needed."

    too_long, unused = _post({"decision": "reject", "justification": "x" * 2001})
    assert too_long.status_code == 400
    assert unused.command is None


@pytest.mark.parametrize(
    "body",
    [{"justification": "no decision"}, {"decision": "approve", "extra": "field"}],
)
def test_console_still_refuses_unknown_or_missing_fields(body: dict[str, str]) -> None:
    response, registry = _post(body)

    assert response.status_code == 400
    assert registry.command is None


def test_optional_text_accepts_blank_but_text_does_not() -> None:
    assert _optional_text({"justification": "  "}, "justification", maximum=10) == ""
    with pytest.raises(Exception, match="bounded text"):
        _optional_text({"justification": 3}, "justification", maximum=10)
    with pytest.raises(Exception, match="non-empty"):
        _text({"justification": "  "}, "justification", maximum=10)


def test_a_parked_key_with_an_embedded_resource_id_is_recorded_not_a_server_error() -> None:
    key = "inventory-snapshot:" + "a" * 64 + ":/subscriptions/s/resourceGroups/rg/" + "p/" * 80
    assert 256 < len(key) <= MAX_HIL_IDEMPOTENCY_KEY_CHARS

    record_key, record = _operator_proposal_record(
        family="iam",
        operation="hil.decision.record",
        principal_id=None,
        idempotency_key=key,
        payload={"decision": "reject"},
    )

    assert record_key.startswith("operator-proposal:iam:")
    assert len(record_key) < 128
    assert record["idempotency_key"] == key
    assert _hil_decision_delivery_key(key).startswith("hil-decision:")

    with pytest.raises(ValueError, match="bounded"):
        _operator_proposal_record(
            family="iam",
            operation="hil.decision.record",
            principal_id=None,
            idempotency_key="k" * (MAX_HIL_IDEMPOTENCY_KEY_CHARS + 1),
            payload={},
        )
