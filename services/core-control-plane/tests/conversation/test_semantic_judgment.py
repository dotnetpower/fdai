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
    SemanticDocumentEvidenceMode,
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
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


class _DirectResponseModel(_Model):
    def __init__(
        self,
        *,
        answer: str,
        locale: str | None = None,
        digest: str | None = None,
    ) -> None:
        super().__init__(None)
        self.answer = answer
        self.locale = locale
        self.digest = digest

    def judge(self, **kwargs: object) -> object:
        self.calls += 1
        self.schema_repairs.append(kwargs["schema_repair"])
        return _proposal(
            primary_intent="greeting",
            targets=[],
            requested_facets=[],
            direct_response={
                "locale": self.locale or kwargs["locale"],
                "answer": self.answer,
                "profile_digest": self.digest or kwargs["direct_response_profile_digest"],
                "execution_authority": False,
            },
        )


def _proposal(**overrides: object) -> dict[str, object]:
    proposal = {
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
    if "forbidden_actions" in overrides and "schema_version" not in overrides:
        proposal["schema_version"] = "1.1.0"
    return proposal


@pytest.mark.parametrize("kind", ("object", "interface", "link", "action", "function"))
def test_complete_manifest_list_skips_schema_repair(kind: str) -> None:
    primary = _Model(
        _proposal(
            primary_intent="query.manifest",
            targets=[],
            requested_facets=[f"{kind}_types", "readable"],
        )
    )
    repair = _Model(None)

    result = _boundary(primary, schema_repair=repair, strict_intent_grounding=True).judge(
        utterance="List the readable declaration kinds.",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.manifest"},),
        allow_escalation=False,
    )

    assert result.accepted
    assert primary.calls == 1
    assert repair.calls == 0
    assert result.proposal is not None
    assert result.proposal.requested_facets == (f"{kind}_types", "readable")


@pytest.mark.parametrize(
    "facets",
    (
        ("object_types",),
        ("object_types", "readable", "count"),
        ("object_types", "readable", "historical"),
        ("object_types", "readable", "properties"),
        ("object_types", "link_types", "readable"),
    ),
)
def test_incomplete_or_composite_manifest_lists_still_require_repair(facets) -> None:
    from fdai.core.conversation.semantic_judgment_schema_repair import repair_required

    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(primary_intent="query.manifest", targets=[], requested_facets=facets)
    )

    assert repair_required(proposal)


def test_explicit_document_mode_requires_governed_document_intent() -> None:
    with pytest.raises(
        ValueError,
        match="explicit document evidence requires the governed document query intent",
    ):
        SemanticJudgmentProposal.model_validate(
            _proposal(document_evidence_mode=SemanticDocumentEvidenceMode.EXPLICIT)
        )


def test_ambiguous_judgment_cannot_trigger_document_retrieval() -> None:
    with pytest.raises(
        ValueError,
        match="ambiguous semantic judgment MUST NOT request document evidence",
    ):
        SemanticJudgmentProposal.model_validate(
            _proposal(
                ambiguous=True,
                alternatives=["cost_summary"],
                clarification="Which cost view should I use?",
                document_evidence_mode=SemanticDocumentEvidenceMode.OPTIONAL,
            )
        )


def _binding(tier: SemanticJudgmentTier, model: _Model) -> SemanticJudgmentBinding:
    return SemanticJudgmentBinding(
        tier=tier,
        model=model,  # type: ignore[arg-type]
        model_config_digest=(DIGEST if tier is SemanticJudgmentTier.T1 else "sha256:" + ("b" * 64)),
        prompt_digest=DIGEST,
    )


