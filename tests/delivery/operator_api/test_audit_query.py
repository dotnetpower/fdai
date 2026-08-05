from __future__ import annotations

from fdai.delivery.operator_api.projections.audit import parse_audit_filters


def test_parses_exact_action_and_idempotency_filters() -> None:
    filters = parse_audit_filters(
        {
            "action_id": "action-1",
            "idempotency_key": "operator::action-1",
        }
    )

    assert filters.action_id == "action-1"
    assert filters.idempotency_key == "operator::action-1"
