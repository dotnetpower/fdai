"""Service-contract tests for verified answer claim propositions."""

from __future__ import annotations

import pytest
from fdai_service_contracts.answer_claims import (
    AnswerClaim,
    AnswerClaimProposition,
    ClaimCausalClass,
    ClaimModality,
    ComposedAnswer,
)
from pydantic import ValidationError


def test_proposition_carries_owner_design_fields() -> None:
    proposition = AnswerClaimProposition(
        subject="resource:aks-1",
        predicate="cost",
        object="monthly-spend",
        value=12.5,
        polarity="affirm",
        quantifier="exact",
        unit="currency",
        currency="USD",
        temporal_basis="window",
        time_zone="UTC",
        modality="hypothesis",
        causal_class="causal_hypothesis",
    )

    assert proposition.currency == "USD"
    assert proposition.temporal_basis == "window"
    assert proposition.causal_class is ClaimCausalClass.CAUSAL_HYPOTHESIS


def test_causal_class_requires_hypothesis_modality() -> None:
    with pytest.raises(ValidationError, match="causal"):
        AnswerClaimProposition(
            modality=ClaimModality.OBSERVED,
            causal_class=ClaimCausalClass.CAUSAL_HYPOTHESIS,
        )


def test_composed_answer_round_trips_and_rejects_bad_spans() -> None:
    answer = ComposedAnswer(
        text="It is running.",
        claims=(
            AnswerClaim(
                id="c1",
                kind="state",
                span={"start": 0, "end": 14},
                refs=({"goal": "g1", "node": "state"},),
                proposition={"subject": "resource:aks-1", "predicate": "state"},
            ),
        ),
    )

    assert ComposedAnswer.model_validate_json(answer.model_dump_json()) == answer
    with pytest.raises(ValidationError, match="span"):
        ComposedAnswer.model_validate(
            {
                **answer.model_dump(mode="json"),
                "claims": [
                    {
                        **answer.claims[0].model_dump(mode="json"),
                        "span": {"start": 0, "end": 99},
                    }
                ],
            }
        )