def _boundary(
    primary: _Model | None,
    escalation: _Model | None = None,
    *,
    schema_repair: _Model | None = None,
    strict_intent_grounding: bool = False,
) -> SemanticJudgmentBoundary:
    return SemanticJudgmentBoundary(
        profile_id="conversation.routing",
        profile_version="1.0.0",
        primary=_binding(SemanticJudgmentTier.T1, primary) if primary else None,
        schema_repair=(_binding(SemanticJudgmentTier.T1, schema_repair) if schema_repair else None),
        escalation=_binding(SemanticJudgmentTier.T2, escalation) if escalation else None,
        strict_intent_grounding=strict_intent_grounding,
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


def test_independent_reviewer_rejects_the_primary_model_binding() -> None:
    model = _Model(_proposal())
    primary = _binding(SemanticJudgmentTier.T1, model)

    with pytest.raises(ValueError, match="distinct model bindings"):
        SemanticJudgmentBoundary(
            profile_id="conversation.routing",
            profile_version="1.0.0",
            primary=primary,
            escalation=SemanticJudgmentBinding(
                tier=SemanticJudgmentTier.T2,
                model=model,  # type: ignore[arg-type]
                model_config_digest=primary.model_config_digest,
                prompt_digest=DIGEST,
            ),
        )


def test_resource_state_judgment_requires_matching_independent_review() -> None:
    proposal = _proposal(
        primary_intent="query.resource_state_inventory",
        targets=[],
        requested_facets=["resource_collection", "list", "current_state"],
    )
    primary = _Model(proposal)
    reviewer = _Model(proposal)

    result = _boundary(primary, reviewer).judge(
        utterance="Show current resource state.",
        context=(),
        capabilities=({"intent": "query.resource_state_inventory"},),
    )

    assert result.accepted is True
    assert result.receipt.reason_code == "accepted_independent_review"
    assert result.receipt.tier is SemanticJudgmentTier.T1
    assert primary.calls == reviewer.calls == 1


def test_resource_state_judgment_holds_when_review_finds_an_omitted_facet() -> None:
    primary = _Model(
        _proposal(
            primary_intent="query.resource_state_inventory",
            targets=[],
            requested_facets=["resource_collection", "list", "current_state"],
        )
    )
    reviewer = _Model(
        _proposal(
            primary_intent="query.resource_state_inventory",
            targets=[],
            requested_facets=["resource_collection", "list", "current_state", "count"],
        )
    )

    result = _boundary(primary, reviewer).judge(
        utterance="Show how many resources exist and their current state.",
        context=(),
        capabilities=({"intent": "query.resource_state_inventory"},),
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.UNAVAILABLE
    assert result.receipt.reason_code == "semantic_judgment_review_conflict"


def test_resource_state_judgment_review_preserves_forbidden_actions() -> None:
    primary = _Model(
        _proposal(
            schema_version="1.1.0",
            primary_intent="query.resource_state_inventory",
            targets=[],
            requested_facets=["resource_collection", "list", "current_state"],
            forbidden_actions=[],
        )
    )
    reviewer = _Model(
        _proposal(
            schema_version="1.1.0",
            primary_intent="query.resource_state_inventory",
            targets=[],
            requested_facets=["resource_collection", "list", "current_state"],
            forbidden_actions=[
                {
                    "kind": "action",
                    "value": "restart",
                    "source_start": 39,
                    "source_end": 46,
                }
            ],
        )
    )

    result = _boundary(primary, reviewer).judge(
        utterance="Show current resource state and do not restart anything.",
        context=(),
        capabilities=(
            {"intent": "query.resource_state_inventory"},
            {"kind": "action_type", "name": "restart"},
        ),
    )

    assert result.accepted is False
    assert result.receipt.reason_code == "semantic_judgment_review_conflict"


def test_resource_state_judgment_holds_when_independent_reviewer_fails() -> None:
    primary = _Model(
        _proposal(
            primary_intent="query.resource_state_inventory",
            targets=[],
            requested_facets=["resource_collection", "list", "current_state"],
        )
    )

    class FailedReviewer(_Model):
        def judge(self, **_kwargs: object) -> object:
            raise OSError("private provider detail")

    result = _boundary(primary, FailedReviewer(None)).judge(
        utterance="Show current resource state.",
        context=(),
        capabilities=({"intent": "query.resource_state_inventory"},),
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.UNAVAILABLE
    assert result.receipt.reason_code == "semantic_judgment_review_unavailable"
    assert "private provider detail" not in result.receipt.model_dump_json()


def test_resource_state_judgment_holds_without_an_independent_reviewer() -> None:
    primary = _Model(
        _proposal(
            primary_intent="query.resource_state_inventory",
            targets=[],
            requested_facets=["resource_collection", "list", "current_state"],
        )
    )

    result = _boundary(primary).judge(
        utterance="Show current resource state.",
        context=(),
        capabilities=({"intent": "query.resource_state_inventory"},),
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.UNAVAILABLE
    assert result.receipt.reason_code == "semantic_judgment_review_unavailable"


def test_schema_repair_runs_once_after_incomplete_typed_schema_family() -> None:
    utterance = "Show the Resource declaration and readable properties."
    primary = _Model(
        _proposal(
            primary_intent="query.manifest",
            targets=[
                {
                    "kind": "object_type",
                    "value": "Resource",
                    "canonical_value": "Resource",
                    "source_start": 9,
                    "source_end": 17,
                }
            ],
            requested_facets=["count", "readable_properties"],
        )
    )
    repair = _Model(
        _proposal(
            primary_intent="query.ontology_declaration",
            targets=[
                {
                    "kind": "object_type",
                    "value": "Resource",
                    "canonical_value": "Resource",
                    "source_start": 9,
                    "source_end": 17,
                }
            ],
            requested_facets=["declaration_detail", "readable_properties"],
        )
    )

    result = _boundary(primary, schema_repair=repair).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.manifest"},
            {"kind": "function_type", "name": "query.ontology_declaration"},
            {"kind": "object_type", "name": "Resource"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.ontology_declaration"
    assert result.proposal.requested_facets == (
        "declaration_detail",
        "readable_properties",
    )
    assert primary.calls == repair.calls == 1


def test_complete_schema_proposal_does_not_spend_repair_call() -> None:
    utterance = "Show the Resource declaration."
    primary = _Model(
        _proposal(
            primary_intent="query.ontology_declaration",
            targets=[
                {
                    "kind": "object_type",
                    "value": "Resource",
                    "canonical_value": "Resource",
                    "source_start": 9,
                    "source_end": 17,
                }
            ],
            requested_facets=["declaration_detail", "readable_properties"],
        )
    )
    repair = _Model(_proposal(primary_intent="query.ontology_declaration"))

    result = _boundary(primary, schema_repair=repair).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.ontology_declaration"},
            {"kind": "object_type", "name": "Resource"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert repair.calls == 0


def test_invalid_schema_repair_retains_primary_fail_closed_proposal() -> None:
    primary = _Model(
        _proposal(
            primary_intent="query.manifest",
            targets=[],
            requested_facets=[],
        )
    )
    repair = _Model(_proposal(primary_intent="cost_breakdown"))

    result = _boundary(primary, schema_repair=repair).judge(
        utterance="Inspect the active ontology schema.",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.manifest"},),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.manifest"
    assert result.receipt.reason_code == "accepted_schema_repair_fallback"
    assert repair.calls == 3


def test_accepts_locale_bound_model_authored_direct_response() -> None:
    model = _DirectResponseModel(answer="반갑습니다. 어떤 내용을 함께 살펴볼까요?")

    result = _boundary(model).judge(
        utterance="반가워",
        context=(),
        capabilities=(),
        locale="ko",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.direct_response is not None
    assert result.proposal.direct_response.answer == "반갑습니다. 어떤 내용을 함께 살펴볼까요?"
    assert result.proposal.direct_response.locale == "ko"


def test_retries_current_state_intent_with_resource_group_target() -> None:
    utterance = "rg-example resource group resources"
    target = {
        "kind": "resource_group",
        "value": "rg-example",
        "source_start": 0,
        "source_end": len("rg-example"),
    }
    model = _SequenceModel(
        [
            _proposal(
                primary_intent="query.resource_current_state",
                targets=[target],
                requested_facets=["resource_identity"],
            ),
            _proposal(
                primary_intent="query.contextual_resources",
                targets=[target],
                requested_facets=["details", "name_filter"],
            ),
        ]
    )

    result = _boundary(model).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.resource_current_state"},
            {"kind": "function_type", "name": "query.contextual_resources"},
        ),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.contextual_resources"
    assert model.calls == 2
    assert model.schema_repairs[1] == (
        {
            "location": "",
            "type": "value_error",
            "reason": "semantic current-state intent requires a Resource target",
        },
    )


@pytest.mark.parametrize(
    "model",
    [
        _DirectResponseModel(answer="Hello.", locale="en"),
        _DirectResponseModel(answer="Hello.", digest=DIGEST),
    ],
)
def test_rejects_direct_response_with_unbound_locale_or_profile(model: _Model) -> None:
    result = _boundary(model).judge(
        utterance="반가워",
        context=(),
        capabilities=(),
        locale="ko",
        direct_response_profile={"identity": "Bragi"},
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


def test_normalizes_kubernetes_event_history_to_the_bound_function() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.kubernetes_event_history",
                targets=[],
                requested_facets=["kubernetes_events", "recent_window", "time_order"],
            )
        )
    ).judge(
        utterance="Show Kubernetes events from the recent window in time order.",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.resource_event_history"},),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.resource_event_history"


def test_normalizes_kubernetes_events_to_the_bound_function() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.kubernetes_events",
                targets=[],
                requested_facets=["kubernetes_events", "time_range", "chronological_order"],
            )
        )
    ).judge(
        utterance="Show Kubernetes events from the recent window in time order.",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.resource_event_history"},),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.resource_event_history"


def test_does_not_normalize_kubernetes_event_history_without_the_function() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.kubernetes_event_history",
                targets=[],
                requested_facets=["kubernetes_events", "recent_window", "time_order"],
            )
        )
    ).judge(
        utterance="Show Kubernetes events from the recent window in time order.",
        context=(),
        capabilities=(),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.kubernetes_event_history"


@pytest.mark.parametrize(
    ("proposed_intent", "expected_facet"),
    (
        ("query.ontology_action_type_count", "action_type_count"),
        ("query.ontology_function_type_count", "function_type_count"),
        ("query.ontology_interface_type_count", "interface_type_count"),
        ("query.ontology_link_type_count", "link_type_count"),
        ("query.ontology_object_type_count", "object_type_count"),
    ),
)
def test_normalizes_ontology_count_alias_to_the_supplied_manifest_function(
    proposed_intent: str,
    expected_facet: str,
) -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent=proposed_intent,
                targets=[],
                requested_facets=[],
            )
        )
    ).judge(
        utterance="Count the declarations in the active ontology release.",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.manifest"},),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.primary_intent == "query.manifest"
    assert result.proposal.requested_facets == (expected_facet,)


def test_rejects_ontology_count_alias_without_the_manifest_function() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.ontology_action_type_count",
                targets=[],
                requested_facets=[],
            )
        )
    ).judge(
        utterance="Count ActionTypes.",
        context=(),
        capabilities=(),
    )

    assert result.accepted is False
    assert result.proposal is None
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


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


