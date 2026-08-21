"""Shared semantic judgment boundary tests."""

from __future__ import annotations

from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentTier,
)

DIGEST = "sha256:" + ("a" * 64)


class _Model:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def judge(self, **kwargs: object) -> object:
        self.calls += 1
        assert kwargs["profile_id"] == "conversation.routing"
        return self.result


def _proposal(**overrides: object) -> dict[str, object]:
    return {
        "primary_intent": "cost_breakdown",
        "secondary_intents": [],
        "targets": [
            {
                "kind": "resource",
                "value": "api-example",
                "source_start": 5,
                "source_end": 16,
            }
        ],
        "requested_facets": ["budget_status"],
        "confidence": 0.91,
        "ambiguous": False,
        "alternatives": [],
        "unresolved_terms": [],
        "clarification": None,
        "discourse_mode": "direct",
        "action_posture": "advise_only",
        "authority": "candidate_only",
        "execution_authority": False,
        **overrides,
    }


def _binding(tier: SemanticJudgmentTier, model: _Model) -> SemanticJudgmentBinding:
    return SemanticJudgmentBinding(
        tier=tier,
        model=model,  # type: ignore[arg-type]
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )


def _boundary(
    primary: _Model | None,
    escalation: _Model | None = None,
) -> SemanticJudgmentBoundary:
    return SemanticJudgmentBoundary(
        profile_id="conversation.routing",
        profile_version="1.0.0",
        primary=_binding(SemanticJudgmentTier.T1, primary) if primary else None,
        escalation=_binding(SemanticJudgmentTier.T2, escalation) if escalation else None,
    )


def test_accepts_grounded_t1_proposal_with_content_free_receipt() -> None:
    utterance = "Show api-example budget status"
    model = _Model(_proposal())

    result = _boundary(model).judge(
        utterance=utterance,
        context=("prior summary",),
        capabilities=({"intent": "cost_breakdown"},),
    )

    assert result.accepted is True
    assert result.receipt.disposition is SemanticJudgmentDisposition.ACCEPTED
    assert result.receipt.tier is SemanticJudgmentTier.T1
    assert result.receipt.input_digest == content_digest({"utterance": utterance})
    assert utterance not in result.receipt.model_dump_json()
    assert result.receipt.execution_authority is False


def test_malformed_t1_escalates_once_to_valid_t2() -> None:
    t1 = _Model({"primary_intent": "broken"})
    t2 = _Model(_proposal())

    result = _boundary(t1, t2).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    assert result.accepted is True
    assert result.receipt.tier is SemanticJudgmentTier.T2
    assert (t1.calls, t2.calls) == (1, 1)


def test_ambiguous_final_proposal_returns_typed_clarification() -> None:
    model = _Model(
        _proposal(
            targets=[],
            confidence=0.82,
            ambiguous=True,
            alternatives=["resource_a", "resource_b"],
            unresolved_terms=["resource_identity"],
            clarification="Which resource should I inspect?",
        )
    )

    result = _boundary(model).judge(
        utterance="Show its budget status",
        context=(),
        capabilities=(),
    )

    assert result.accepted is False
    assert result.proposal is not None
    assert result.receipt.disposition is SemanticJudgmentDisposition.CLARIFICATION
    assert result.receipt.ambiguous is True


def test_unbound_or_forged_span_fails_closed() -> None:
    unavailable = _boundary(None).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )
    forged = _boundary(
        _Model(
            _proposal(
                targets=[
                    {
                        "kind": "resource",
                        "value": "other-value",
                        "source_start": 5,
                        "source_end": 16,
                    }
                ]
            )
        )
    ).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    assert unavailable.receipt.disposition is SemanticJudgmentDisposition.UNAVAILABLE
    assert unavailable.receipt.reason_code == "model_unbound"
    assert forged.receipt.disposition is SemanticJudgmentDisposition.MALFORMED
    assert forged.proposal is None


def test_bound_unavailable_models_are_distinct_from_unbound_composition() -> None:
    result = _boundary(_Model(None), _Model(None)).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    assert result.receipt.disposition is SemanticJudgmentDisposition.UNAVAILABLE
    assert result.receipt.reason_code == "model_attempts_unavailable"
