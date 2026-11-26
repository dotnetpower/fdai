from __future__ import annotations

import pytest
from fdai.delivery.incident_evidence_query_cli import (
    query_incident_evidence,
    summarize_incident_evidence,
)


class _Reader:
    def __init__(self, entries: tuple[dict[str, object], ...]) -> None:
        self._entries = entries

    async def read_incident_transitions(self) -> tuple[dict[str, object], ...]:
        return self._entries


def test_summary_reports_counts_without_identifiers() -> None:
    prefix = "fdai-incident-live-20260910091804"
    result = summarize_incident_evidence(
        (
            {
                "kind": "incident.open",
                "incident_id": "secret-incident-id",
                "correlation_keys": [f"trace:{prefix}-shared"],
                "member_event_ids": ["event-1", "event-2"],
            },
            {
                "kind": "incident.transition",
                "incident_id": "secret-incident-id",
                "reason": prefix,
            },
            {"kind": "incident.open", "incident_id": "unrelated"},
        ),
        correlation_prefix=prefix,
    )

    assert result == {
        "incidents": 1,
        "kinds": ["incident.open", "incident.transition"],
        "max_members": 2,
        "transitions": 2,
    }
    assert "secret" not in str(result)


@pytest.mark.asyncio
async def test_query_uses_the_read_only_transition_surface() -> None:
    result = await query_incident_evidence(
        correlation_prefix="fdai-live-1",
        reader=_Reader(({"kind": "incident.open", "reason": "fdai-live-1"},)),
    )

    assert result["transitions"] == 1


@pytest.mark.parametrize(
    "prefix",
    ("", "incident-live", "fdai-UPPER", "fdai-has spaces", "fdai-" + "a" * 121),
)
def test_invalid_prefixes_fail_before_querying_entries(prefix: str) -> None:
    with pytest.raises(ValueError, match="prefix is invalid"):
        summarize_incident_evidence((), correlation_prefix=prefix)