@pytest.mark.parametrize(
    ("locale", "expected_clarification"),
    [
        ("en", "Which exact incident ID should the mitigation draft use?"),
        ("ko", "완화 초안에 사용할 정확한 장애 ID는 무엇인가요?"),
    ],
)
def test_targetless_incident_mitigation_draft_requires_typed_identity_clarification(
    locale: str,
    expected_clarification: str,
) -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="action_request",
                targets=[],
                requested_facets=["incident_mitigation", "draft"],
                action_posture="draft_only",
                action_subject="Incident",
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance=(
            "검토 전용 장애 완화 초안을 작성해 주세요."
            if locale == "ko"
            else "Draft a review-only incident mitigation proposal."
        ),
        context=(),
        capabilities=(
            {"kind": "intent", "name": "action_request"},
            {"kind": "object_type", "name": "Incident"},
        ),
        allow_escalation=False,
        locale=locale,
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.CLARIFICATION
    assert result.proposal is not None
    assert result.proposal.unresolved_terms == ("incident_identity",)
    assert result.proposal.clarification == expected_clarification
    assert result.proposal.targets == ()
    assert result.proposal.execution_authority is False


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


def test_strict_candidate_rejects_unsupplied_intent_identity_and_span() -> None:
    invalid_cases = (
        (
            _proposal(primary_intent="invented_query", targets=[]),
            "Show the current state.",
            ({"kind": "function_type", "name": "query.resource_current_state"},),
        ),
        (
            _proposal(
                primary_intent="query.resource_current_state",
                targets=[
                    {
                        "kind": "resource_type",
                        "value": "VM",
                        "canonical_value": "invented.vm",
                        "source_start": 0,
                        "source_end": 2,
                    }
                ],
            ),
            "VM 상태를 보여줘",
            (
                {"kind": "function_type", "name": "query.resource_current_state"},
                {"kind": "resource_type", "name": "compute.vm"},
            ),
        ),
    )
    for proposal, utterance, capabilities in invalid_cases:
        result = _boundary(
            _Model(proposal),
            strict_intent_grounding=True,
        ).judge(
            utterance=utterance,
            context=(),
            capabilities=capabilities,
            allow_escalation=False,
        )
        assert result.accepted is False
        assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


