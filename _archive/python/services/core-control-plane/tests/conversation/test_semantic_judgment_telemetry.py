"""Content-free semantic judgment telemetry tests."""

from __future__ import annotations

import pytest
from fdai.core.conversation.semantic_judgment_telemetry import (
    summarize_semantic_judgments,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentReceipt,
)

_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64
_DIGEST_D = "sha256:" + "d" * 64
_DIGEST_E = "sha256:" + "e" * 64


def _receipt(
    *,
    disposition: SemanticJudgmentDisposition,
    tier: str | None,
    suffix: str,
    profile_version: str = "1.0.0",
) -> SemanticJudgmentReceipt:
    accepted = disposition is SemanticJudgmentDisposition.ACCEPTED
    body = {
        "schema_version": "1.0.0",
        "input_digest": _DIGEST_A,
        "context_digest": _DIGEST_B,
        "capability_digest": _DIGEST_C,
        "proposal_digest": _DIGEST_D if accepted else None,
        "profile_id": "semantic-judgment",
        "profile_version": profile_version,
        "tier": tier,
        "model_config_digest": _DIGEST_E if accepted else None,
        "prompt_digest": _DIGEST_D if accepted else None,
        "disposition": disposition.value,
        "confidence": 0.91 if accepted else None,
        "ambiguous": disposition is SemanticJudgmentDisposition.AMBIGUOUS,
        "latency_ms": 25 if accepted else 5,
        "reason_code": f"outcome.{suffix}",
        "execution_authority": False,
    }
    return SemanticJudgmentReceipt.model_validate({**body, "receipt_digest": content_digest(body)})


def test_summary_exposes_content_free_semantic_metrics() -> None:
    accepted = _receipt(
        disposition=SemanticJudgmentDisposition.ACCEPTED,
        tier="t1",
        suffix="accepted",
    )
    unavailable = _receipt(
        disposition=SemanticJudgmentDisposition.UNAVAILABLE,
        tier=None,
        suffix="unavailable",
    )

    summary = summarize_semantic_judgments((unavailable, accepted))

    assert summary.profile_id == "semantic-judgment"
    assert summary.profile_version == "1.0.0"
    assert summary.total_count == 2
    assert summary.abstention_count == 1
    assert summary.abstention_rate == 0.5
    assert summary.outcome_counts == (("accepted", 1), ("unavailable", 1))
    assert summary.tier_counts == (("none", 1), ("t1", 1))
    assert tuple(sample.receipt_digest for sample in summary.samples) == tuple(
        sorted((accepted.receipt_digest, unavailable.receipt_digest))
    )
    accepted_sample = next(sample for sample in summary.samples if not sample.abstained)
    assert accepted_sample.model_config_digest == _DIGEST_E
    assert accepted_sample.confidence == 0.91
    assert accepted_sample.latency_ms == 25
    assert accepted_sample.execution_authority is summary.execution_authority is False
    assert not hasattr(accepted_sample, "input_digest")
    assert not hasattr(accepted_sample, "context_digest")
    assert not hasattr(accepted_sample, "proposal_digest")


def test_summary_rejects_mixed_profile_revisions_and_duplicate_receipts() -> None:
    first = _receipt(
        disposition=SemanticJudgmentDisposition.ACCEPTED,
        tier="t1",
        suffix="accepted",
    )
    other_revision = _receipt(
        disposition=SemanticJudgmentDisposition.ACCEPTED,
        tier="t1",
        suffix="other",
        profile_version="2.0.0",
    )

    with pytest.raises(ValueError, match="one profile revision"):
        summarize_semantic_judgments((first, other_revision))
    with pytest.raises(ValueError, match="MUST be unique"):
        summarize_semantic_judgments((first, first))


def test_summary_requires_bounded_non_empty_input() -> None:
    with pytest.raises(ValueError, match="at least one receipt"):
        summarize_semantic_judgments(())
