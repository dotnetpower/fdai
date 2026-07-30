from __future__ import annotations

from typing import Any, cast

from fdai.agents import Norns, instantiate_pantheon


def _case(identifier: str, *, reusable: bool) -> dict[str, object]:
    return {
        "case_id": f"case-{identifier}",
        "action_type": "ops.scale-out",
        "outcome_id": f"outcome-{identifier}",
        "reusable": reusable,
        "evidence_refs": [f"case-history:{identifier}"],
    }


async def test_success_only_operating_cohort_is_held() -> None:
    norns = Norns()

    await norns.on_typed_message(
        "object.context-index",
        {
            "producer_principal": "Muninn",
            "kind": "operating_pattern_cohort",
            "cases": [_case("one", reusable=True), _case("two", reusable=True)],
        },
    )

    assert norns.pending_candidates == []


async def test_balanced_operating_cohort_reaches_mimir_guard() -> None:
    norns = Norns()
    mimir = cast(Any, instantiate_pantheon()["Mimir"])

    await norns.on_typed_message(
        "object.context-index",
        {
            "producer_principal": "Muninn",
            "kind": "operating_pattern_cohort",
            "cases": [_case("success", reusable=True), _case("control", reusable=False)],
        },
    )

    assert len(norns.pending_candidates) == 1
    candidate = norns.pending_candidates[0]
    await mimir.on_typed_message(
        "object.rule-candidate",
        {
            "producer_principal": "Norns",
            **candidate,
            "norns_consensus": {
                "decision": "propose",
                "unanimous": True,
                "perspective_count": 3,
            },
        },
    )

    assert len(mimir.pending_candidates()) == 1
    assert mimir.pending_candidates()[0]["source_signal"] == "operating_pattern_cohort"