def test_strict_candidate_rejects_catalog_type_on_resource_instance() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.resource_current_state",
                targets=[
                    {
                        "kind": "resource",
                        "value": "vm01",
                        "canonical_value": "compute.vm",
                        "source_start": 0,
                        "source_end": 4,
                    }
                ],
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance="vm01 상태를 보여줘",
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.resource_current_state"},
            {"kind": "resource_type", "name": "compute.vm"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


def test_strict_candidate_repairs_only_one_exact_current_utterance_span() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.resource_current_state",
                targets=[
                    {
                        "kind": "resource",
                        "value": "vm01",
                        "source_start": 1,
                        "source_end": 5,
                    }
                ],
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance="vm01 상태를 보여줘",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.resource_current_state"},),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert (result.proposal.targets[0].source_start, result.proposal.targets[0].source_end) == (
        0,
        4,
    )


def test_strict_current_state_removes_only_redundant_exact_resource_clarification() -> None:
    utterance = "vm01은 지금 실행 중이야?"
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.resource_current_state",
                targets=[
                    {
                        "kind": "resource_type",
                        "value": "vm",
                        "canonical_value": "compute.vm",
                        "source_start": 0,
                        "source_end": 2,
                    },
                    {
                        "kind": "resource",
                        "value": "vm01",
                        "source_start": 0,
                        "source_end": 4,
                    },
                ],
                ambiguous=True,
                alternatives=[],
                unresolved_terms=["resource_identity"],
                clarification="어떤 리소스를 조회할까요?",
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.resource_current_state"},
            {"kind": "resource_type", "name": "compute.vm"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.ambiguous is False
    assert result.proposal.clarification is None
    assert tuple(target.value for target in result.proposal.targets) == ("vm01",)


def test_strict_action_subtype_requires_identity_clarification() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="action_request",
                targets=[
                    {
                        "kind": "resource_type",
                        "value": "VM",
                        "canonical_value": "compute.vm",
                        "source_start": 0,
                        "source_end": 2,
                    }
                ],
                action_posture="draft_only",
                action_subject="ActionType",
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance="VM을 재시작해줘",
        context=(),
        capabilities=(
            {"kind": "intent", "name": "action_request"},
            {"kind": "resource_type", "name": "compute.vm"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.CLARIFICATION
    assert result.proposal is not None
    assert result.proposal.unresolved_terms == ("resource_identity",)
    assert result.proposal.clarification == "Which exact resource name or ID should I use?"


@pytest.mark.parametrize(
    ("primary_intent", "targets", "discourse_mode"),
    [
        (
            "query.resource_event_history",
            [
                {
                    "kind": "time_range",
                    "value": "지난 24시간",
                    "source_start": 0,
                    "source_end": 7,
                }
            ],
            "direct",
        ),
        (
            "action_requirements",
            [
                {
                    "kind": "resource_type",
                    "value": "VM",
                    "canonical_value": "compute.vm",
                    "source_start": 0,
                    "source_end": 2,
                }
            ],
            "hypothetical",
        ),
    ],
)
def test_strict_safe_read_and_action_advice_drop_identity_clarification(
    primary_intent: str,
    targets: list[dict[str, object]],
    discourse_mode: str,
) -> None:
    utterance = (
        "지난 24시간 Resource Health 이벤트를 시간순으로 보여줘"
        if primary_intent.startswith("query.")
        else "VM을 재시작하면 해결될까?"
    )
    result = _boundary(
        _Model(
            _proposal(
                primary_intent=primary_intent,
                targets=targets,
                ambiguous=True,
                alternatives=[],
                unresolved_terms=["resource_identity"],
                clarification="어떤 리소스를 의미하나요?",
                discourse_mode=discourse_mode,
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.resource_event_history"},
            {"kind": "intent", "name": "action_requirements"},
            {"kind": "resource_type", "name": "compute.vm"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.ambiguous is False


def test_strict_time_target_drops_canonical_value_absent_from_capabilities() -> None:
    utterance = "지난 24시간 Resource Health 이벤트를 시간순으로 보여줘"
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.resource_event_history",
                targets=[
                    {
                        "kind": "time_range",
                        "value": "지난 24시간",
                        "canonical_value": "duration.PT24H",
                        "source_start": 0,
                        "source_end": 7,
                    }
                ],
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=({"kind": "function_type", "name": "query.resource_event_history"},),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.targets[0].canonical_value is None


def test_strict_resource_health_history_uses_principal_scope_without_clarification() -> None:
    utterance = "지난 24시간 Resource Health 이벤트를 시간순으로 보여줘"
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.resource_event_history",
                targets=[
                    {
                        "kind": "time_range",
                        "value": "지난 24시간",
                        "source_start": 0,
                        "source_end": 7,
                    }
                ],
                requested_facets=[
                    "resource_health_events",
                    "chronological_order",
                    "time_range",
                ],
                ambiguous=True,
                alternatives=["resource_identity"],
                unresolved_terms=["Resource"],
                clarification="어느 Resource를 조회할까요?",
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=({"kind": "function_type", "name": "query.resource_event_history"},),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.ambiguous is False


def test_strict_complete_error_correlation_drops_redundant_clarification() -> None:
    utterance = "prod-api가 느려. 재시작하지 말고 지난 30분 오류와 변경 이력만 조사해줘"
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.resource_error_activity_correlation",
                targets=[
                    {
                        "kind": "resource",
                        "value": "prod-api",
                        "source_start": 0,
                        "source_end": 8,
                    },
                    {
                        "kind": "time_range",
                        "value": "지난 30분",
                        "source_start": 23,
                        "source_end": 29,
                    },
                ],
                requested_facets=["cause", "errors", "change_history", "time_range"],
                ambiguous=True,
                alternatives=["resource_identity"],
                unresolved_terms=["resource_identity"],
                clarification="어느 리소스를 조사할까요?",
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {
                "kind": "function_type",
                "name": "query.resource_error_activity_correlation",
            },
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.ambiguous is False


def test_forbidden_action_is_grounded_and_never_repaired_from_context() -> None:
    utterance = "prod-api가 느려. 재시작하지 말고 원인만 조사해줘"
    accepted = _boundary(
        _Model(
            _proposal(
                primary_intent="query.resource_current_state",
                targets=[
                    {
                        "kind": "resource",
                        "value": "prod-api",
                        "source_start": 0,
                        "source_end": 8,
                    }
                ],
                forbidden_actions=[
                    {
                        "kind": "action_type",
                        "value": "재시작",
                        "canonical_value": "ops.restart-service",
                        "source_start": utterance.index("재시작"),
                        "source_end": utterance.index("재시작") + len("재시작"),
                    }
                ],
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {
                "kind": "function_type",
                "name": "query.resource_current_state",
            },
            {"kind": "action_type", "name": "ops.restart-service"},
        ),
        allow_escalation=False,
    )
    rejected = _boundary(
        _Model(
            _proposal(
                primary_intent="explanation",
                targets=[],
                forbidden_actions=[
                    {
                        "kind": "action",
                        "value": "재시작",
                        "source_start": 0,
                        "source_end": 3,
                    }
                ],
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance="원인만 조사해줘",
        context=("재시작하지 마",),
        capabilities=(
            {
                "kind": "intent",
                "name": "explanation",
            },
        ),
        allow_escalation=False,
    )

    assert accepted.accepted is True
    assert accepted.proposal is not None
    assert accepted.proposal.action_posture == "advise_only"
    assert rejected.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


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


def test_malformed_t2_does_not_restore_low_confidence_t1_candidate() -> None:
    t1 = _Model(_proposal(confidence=0.5))
    t2 = _Model({"primary_intent": "broken"})

    result = _boundary(t1, t2).judge(
        utterance="Show api-example budget status",
        context=(),
        capabilities=(),
    )

    assert result.accepted is False
    assert result.proposal is None
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED
    assert result.receipt.tier is None
    assert (t1.calls, t2.calls) == (1, 3)


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


def test_strict_candidate_never_uses_legacy_safe_trace_recovery() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.ontology_relationships",
                targets=[],
                requested_facets=[
                    "resource_type",
                    "signal_type",
                    "action_type",
                    "trace",
                ],
                ambiguous=True,
                alternatives=["current_finding"],
                unresolved_terms=["current_finding_state"],
                clarification=None,
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance="Trace the governed ontology declarations.",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.ontology_relationships"},),
        allow_escalation=False,
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.MALFORMED


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


def test_collection_function_discards_only_redundant_resource_identity_ambiguity() -> None:
    proposal = _proposal(
        primary_intent="query.resource_state_inventory",
        targets=[],
        requested_facets=["current_state", "resource_identity"],
        confidence=0.82,
        ambiguous=True,
        alternatives=[],
        unresolved_terms=["resource_identity"],
        clarification="Which exact resource should I inspect?",
    )
    model = _Model(proposal)
    reviewer = _Model(proposal)

    result = _boundary(model, reviewer).judge(
        utterance="Show resources that are currently not running.",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.resource_state_inventory"},),
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.ambiguous is False
    assert result.proposal.unresolved_terms == ()
    assert result.proposal.clarification is None


@pytest.mark.parametrize(
    ("primary_intent", "secondary_intents", "targets", "capabilities"),
    (
        (
            "query.resource_event_history",
            [],
            [
                {
                    "kind": "time_range",
                    "value": "지난 24시간",
                    "source_start": 0,
                    "source_end": 7,
                }
            ],
            ({"kind": "function_type", "name": "query.resource_event_history"},),
        ),
        (
            "query.subscription_service_health",
            ["query.resource_state_inventory"],
            [
                {
                    "kind": "resource_type",
                    "value": "VM",
                    "canonical_value": "compute.vm",
                    "source_start": 0,
                    "source_end": 2,
                }
            ],
            (
                {"kind": "function_type", "name": "query.subscription_service_health"},
                {"kind": "function_type", "name": "query.resource_state_inventory"},
                {"kind": "resource_type", "name": "compute.vm"},
            ),
        ),
    ),
)
def test_complete_collection_scope_drops_redundant_resource_identity_clarification(
    primary_intent: str,
    secondary_intents: list[str],
    targets: list[dict[str, object]],
    capabilities: tuple[dict[str, object], ...],
) -> None:
    utterance = (
        "지난 24시간 Resource Health 이벤트를 보여줘"
        if primary_intent == "query.resource_event_history"
        else "VM과 Service Health를 같이 보여줘"
    )
    result = _boundary(
        _Model(
            _proposal(
                primary_intent=primary_intent,
                secondary_intents=secondary_intents,
                targets=targets,
                requested_facets=["current_state"],
                ambiguous=True,
                alternatives=["resource_identity"],
                unresolved_terms=["Resource"],
                clarification="어느 Resource를 조회할까요?",
            )
        ),
        strict_intent_grounding=True,
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=capabilities,
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.ambiguous is False
    assert result.proposal.unresolved_terms == ()
    assert result.proposal.clarification is None


@pytest.mark.parametrize(
    ("primary_intent", "targets", "requested_facets"),
    (
        (
            "query.ontology_declaration",
            [],
            ["agent_declaration", "read_only_properties"],
        ),
        (
            "query.ontology_relationships",
            [
                {
                    "kind": "object_type",
                    "value": "BusinessService",
                    "canonical_value": "BusinessService",
                    "source_start": 0,
                    "source_end": 15,
                }
            ],
            ["declared_relationships", "incoming_relationships", "outgoing_relationships"],
        ),
    ),
)
def test_complete_schema_subject_drops_redundant_identity_clarification(
    primary_intent: str,
    targets: list[dict[str, object]],
    requested_facets: list[str],
) -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent=primary_intent,
                targets=targets,
                requested_facets=requested_facets,
                ambiguous=True,
                alternatives=["resource_identity"],
                unresolved_terms=["Resource"],
                clarification="Which exact schema subject should I use?",
            )
        )
    ).judge(
        utterance="BusinessService schema" if targets else "Agent schema",
        context=(),
        capabilities=(
            {"kind": "function_type", "name": primary_intent},
            {"kind": "object_type", "name": "Agent"},
            {"kind": "object_type", "name": "BusinessService"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.ambiguous is False
    assert result.proposal.unresolved_terms == ()
    assert result.proposal.clarification is None


def test_schema_identity_ambiguity_preserves_multiple_typed_subjects() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.ontology_declaration",
                targets=[],
                requested_facets=["agent_declaration", "workload_declaration"],
                ambiguous=True,
                alternatives=["Agent", "Workload"],
                unresolved_terms=["schema_subject"],
                clarification="Which schema subject should I use?",
            )
        )
    ).judge(
        utterance="Show the Agent or Workload schema.",
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.ontology_declaration"},
            {"kind": "object_type", "name": "Agent"},
            {"kind": "object_type", "name": "Workload"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is False
    assert result.receipt.disposition is SemanticJudgmentDisposition.CLARIFICATION


@pytest.mark.parametrize(
    "primary_intent",
    ("query.ontology_declaration", "query.ontology_relationships"),
)
def test_schema_target_drops_only_the_generic_object_type_suffix(
    primary_intent: str,
) -> None:
    utterance = "Show the Resource ObjectType declaration."
    result = _boundary(
        _Model(
            _proposal(
                primary_intent=primary_intent,
                targets=[
                    {
                        "kind": "object_type",
                        "value": "Resource ObjectType",
                        "canonical_value": "Resource",
                        "source_start": 9,
                        "source_end": 28,
                    }
                ],
                requested_facets=(
                    ["declaration_detail"]
                    if primary_intent == "query.ontology_declaration"
                    else ["incoming_relationships", "outgoing_relationships"]
                ),
            )
        )
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "function_type", "name": primary_intent},
            {"kind": "object_type", "name": "Resource"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert len(result.proposal.targets) == 1
    assert result.proposal.targets[0].value == "Resource"
    assert result.proposal.targets[0].source_start == 9
    assert result.proposal.targets[0].source_end == 17


def test_relationship_target_drops_a_generic_link_type_metatype() -> None:
    utterance = "Which LinkTypes enter and leave BusinessService?"
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.ontology_relationships",
                targets=[
                    {
                        "kind": "object_type",
                        "value": "LinkTypes",
                        "canonical_value": "LinkType",
                        "source_start": 6,
                        "source_end": 15,
                    },
                    {
                        "kind": "object_type",
                        "value": "BusinessService",
                        "canonical_value": "BusinessService",
                        "source_start": 32,
                        "source_end": 47,
                    },
                ],
                requested_facets=["incoming_relationships", "outgoing_relationships"],
            )
        )
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.ontology_relationships"},
            {"kind": "object_type", "name": "LinkType"},
            {"kind": "object_type", "name": "BusinessService"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert [target.canonical_value for target in result.proposal.targets] == ["BusinessService"]


@pytest.mark.parametrize(
    "primary_intent",
    ("query.ontology_declaration", "query.ontology_relationships"),
)
def test_schema_intent_recovers_one_exact_supplied_subject(
    primary_intent: str,
) -> None:
    utterance = "Show the Finding ObjectType schema."
    result = _boundary(
        _Model(
            _proposal(
                primary_intent=primary_intent,
                targets=[
                    {
                        "kind": "object_type",
                        "value": "ObjectType",
                        "canonical_value": "ObjectType",
                        "source_start": 17,
                        "source_end": 27,
                    }
                ],
                requested_facets=[],
                ambiguous=True,
                alternatives=["schema_subject"],
                unresolved_terms=["schema_subject"],
                clarification="Which schema subject should I use?",
            )
        )
    ).judge(
        utterance=utterance,
        context=(),
        capabilities=(
            {"kind": "function_type", "name": primary_intent},
            {"kind": "object_type", "name": "Finding"},
            {"kind": "object_type", "name": "ObjectType"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.ambiguous is False
    assert [target.canonical_value for target in result.proposal.targets] == ["Finding"]


def test_schema_intent_does_not_choose_between_two_supplied_subjects() -> None:
    result = _boundary(
        _Model(
            _proposal(
                primary_intent="query.ontology_declaration",
                targets=[],
                requested_facets=[],
            )
        )
    ).judge(
        utterance="Compare the Finding and Incident schemas.",
        context=(),
        capabilities=(
            {"kind": "function_type", "name": "query.ontology_declaration"},
            {"kind": "object_type", "name": "Finding"},
            {"kind": "object_type", "name": "Incident"},
        ),
        allow_escalation=False,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert result.proposal.targets == ()


@pytest.mark.parametrize(
    ("confidence", "unresolved_terms", "alternatives", "expected_disposition"),
    (
        (0.5, ["resource_identity"], [], SemanticJudgmentDisposition.LOW_CONFIDENCE),
        (
            0.82,
            ["resource_identity", "time_range"],
            [],
            SemanticJudgmentDisposition.CLARIFICATION,
        ),
        (
            0.82,
            ["resource_identity"],
            ["resource_a"],
            SemanticJudgmentDisposition.CLARIFICATION,
        ),
    ),
)
def test_collection_function_preserves_low_confidence_and_material_ambiguity(
    confidence: float,
    unresolved_terms: list[str],
    alternatives: list[str],
    expected_disposition: SemanticJudgmentDisposition,
) -> None:
    model = _Model(
        _proposal(
            primary_intent="query.resource_state_inventory",
            targets=[],
            requested_facets=["current_state"],
            confidence=confidence,
            ambiguous=True,
            alternatives=alternatives,
            unresolved_terms=unresolved_terms,
            clarification="Which scope should I inspect?",
        )
    )

    result = _boundary(model).judge(
        utterance="Show resources that are currently not running.",
        context=(),
        capabilities=({"kind": "function_type", "name": "query.resource_state_inventory"},),
        allow_escalation=False,
    )

    assert result.receipt.disposition is expected_disposition


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
