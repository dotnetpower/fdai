"""Shared semantic judgment boundary tests."""

from __future__ import annotations

import json

import pytest
from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
    SemanticJudgmentModelResponse,
    SemanticJudgmentObservation,
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
        self.schema_repairs: list[object] = []

    def judge(self, **kwargs: object) -> object:
        self.calls += 1
        assert kwargs["profile_id"] == "conversation.routing"
        self.schema_repairs.append(kwargs["schema_repair"])
        return self.result


class _SequenceModel(_Model):
    def __init__(self, results: list[object]) -> None:
        super().__init__(None)
        self.results = results

    def judge(self, **kwargs: object) -> object:
        self.calls += 1
        assert kwargs["profile_id"] == "conversation.routing"
        self.schema_repairs.append(kwargs["schema_repair"])
        return self.results.pop(0)


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
        "action_subject": "none",
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


def test_preserves_measured_provider_observation_without_changing_proposal_validation() -> None:
    observation = SemanticJudgmentObservation(
        model="semantic-test",
        usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        trace_call={"call_id": "semantic-judgment-1", "redacted": True},
    )
    model = _Model(
        SemanticJudgmentModelResponse(
            proposal=_proposal(),
            observation=observation,
        )
    )

    result = _boundary(model).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=({"intent": "cost_breakdown"},),
    )

    assert result.accepted is True
    assert result.observations == (observation,)


