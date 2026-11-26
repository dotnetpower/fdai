from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.direction_shadow import (
    DirectionGraphGeneration,
    DirectionPromotionDecision,
    RebuildPointer,
    assess_direction_mapping_promotion,
    compare_exact_release_graph_generations,
)
from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.delivery.provider_schema_relationship_ledger import (
    ProviderSchemaRelationshipLedger,
)

_ONTOLOGY = "sha256:" + "a" * 64
_PROVIDER_SCHEMA = "sha256:" + "b" * 64
_REGRESSION = "sha256:" + "c" * 64
_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _generations() -> tuple[DirectionGraphGeneration, DirectionGraphGeneration]:
    common = {
        "ontology_release_digest": _ONTOLOGY,
        "object_ids": ("group", "resource"),
        "complete": True,
        "provider_schema_digest": _PROVIDER_SCHEMA,
        "mapping_revision": "mapping-v1",
    }
    prior = DirectionGraphGeneration.create(
        generation_ref="prior",
        links=(),
        **common,
    )
    aligned = DirectionGraphGeneration.create(
        generation_ref="aligned",
        links=(),
        **common,
    )
    return prior, aligned


def _review(
    *,
    reviewed_at: datetime = _NOW,
    decision: DirectionPromotionDecision = DirectionPromotionDecision.APPROVE_PROPOSAL,
):
    prior, aligned = _generations()
    receipt = compare_exact_release_graph_generations(
        prior,
        aligned,
        migration_revision="mapping-direction-v1",
        rebuild_pointer=RebuildPointer(
            authoritative_generation_ref="inventory-generation:prior",
            rebuild_procedure_ref="runbook:ontology-current-state-rebuild:v1",
        ),
    )
    assessment = assess_direction_mapping_promotion(
        receipt,
        regression_receipt_digests=(_REGRESSION,),
        requested_by="requester",
        reviewed_by="reviewer",
        reviewed_at=reviewed_at,
        decision=decision,
    )
    return prior, aligned, receipt, assessment


def test_review_ledger_preserves_comparison_and_both_historical_contexts(
    tmp_path,
) -> None:
    prior, aligned, receipt, assessment = _review()
    ledger = ProviderSchemaRelationshipLedger(tmp_path)

    digest = ledger.record_promotion_review(
        assessment=assessment,
        receipt=receipt,
        prior=prior,
        aligned=aligned,
    )

    assert digest == assessment.assessment_digest
    assert (tmp_path / "direction-contexts" / f"{prior.generation_digest[7:]}.json").is_file()
    assert (tmp_path / "direction-contexts" / f"{aligned.generation_digest[7:]}.json").is_file()
    history = ledger.read_promotion_history()
    assert len(history) == 1
    assert history[0]["proposal_ready"] is True
    assert history[0]["graph_mutation_authority"] is False
    assert history[0]["reviewed_by"] == "reviewer"
    assert history[0]["regression_receipt_digests"] == [_REGRESSION]
    assert history[0]["rebuild_pointer"]["authoritative_generation_ref"] == (
        "inventory-generation:prior"
    )


def test_review_history_is_append_only_and_duplicate_safe(tmp_path) -> None:
    prior, aligned, receipt, approved = _review()
    _, _, _, rejected = _review(
        reviewed_at=_NOW + timedelta(minutes=1),
        decision=DirectionPromotionDecision.REJECT,
    )
    ledger = ProviderSchemaRelationshipLedger(tmp_path)

    ledger.record_promotion_review(
        assessment=approved,
        receipt=receipt,
        prior=prior,
        aligned=aligned,
    )
    ledger.record_promotion_review(
        assessment=approved,
        receipt=receipt,
        prior=prior,
        aligned=aligned,
    )
    ledger.record_promotion_review(
        assessment=rejected,
        receipt=receipt,
        prior=prior,
        aligned=aligned,
    )

    history = ledger.read_promotion_history()
    assert [item["decision"] for item in history] == [
        "approve_proposal",
        "reject",
    ]
    assert all(item["migration_execution_authority"] is False for item in history)
    assert (
        len(
            (tmp_path / "direction-promotion-history.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        == 2
    )


def test_review_ledger_rejects_generation_substitution(tmp_path) -> None:
    prior, aligned, receipt, assessment = _review()
    substituted = DirectionGraphGeneration.create(
        generation_ref="substituted",
        ontology_release_digest=_ONTOLOGY,
        object_ids=("other",),
        links=(),
        complete=True,
        provider_schema_digest=_PROVIDER_SCHEMA,
        mapping_revision="mapping-v1",
    )

    with pytest.raises(ProviderSchemaError, match="generation identity mismatch"):
        ProviderSchemaRelationshipLedger(tmp_path).record_promotion_review(
            assessment=assessment,
            receipt=receipt,
            prior=substituted,
            aligned=aligned,
        )


def test_review_history_with_mutation_authority_fails_closed(tmp_path) -> None:
    path = tmp_path / "direction-promotion-history.jsonl"
    path.write_text(
        json.dumps(
            {
                "assessment_digest": "sha256:" + "a" * 64,
                "graph_mutation_authority": True,
                "migration_execution_authority": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ProviderSchemaError, match="mutation authority"):
        ProviderSchemaRelationshipLedger(tmp_path).read_promotion_history()
