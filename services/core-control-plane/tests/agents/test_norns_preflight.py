"""Norns recurring deployment-preflight blocker learning."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fdai.agents import Norns, instantiate_pantheon


def _observe(norns: Norns, scope: str) -> None:
    norns.observe_preflight_manual_blocker(
        finding_id="quota-capacity:cores",
        category="quota_capacity",
        evidence_source="quota:cores@region",
        scope=scope,
    )


async def test_recurring_manual_blocker_proposes_one_inert_candidate() -> None:
    norns = Norns(preflight_blocker_threshold=3)
    _observe(norns, "scope:a")
    _observe(norns, "scope:a")
    _observe(norns, "scope:b")
    assert norns.pending_candidates == []

    _observe(norns, "scope:c")
    _observe(norns, "scope:d")

    assert len(norns.pending_candidates) == 1
    candidate = norns.pending_candidates[0]
    assert candidate["source_signal"] == "recurring_preflight_manual_blocker"
    assert candidate["proposal_kind"] == "new"
    assert candidate["candidate_type"] == "preflight-toggle-gap"
    evidence = cast(dict[str, object], candidate["evidence"])
    assert evidence["occurrence_count"] == 3
    assert len(cast(list[str], evidence["scope_digests"])) == 3
    assert "scope:a" not in str(candidate)

    mimir = cast(Any, instantiate_pantheon()["Mimir"])
    await mimir.on_typed_message(
        "object.rule-candidate",
        {
            "producer_principal": "Norns",
            "correlation_id": "norns:preflight-toggle-gap",
            "idempotency_key": "rule-candidate:preflight-toggle-gap",
            **candidate,
            "norns_consensus": {
                "decision": "propose",
                "unanimous": True,
                "perspective_count": 3,
            },
        },
    )
    assert len(mimir.pending_candidates()) == 1


@pytest.mark.parametrize("field", ("finding_id", "category", "evidence_source", "scope"))
def test_preflight_manual_blocker_rejects_invalid_fields(field: str) -> None:
    values = {
        "finding_id": "quota-capacity:cores",
        "category": "quota_capacity",
        "evidence_source": "quota:cores@region",
        "scope": "scope:a",
    }
    values[field] = ""
    norns = Norns()

    with pytest.raises(ValueError, match=field):
        norns.observe_preflight_manual_blocker(**values)


def test_preflight_blocker_threshold_requires_multiple_scopes() -> None:
    with pytest.raises(ValueError, match="preflight_blocker_threshold"):
        Norns(preflight_blocker_threshold=1)
