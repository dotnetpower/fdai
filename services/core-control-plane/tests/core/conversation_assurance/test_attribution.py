from __future__ import annotations

from fdai.core.conversation_assurance import (
    AdequacyCandidateKind,
    AdequacyReviewState,
    FailureLayer,
    TurnAssessmentInput,
    attribute_answer_failure,
    build_ontology_adequacy_review,
)


def _turn(reason_code: str, **overrides: object) -> TurnAssessmentInput:
    values: dict[str, object] = {
        "turn_id": "turn-1",
        "conversation_id": "conversation-1",
        "principal_scope": "principal-scope",
        "question": "What happens next?",
        "answer": "The result could not be verified.",
        "question_digest": "q" * 64,
        "answer_digest": "a" * 64,
        "evidence_manifest_digest": "e" * 64,
        "evidence_refs": ("evidence:1",),
        "verification_status": "unverified",
        "verification_authority": "server_read_model",
        "checks_completed": 0,
        "checks_total": 1,
        "verification_reason_code": reason_code,
        "verification_route_id": "route-1",
        "evidence_complete": True,
        "ontology_release": "sha256:" + "b" * 64,
        "graph_revision": "graph-2",
    }
    values.update(overrides)
    return TurnAssessmentInput(**values)  # type: ignore[arg-type]


def test_provider_failure_is_not_an_ontology_review() -> None:
    attribution = attribute_answer_failure(_turn("provider_unavailable"))
    review = build_ontology_adequacy_review(
        attribution,
        question_digest="q" * 64,
        replay_reproduced=True,
        routing_verified=True,
        identity_resolved=True,
    )

    assert attribution.layer is FailureLayer.EVIDENCE
    assert review.state is AdequacyReviewState.NOT_APPLICABLE
    assert review.candidate_kind is None


def test_reproduced_schema_gap_opens_declaration_review() -> None:
    attribution = attribute_answer_failure(_turn("unknown_link_type"))
    review = build_ontology_adequacy_review(
        attribution,
        question_digest="q" * 64,
        replay_reproduced=True,
        routing_verified=True,
        identity_resolved=True,
    )

    assert attribution.layer is FailureLayer.ONTOLOGY_SCHEMA
    assert review.state is AdequacyReviewState.READY
    assert review.candidate_kind is AdequacyCandidateKind.ONTOLOGY_DECLARATION
    assert review.reason_codes == ("adequacy_review_ready",)


def test_dynamic_gap_routes_to_dynamic_model_review() -> None:
    attribution = attribute_answer_failure(_turn("active_model_unavailable"))
    review = build_ontology_adequacy_review(
        attribution,
        question_digest="q" * 64,
        replay_reproduced=True,
        routing_verified=True,
        identity_resolved=True,
    )

    assert attribution.layer is FailureLayer.DYNAMIC
    assert review.candidate_kind is AdequacyCandidateKind.DYNAMIC_MODEL
    assert review.state is AdequacyReviewState.READY


def test_ontology_gap_holds_when_any_precondition_is_missing() -> None:
    attribution = attribute_answer_failure(
        _turn(
            "ontology_mapping_missing",
            evidence_complete=False,
            ontology_release=None,
            graph_revision=None,
        )
    )
    review = build_ontology_adequacy_review(
        attribution,
        question_digest="q" * 64,
        replay_reproduced=False,
        routing_verified=False,
        identity_resolved=False,
    )

    assert review.state is AdequacyReviewState.HELD
    assert review.candidate_kind is AdequacyCandidateKind.PROVIDER_MAPPING
    assert set(review.reason_codes) == {
        "evidence_incomplete",
        "gap_not_reproduced",
        "graph_revision_unavailable",
        "identity_unresolved",
        "ontology_release_unavailable",
        "routing_unverified",
    }


def test_attribution_identity_binds_exact_reason_code() -> None:
    first = attribute_answer_failure(_turn("unknown_object_type"))
    second = attribute_answer_failure(_turn("unknown_link_type"))

    assert first.attribution_id != second.attribution_id


def test_missing_exact_reason_remains_unknown_instead_of_evidence_failure() -> None:
    attribution = attribute_answer_failure(_turn("verification_reason_unavailable"))

    assert attribution.layer is FailureLayer.UNKNOWN
