from __future__ import annotations

from typing import Any, cast

from fdai.agents import Norns, instantiate_pantheon
from fdai.core.operational_learning import InvestigationStrategyComparisonEvidence
from fdai.core.rca.discrimination_shadow import (
    ChallengerComparisonOutcome,
)
from fdai_service_contracts.ontology_query import content_digest

from tests.core.operational_learning.test_investigation_strategy import _comparison


def _evidence(
    character: str,
    outcome: ChallengerComparisonOutcome,
) -> InvestigationStrategyComparisonEvidence:
    del character
    return InvestigationStrategyComparisonEvidence.from_shadow(
        _comparison(improvement=outcome is ChallengerComparisonOutcome.IMPROVEMENT)
    )


def _payload(
    comparisons: tuple[InvestigationStrategyComparisonEvidence, ...],
) -> dict[str, object]:
    active = comparisons[0].active_strategy_digest
    challenger = comparisons[0].challenger_strategy_digest
    pair_digest = content_digest(
        {
            "active_strategy_digest": active,
            "challenger_strategy_digest": challenger,
        }
    )
    cohort_digest = content_digest(
        {
            "pair_digest": pair_digest,
            "comparison_digests": sorted(item.comparison_digest for item in comparisons),
        }
    )
    return {
        "kind": "investigation_strategy_comparison_cohort",
        "producer_principal": "Muninn",
        "correlation_id": pair_digest,
        "idempotency_key": f"investigation-strategy:{cohort_digest}",
        "cohort_digest": cohort_digest,
        "comparisons": [item.to_mapping() for item in comparisons],
    }


async def test_norns_compiles_muninn_strategy_cohort_into_inert_candidate() -> None:
    norns = Norns()
    comparisons = (
        _evidence("c", ChallengerComparisonOutcome.IMPROVEMENT),
        _evidence("d", ChallengerComparisonOutcome.NON_IMPROVEMENT),
    )

    await norns.on_typed_message(
        "object.context-index",
        _payload(comparisons),
    )

    assert len(norns.pending_candidates) == 1
    candidate = norns.pending_candidates[0]
    assert candidate["proposed_by"] == "Norns"
    assert candidate["source_signal"] == "investigation_strategy_comparison_cohort"
    assert candidate["suggested_change"] == "review_investigation_strategy"
    assert candidate["enforcement_mode"] == "shadow"
    assert candidate["auto_promote"] is False


async def test_inert_strategy_candidate_reaches_existing_mimir_review_queue() -> None:
    norns = Norns()
    mimir = cast(Any, instantiate_pantheon()["Mimir"])
    comparisons = (
        _evidence("c", ChallengerComparisonOutcome.IMPROVEMENT),
        _evidence("d", ChallengerComparisonOutcome.CONTROL),
    )
    await norns.on_typed_message(
        "object.context-index",
        _payload(comparisons),
    )
    candidate = norns.pending_candidates[0]

    published = {
        "producer_principal": "Norns",
        "correlation_id": "norns:investigation-strategy",
        "idempotency_key": "rule-candidate:investigation-strategy",
        **candidate,
        "norns_consensus": {
            "decision": "propose",
            "unanimous": True,
            "perspective_count": 3,
        },
    }
    await mimir.on_typed_message(
        "object.rule-candidate",
        published,
    )
    await mimir.on_typed_message("object.rule-candidate", published)

    assert len(mimir.pending_candidates()) == 1
    assert (
        mimir.pending_candidates()[0]["source_signal"] == "investigation_strategy_comparison_cohort"
    )


async def test_norns_rejects_non_muninn_strategy_cohort() -> None:
    norns = Norns()

    await norns.on_typed_message(
        "object.context-index",
        {
            "kind": "investigation_strategy_comparison_cohort",
            "producer_principal": "Other",
            "comparisons": [],
        },
    )

    assert norns.pending_candidates == []
    assert "investigation_strategy_cohort_invalid_producer" in norns.behavior_snapshot()


async def test_norns_holds_unbalanced_strategy_cohort() -> None:
    norns = Norns()
    comparison = _evidence("c", ChallengerComparisonOutcome.IMPROVEMENT)

    await norns.on_typed_message(
        "object.context-index",
        _payload((comparison,)),
    )

    assert norns.pending_candidates == []
    assert "investigation_strategy_cohort_held" in norns.behavior_snapshot()