@pytest.mark.parametrize(
    ("utterance", "source_value", "action_posture", "action_subject"),
    [
        (
            "Draft a review-only incident mitigation proposal.",
            "Draft",
            "draft_only",
            "Incident",
        ),
        (
            "검토 전용 장애 완화 제안을 작성해 주세요.",
            "작성",
            "draft_only",
            "Incident",
        ),
        (
            "Show the review-only incident mitigation proposal.",
            "mitigation proposal",
            "advise_only",
            "none",
        ),
        (
            "검토 전용 장애 완화 제안을 보여 주세요.",
            "완화 제안",
            "advise_only",
            "none",
        ),
    ],
    ids=("draft-en", "draft-ko", "read-en", "read-ko"),
)
def test_bilingual_action_posture_receipts_are_typed_and_authority_free(
    utterance: str,
    source_value: str,
    action_posture: str,
    action_subject: str,
) -> None:
    source_start = utterance.index(source_value)
    result = _boundary(
        _Model(
            _proposal(
                primary_intent=(
                    "action_request" if action_posture == "draft_only" else "incident_evidence"
                ),
                targets=[
                    {
                        "kind": "request_concept",
                        "value": source_value,
                        "source_start": source_start,
                        "source_end": source_start + len(source_value),
                    }
                ],
                action_posture=action_posture,
                action_subject=action_subject,
            )
        )
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=({"kind": "object_type", "name": "Incident"},),
        allow_escalation=False,
        bound_subject_types=("Incident",),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.action_posture == action_posture
    assert result.proposal.action_subject == action_subject
    assert result.proposal.execution_authority is False
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
    assert (t1.calls, t2.calls) == (3, 1)


def test_validation_rejection_logs_only_bounded_schema_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _boundary(_Model({"primary_intent": "broken"})).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    record = next(
        item for item in caplog.records if item.message == "semantic_judgment_proposal_rejected"
    )
    validation_reason = json.loads(record.__dict__["validation_reason"])
    assert validation_reason
    assert all(set(error) <= {"location", "type", "reason"} for error in validation_reason)


def test_validation_rejection_logs_allowlisted_fixed_contract_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _boundary(_Model(_proposal(action_posture="draft_only", action_subject="none"))).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    record = next(
        item for item in caplog.records if item.message == "semantic_judgment_proposal_rejected"
    )
    validation_reason = json.loads(record.__dict__["validation_reason"])
    assert validation_reason == [
        {
            "location": "",
            "reason": "semantic judgment action subject MUST match draft posture",
            "type": "value_error",
        }
    ]


def test_advise_only_clears_redundant_action_subject() -> None:
    result = _boundary(
        _Model(_proposal(action_posture="advise_only", action_subject="Incident"))
    ).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.action_posture == "advise_only"
    assert result.proposal.action_subject == "none"


def test_malformed_t1_retries_same_binding_before_escalation() -> None:
    t1 = _SequenceModel(
        [{"primary_intent": "broken"}, {"primary_intent": "still-broken"}, _proposal()]
    )
    t2 = _Model(_proposal())

    result = _boundary(t1, t2).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    assert result.accepted is True
    assert result.receipt.tier is SemanticJudgmentTier.T1
    assert (t1.calls, t2.calls) == (3, 0)
    assert t1.schema_repairs[0] == ()
    assert t1.schema_repairs[1]
    assert t1.schema_repairs[2]


def test_same_binding_retry_accumulates_distinct_schema_repairs() -> None:
    t1 = _SequenceModel(
        [
            _proposal(action_posture="draft_only", action_subject="none"),
            _proposal(
                targets=[
                    {
                        "kind": "resource",
                        "value": "missing-target",
                        "source_start": 0,
                        "source_end": 14,
                    }
                ]
            ),
            _proposal(),
        ]
    )

    result = _boundary(t1).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.targets
    assert t1.calls == 3
    assert t1.schema_repairs[1] == (
        {
            "location": "",
            "type": "value_error",
            "reason": "semantic judgment action subject MUST match draft posture",
        },
    )
    assert t1.schema_repairs[2] == (
        *t1.schema_repairs[1],
        {
            "location": "",
            "type": "value_error",
            "reason": "semantic target source span does not match the utterance",
        },
    )


def test_ungrounded_optional_target_is_removed_before_proposal_validation() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.incident_evidence",
                requested_facets=["compare", "recurrence_supported"],
                targets=[
                    {
                        "kind": "object_type",
                        "value": "invented incident target",
                        "canonical_value": "Incident",
                        "source_start": 0,
                        "source_end": 7,
                    }
                ],
            )
        )
    ).judge(
        utterance="Compare retained incident evidence for recurrence.",
        context=(),
        capabilities=({"kind": "object_type", "name": "Incident"},),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.incident_evidence"
    assert result.proposal.requested_facets == ("compare", "recurrence_supported")
    assert result.proposal.targets == ()
    assert result.receipt.execution_authority is False


def test_bound_subject_recovers_targetless_typed_proposal() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.incident_evidence",
                requested_facets=["compare", "recurrence_supported"],
                targets=[
                    {
                        "kind": "object_type",
                        "value": "retained incident evidence",
                        "canonical_value": "not a canonical identity",
                        "source_start": 0,
                        "source_end": 7,
                    }
                ],
            )
        )
    ).judge(
        utterance="Compare retained incident evidence for recurrence.",
        context=(),
        capabilities=({"kind": "object_type", "name": "Incident"},),
        allow_escalation=False,
        bound_subject_types=("Incident",),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.requested_facets == ("compare", "recurrence_supported")
    assert result.proposal.targets == ()


def test_bound_subject_recovery_cannot_promote_malformed_draft() -> None:
    model = _Model(
        _proposal(
            primary_intent="action_request",
            action_posture="draft_only",
            action_subject="Incident",
            targets=[
                {
                    "kind": "object_type",
                    "value": "missing incident",
                    "canonical_value": "not a canonical identity",
                    "source_start": 0,
                    "source_end": 7,
                }
            ],
        )
    )

    result = _boundary(model).judge(
        utterance="Draft an incident mitigation proposal.",
        context=(),
        capabilities=({"kind": "object_type", "name": "Incident"},),
        allow_escalation=False,
        bound_subject_types=("Incident",),
    )

    assert result.accepted is False
    assert result.proposal is None
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED
    assert result.receipt.execution_authority is False
    assert model.calls == 3
    assert result.receipt.execution_authority is False


def test_unbound_subject_does_not_recover_invalid_target() -> None:
    result = _boundary(
        _Model(
            _proposal(
                targets=[
                    {
                        "kind": "object_type",
                        "value": "retained incident evidence",
                        "canonical_value": "not a canonical identity",
                        "source_start": 0,
                        "source_end": 7,
                    }
                ],
            )
        )
    ).judge(
        utterance="Compare retained incident evidence for recurrence.",
        context=(),
        capabilities=({"kind": "object_type", "name": "Incident"},),
        allow_escalation=False,
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


def test_bare_manifest_link_intent_is_namespaced_without_retry() -> None:
    t1 = _Model(_proposal(primary_intent="diagnostic_finding_derived_from"))

    result = _boundary(t1).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=({"kind": "link_type", "name": "diagnostic_finding_derived_from"},),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.diagnostic_finding_derived_from"
    assert t1.calls == 1


def test_non_capability_primary_intent_remains_valid() -> None:
    result = _boundary(_Model(_proposal(primary_intent="cost_breakdown"))).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=({"kind": "link_type", "name": "diagnostic_finding_derived_from"},),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "cost_breakdown"


def test_low_confidence_retains_schema_valid_candidate_without_accepting_it() -> None:
    result = _boundary(_Model(_proposal(confidence=0.5))).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
        allow_escalation=False,
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.LOW_CONFIDENCE
    assert result.proposal is not None
    assert result.proposal.confidence == 0.5
    assert result.receipt.proposal_digest == result.proposal.proposal_digest
    assert result.receipt.execution_authority is False


def test_human_readable_machine_tokens_are_canonicalized_before_validation() -> None:
    model = _Model(
        _proposal(
            primary_intent="Query Incident Evidence",
            requested_facets=["Retained Evidence", "Determine Recurrence?"],
            targets=[],
        )
    )

    result = _boundary(model).judge(
        utterance="Compare the retained incident evidence.",
        context=(),
        capabilities=(),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query_incident_evidence"
    assert result.proposal.requested_facets == (
        "retained_evidence",
        "determine_recurrence",
    )


def test_machine_token_canonicalization_collision_still_fails_closed() -> None:
    model = _Model(
        _proposal(
            requested_facets=["retained evidence", "retained_evidence"],
            targets=[],
        )
    )

    result = _boundary(model).judge(
        utterance="Compare the retained incident evidence.",
        context=(),
        capabilities=(),
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


def test_redundant_ambiguity_flag_is_derived_from_typed_meaning() -> None:
    model = _Model(
        _proposal(
            targets=[],
            ambiguous=False,
            alternatives=["incident_a", "incident_b"],
            unresolved_terms=["incident_identity"],
            clarification="Which incident should I inspect?",
        )
    )

    result = _boundary(model).judge(
        utterance="Inspect the incident.",
        context=(),
        capabilities=(),
    )

    assert result.receipt.disposition is SemanticJudgmentDisposition.CLARIFICATION
    assert result.proposal is not None
    assert result.proposal.ambiguous is True


def test_ambiguity_repair_does_not_invent_required_clarification() -> None:
    model = _Model(
        _proposal(
            targets=[],
            ambiguous=False,
            unresolved_terms=["incident_identity"],
            clarification=None,
        )
    )

    result = _boundary(model).judge(
        utterance="Inspect the incident.",
        context=(),
        capabilities=(),
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


@pytest.mark.parametrize(
    ("trace_facet", "posture_facet"),
    [("explore", "controlled"), ("relationships", "scope"), ("trace", "governed")],
)
def test_complete_ontology_trace_missing_clarification_recovers_to_safe_hold(
    trace_facet: str,
    posture_facet: str,
) -> None:
    model = _Model(
        _proposal(
            primary_intent="query.ontology_relationships",
            targets=[],
            requested_facets=[
                "resource_type",
                "signal_type",
                "action_type",
                trace_facet,
                posture_facet,
            ],
            ambiguous=True,
            alternatives=["current_finding"],
            unresolved_terms=["current_finding_state"],
            clarification=None,
        )
    )

    result = _boundary(model).judge(
        utterance="Trace the governed ontology declarations.",
        context=(),
        capabilities=(),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.action_posture == "advise_only"
    assert result.proposal.execution_authority is False
    assert result.receipt.reason_code == "accepted_safe_trace_hold"


def test_t1_only_judgment_does_not_invoke_escalation_binding() -> None:
    t1 = _Model({"primary_intent": "broken"})
    t2 = _Model(_proposal())

    result = _boundary(t1, t2).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
        allow_escalation=False,
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED
    assert (t1.calls, t2.calls) == (3, 0)


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


def test_unique_exact_target_value_repairs_incorrect_source_span() -> None:
    result = _boundary(
        _Model(
            _proposal(
                targets=[
                    {
                        "kind": "resource",
                        "value": "api-example",
                        "source_start": 0,
                        "source_end": 11,
                    }
                ]
            )
        )
    ).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.targets[0].source_start == 5
    assert result.proposal.targets[0].source_end == 16


def test_supplied_canonical_target_does_not_relabel_localized_source_value() -> None:
    utterance = "비즈니스 서비스 비용 목표를 보여줘"
    source_value = "비즈니스 서비스"
    source_start = utterance.index(source_value)
    result = _boundary(
        _Model(
            _proposal(
                targets=[
                    {
                        "kind": "object_type",
                        "value": "BusinessService",
                        "canonical_value": "BusinessService",
                        "source_start": source_start,
                        "source_end": source_start + len(source_value),
                    }
                ]
            )
        )
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=({"kind": "object_type", "name": "BusinessService"},),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.targets == ()


def test_unbound_canonical_target_cannot_repair_localized_source_value() -> None:
    utterance = "비즈니스 서비스 비용 목표를 보여줘"
    source_value = "비즈니스 서비스"
    source_start = utterance.index(source_value)
    result = _boundary(
        _Model(
            _proposal(
                targets=[
                    {
                        "kind": "object_type",
                        "value": "BusinessService",
                        "canonical_value": "BusinessService",
                        "source_start": source_start,
                        "source_end": source_start + len(source_value),
                    }
                ]
            )
        )
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=(),
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


def test_bound_unavailable_models_are_distinct_from_unbound_composition() -> None:
    result = _boundary(_Model(None), _Model(None)).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    assert result.receipt.disposition is SemanticJudgmentDisposition.UNAVAILABLE
    assert result.receipt.reason_code == "model_attempts_unavailable"
