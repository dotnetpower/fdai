from datetime import UTC, datetime

import pytest
from fdai_operator_service.browser_evidence_filters import (
    parse_browser_evidence_workspace_query,
)


def test_workspace_query_parser_normalizes_aware_times() -> None:
    query = parse_browser_evidence_workspace_query(
        [
            ("limit", "25"),
            ("host", "dashboard.example"),
            ("host_scope", "requested"),
            ("policy", "dashboard"),
            ("policy_version", "4"),
            ("from", "2026-09-01T09:00:00+09:00"),
            ("before", "2026-09-15T00:00:00Z"),
            ("retention", "expiring"),
            ("finding", "present"),
            ("sort", "newest"),
        ]
    )

    assert query.captured_from == datetime(2026, 9, 1, tzinfo=UTC)
    assert query.captured_before == datetime(2026, 9, 15, tzinfo=UTC)
    assert query.policy_version == 4


@pytest.mark.parametrize(
    ("items", "message"),
    (
        ([("unknown", "one")], "unknown"),
        ([("host", "one"), ("host", "two")], "duplicate"),
        ([("host", "")], "non-empty"),
        ([("limit", "0")], "positive integer"),
        ([("policy", "dashboard"), ("policy_version", "2147483648")], "policy version"),
        ([("from", "2026-09-01")], "RFC 3339"),
        ([("before", "2026-13-01T00:00:00Z")], "RFC 3339"),
    ),
)
def test_workspace_query_parser_rejects_ambiguous_input(
    items: list[tuple[str, str]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_browser_evidence_workspace_query(items)
