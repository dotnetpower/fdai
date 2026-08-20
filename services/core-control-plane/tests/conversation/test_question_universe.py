"""Declaration-derived finite question-universe generation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation import (
    GeneratedQuestionCase,
    GeneratedQuestionUniverse,
    QuestionAnchorKind,
    QuestionCapabilityFamily,
    QuestionCaseClass,
    QuestionCaseExclusion,
    QuestionCausalResult,
    QuestionEntityState,
    QuestionEvidencePosture,
    QuestionExclusionReason,
    QuestionExpectedPosture,
    QuestionPerspective,
    QuestionPresentationShape,
    QuestionRuleState,
    QuestionTemporalState,
    QuestionUniverseGrammar,
    generate_question_universe,
)
from fdai.core.ontology_platform import QueryManifest, build_query_manifest
from fdai.shared.contracts.models import (
    ActionInterface,
    CeilingRole,
    OntologyActionType,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyObjectType,
    Operation,
    PromotionGate,
    PropertyDecl,
    PropertyType,
    RollbackKind,
)
from fdai.shared.ontology.release import build_ontology_release

SCOPE_DIGEST = "sha256:" + "f" * 64


def test_question_universe_contract_is_exported_from_conversation_package() -> None:
    assert GeneratedQuestionCase.__module__.endswith("question_universe")
    assert GeneratedQuestionUniverse.__module__.endswith("question_universe")
    assert QuestionCaseExclusion.__module__.endswith("question_universe")


def _object(name: str) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )


def _function() -> OntologyFunctionType:
    return OntologyFunctionType(
        name="query.resources",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "a" * 64,
        publisher="fdai",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_role=CeilingRole.READER,
    )


def _action() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.example",
        version="1.0.0",
        operation=Operation.TAG,
        interfaces=(ActionInterface.CONTROL_PLANE, ActionInterface.IDEMPOTENT_BY_KEY),
        rollback_contract=RollbackKind.PR_REVERT,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        description="Draft-only generic remediation example.",
    )


def _object_manifest(*names: str, purposes: tuple[str, ...] = ()) -> QueryManifest:
    objects = tuple(_object(name) for name in names)
    release = build_ontology_release(object_types=objects)
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=purposes,
        principal_scope_digest=SCOPE_DIGEST,
        object_types=objects,
    )


def _unavailable_manifest() -> QueryManifest:
    function = _function()
    release = build_ontology_release(function_types=(function,))
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=(),
        principal_scope_digest=SCOPE_DIGEST,
        functions=(function,),
        bound_function_names=(),
    )


def test_generation_is_stable_under_manifest_and_axis_reordering() -> None:
    first_manifest = _object_manifest("Resource", "Service")
    second_manifest = _object_manifest("Resource", "Service", purposes=("operations-review",))
    first_grammar = QuestionUniverseGrammar.build(
        locales=("ko-KR", "en-US"),
        case_classes=(QuestionCaseClass.ZERO_MATCH, QuestionCaseClass.POSITIVE),
        path_depths=(2, 1),
        result_bounds=(100, 10),
    )
    second_grammar = QuestionUniverseGrammar.build(
        locales=("en-US", "ko-KR"),
        case_classes=(QuestionCaseClass.POSITIVE, QuestionCaseClass.ZERO_MATCH),
        path_depths=(1, 2),
        result_bounds=(10, 100),
    )

    first = generate_question_universe(
        manifests=(first_manifest, second_manifest), grammar=first_grammar
    )
    second = generate_question_universe(
        manifests=(second_manifest, first_manifest), grammar=second_grammar
    )

    assert first.grammar.digest == second.grammar.digest
    assert first.receipt == second.receipt
    assert first.cases == second.cases
    assert first.generation_digest == second.generation_digest


def test_unavailable_declaration_becomes_reason_bearing_exclusion() -> None:
    manifest = _unavailable_manifest()
    grammar = QuestionUniverseGrammar.build(locales=("en-US",))

    generated = generate_question_universe(manifests=(manifest,), grammar=grammar)

    assert generated.cases == ()
    assert len(generated.exclusions) == 1
    assert generated.exclusions[0].declaration_id == "function:query.resources"
    assert generated.exclusions[0].reason is QuestionExclusionReason.RUNTIME_BINDING_UNAVAILABLE
    assert generated.receipt.case_ids == ()
    assert generated.receipt.excluded_case_ids == (generated.exclusions[0].case_id,)


def test_non_cartesian_perspectives_and_evidence_postures_enter_case_identity() -> None:
    manifest = _object_manifest("Resource", "BusinessService", "CausalHypothesis")
    grammar = QuestionUniverseGrammar.build(
        locales=("en", "ko"),
        case_classes=(QuestionCaseClass.POSITIVE,),
        evidence_postures=(
            QuestionEvidencePosture.FRESH,
            QuestionEvidencePosture.INCOMPLETE,
        ),
    )

    generated = generate_question_universe(manifests=(manifest,), grammar=grammar)

    assert {case.perspective for case in generated.cases} == {
        QuestionPerspective.RESOURCE,
        QuestionPerspective.SERVICE,
        QuestionPerspective.OPERATION,
        QuestionPerspective.BUSINESS,
        QuestionPerspective.CAUSAL,
    }
    resource_cases = [case for case in generated.cases if case.declaration_id == "object:Resource"]
    assert {case.perspective for case in resource_cases} == {
        QuestionPerspective.RESOURCE,
        QuestionPerspective.OPERATION,
    }
    assert all(case.perspective is not QuestionPerspective.ACTION for case in resource_cases)
    assert {
        case.expected_posture
        for case in generated.cases
        if case.evidence_posture is QuestionEvidencePosture.INCOMPLETE
    } == {QuestionExpectedPosture.HOLD}
    assert any(
        case.required_capability is QuestionCapabilityFamily.EVIDENCE_JOIN
        and case.anchor_kind is QuestionAnchorKind.SERVER_SCOPE
        for case in generated.cases
    )
    causal_cases = [
        case for case in generated.cases if case.perspective is QuestionPerspective.CAUSAL
    ]
    assert causal_cases
    assert {case.entity_state for case in causal_cases} == {QuestionEntityState.EXACT}
    assert {case.temporal_state for case in causal_cases} == {QuestionTemporalState.ALIGNED}
    assert {case.causal_result for case in causal_cases} == {QuestionCausalResult.COMPETING}
    assert {case.presentation_shape for case in causal_cases} == {QuestionPresentationShape.TABLE}
    noncausal = [
        case for case in generated.cases if case.perspective is not QuestionPerspective.CAUSAL
    ]
    assert {case.entity_state for case in noncausal} == {QuestionEntityState.NOT_APPLICABLE}
    assert {case.temporal_state for case in noncausal} == {QuestionTemporalState.NOT_APPLICABLE}
    assert {case.causal_result for case in noncausal} == {QuestionCausalResult.NOT_APPLICABLE}
    assert {case.presentation_shape for case in noncausal} == {QuestionPresentationShape.DEFAULT}
    assert len({case.case_id for case in generated.cases}) == len(generated.cases)


def test_causal_question_space_expands_all_investigation_assurance_axes() -> None:
    manifest = _object_manifest("CausalHypothesis")
    grammar = QuestionUniverseGrammar.build(
        locales=("en", "ko"),
        case_classes=(QuestionCaseClass.POSITIVE,),
        entity_states=(
            QuestionEntityState.AMBIGUOUS,
            QuestionEntityState.EXACT,
            QuestionEntityState.MISSING,
        ),
        temporal_states=(
            QuestionTemporalState.ALIGNED,
            QuestionTemporalState.PARTIAL_CURRENT,
            QuestionTemporalState.STALE_BASELINE,
        ),
        causal_results=(
            QuestionCausalResult.COMPETING,
            QuestionCausalResult.REFUTED,
            QuestionCausalResult.SUPPORTED,
            QuestionCausalResult.UNRESOLVED,
        ),
        presentation_shapes=(
            QuestionPresentationShape.TABLE,
            QuestionPresentationShape.TIMELINE,
        ),
    )

    generated = generate_question_universe(manifests=(manifest,), grammar=grammar)

    assert len(generated.cases) == 144
    assert {case.locale for case in generated.cases} == {"en", "ko"}
    assert {case.entity_state for case in generated.cases} == {
        QuestionEntityState.AMBIGUOUS,
        QuestionEntityState.EXACT,
        QuestionEntityState.MISSING,
    }
    assert {case.temporal_state for case in generated.cases} == {
        QuestionTemporalState.ALIGNED,
        QuestionTemporalState.PARTIAL_CURRENT,
        QuestionTemporalState.STALE_BASELINE,
    }
    assert {case.causal_result for case in generated.cases} == {
        QuestionCausalResult.COMPETING,
        QuestionCausalResult.REFUTED,
        QuestionCausalResult.SUPPORTED,
        QuestionCausalResult.UNRESOLVED,
    }
    assert {case.presentation_shape for case in generated.cases} == {
        QuestionPresentationShape.TABLE,
        QuestionPresentationShape.TIMELINE,
    }
    assert {
        case.expected_posture
        for case in generated.cases
        if case.entity_state is QuestionEntityState.AMBIGUOUS
    } == {QuestionExpectedPosture.CLARIFY}
    assert {
        case.expected_posture
        for case in generated.cases
        if case.entity_state is QuestionEntityState.EXACT
        and case.temporal_state is QuestionTemporalState.STALE_BASELINE
    } == {QuestionExpectedPosture.HOLD}


def test_all_seven_perspectives_have_english_and_korean_coverage() -> None:
    objects = (
        _object("Resource"),
        _object("BusinessService"),
        _object("BusinessCapability"),
        _object("CausalHypothesis"),
        _object("Rule"),
    )
    action = _action()
    release = build_ontology_release(object_types=objects, action_types=(action,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=(),
        principal_scope_digest=SCOPE_DIGEST,
        object_types=objects,
        action_types=(action,),
    )
    generated = generate_question_universe(
        manifests=(manifest,),
        grammar=QuestionUniverseGrammar.build(
            locales=("en", "ko"),
            case_classes=(QuestionCaseClass.POSITIVE,),
        ),
    )

    expected = set(QuestionPerspective)
    for locale in ("en", "ko"):
        assert {case.perspective for case in generated.cases if case.locale == locale} == expected


def test_active_and_collected_rule_cases_are_distinct_policy_references() -> None:
    generated = generate_question_universe(
        manifests=(_object_manifest("Rule"),),
        grammar=QuestionUniverseGrammar.build(
            locales=("en",),
            case_classes=(QuestionCaseClass.POSITIVE,),
        ),
    )

    assert {case.rule_state for case in generated.cases} == {
        QuestionRuleState.ACTIVE,
        QuestionRuleState.COLLECTED,
    }
    assert {case.perspective for case in generated.cases} == {QuestionPerspective.POLICY}
    assert {case.required_capability for case in generated.cases} == {
        QuestionCapabilityFamily.POLICY_REFERENCE
    }
    assert len({case.case_id for case in generated.cases}) == 2


def test_generation_rejects_mixed_releases_and_incomplete_accounting() -> None:
    first = _object_manifest("Resource")
    second = _object_manifest("Service")
    grammar = QuestionUniverseGrammar.build(locales=("en-US",))

    with pytest.raises(ValueError, match="one ontology release"):
        generate_question_universe(manifests=(first, second), grammar=grammar)

    incomplete = replace(
        first,
        coverage_receipt=first.coverage_receipt.model_copy(update={"complete": False}),
    )
    with pytest.raises(ValueError, match="complete principal manifests"):
        generate_question_universe(manifests=(incomplete,), grammar=grammar)


def test_generation_fails_preflight_before_case_expansion_exceeds_bound() -> None:
    manifest = _object_manifest("Resource", "Service")
    grammar = QuestionUniverseGrammar.build(
        locales=("en-US",),
        case_classes=(QuestionCaseClass.POSITIVE,),
        max_cases=1,
    )

    with pytest.raises(ValueError, match="preflight case bound"):
        generate_question_universe(manifests=(manifest,), grammar=grammar)


def test_generation_preflight_counts_each_perspective_application() -> None:
    manifest = _object_manifest("Resource")
    grammar = QuestionUniverseGrammar.build(
        locales=("en-US",),
        max_cases=4,
    )

    with pytest.raises(ValueError, match="preflight case bound"):
        generate_question_universe(manifests=(manifest,), grammar=grammar)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"locales": ()}, "locales MUST be non-empty"),
        ({"locales": ("english",)}, "locales MUST be canonical"),
        ({"locales": ("en-US",), "case_classes": ()}, "case classes MUST be non-empty"),
        ({"locales": ("en-US",), "path_depths": (0,)}, "path depths MUST be in"),
        ({"locales": ("en-US",), "result_bounds": (100_001,)}, "result bounds MUST be in"),
        ({"locales": ("en-US",), "max_cases": 0}, "max_cases MUST be in"),
        ({"locales": ("en-US",), "max_cases": 10_001}, "max_cases MUST be in"),
    ),
)
def test_grammar_rejects_empty_or_out_of_bounds_axes(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        QuestionUniverseGrammar.build(**kwargs)  # type: ignore[arg-type]

    valid = QuestionUniverseGrammar.build(locales=("en-US",))
    with pytest.raises(ValueError, match="case classes MUST be unique and ordered"):
        replace(
            valid,
            case_classes=(QuestionCaseClass.ZERO_MATCH, QuestionCaseClass.POSITIVE),
        )
    with pytest.raises(ValueError, match="path depths MUST be non-empty, unique, and ordered"):
        replace(valid, path_depths=(1, 1))
    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(valid, digest="not-a-digest")
    with pytest.raises(ValueError, match="digest does not match"):
        replace(valid, digest="sha256:" + "0" * 64)


def test_generation_requires_nonempty_unique_manifest_inventory() -> None:
    manifest = _object_manifest("Resource")
    grammar = QuestionUniverseGrammar.build(locales=("en-US",))

    with pytest.raises(ValueError, match="at least one principal manifest"):
        generate_question_universe(manifests=(), grammar=grammar)
    with pytest.raises(ValueError, match="principal manifests MUST be unique"):
        generate_question_universe(manifests=(manifest, manifest), grammar=grammar)
    with pytest.raises(ValueError, match="no readable declaration accounting"):
        generate_question_universe(manifests=(_object_manifest(),), grammar=grammar)


def test_generation_rejects_tampered_manifest_receipts_and_exclusions() -> None:
    manifest = _object_manifest("Resource")
    grammar = QuestionUniverseGrammar.build(locales=("en-US",))

    wrong_release = replace(
        manifest,
        coverage_receipt=manifest.coverage_receipt.model_copy(
            update={"ontology_release_digest": "sha256:" + "0" * 64}
        ),
    )
    with pytest.raises(ValueError, match="different ontology release"):
        generate_question_universe(manifests=(wrong_release,), grammar=grammar)

    wrong_manifest = replace(
        manifest,
        coverage_receipt=manifest.coverage_receipt.model_copy(
            update={"manifest_digest": "sha256:" + "0" * 64}
        ),
    )
    with pytest.raises(ValueError, match="different manifest"):
        generate_question_universe(manifests=(wrong_manifest,), grammar=grammar)

    wrong_count = replace(
        manifest,
        coverage_receipt=manifest.coverage_receipt.model_copy(update={"descriptor_count": 0}),
    )
    with pytest.raises(ValueError, match="descriptor count is incomplete"):
        generate_question_universe(manifests=(wrong_count,), grammar=grammar)

    unavailable = _unavailable_manifest()
    unsupported = replace(
        unavailable,
        unavailable=(
            {
                "declaration_id": unavailable.unavailable[0]["declaration_id"],
                "reason": "provider_not_configured",
            },
        ),
    )
    with pytest.raises(ValueError, match="unsupported question exclusion reason"):
        generate_question_universe(manifests=(unsupported,), grammar=grammar)


@pytest.mark.parametrize(
    ("descriptor", "message"),
    (
        ({"name": "Resource", "declaration_digest": "sha256:" + "a" * 64}, "kind and name"),
        ({"kind": "object", "name": "Resource"}, "declaration digest"),
        (
            {"kind": "object", "name": "Resource", "declaration_digest": "invalid"},
            "canonical SHA-256",
        ),
    ),
)
def test_generation_rejects_malformed_descriptors(
    descriptor: dict[str, object], message: str
) -> None:
    manifest = replace(_object_manifest("Resource"), descriptors=(descriptor,))
    grammar = QuestionUniverseGrammar.build(locales=("en-US",))

    with pytest.raises(ValueError, match=message):
        generate_question_universe(manifests=(manifest,), grammar=grammar)


def test_generation_rejects_duplicate_or_incomplete_declaration_accounting() -> None:
    manifest = _object_manifest("Resource")
    descriptor = manifest.descriptors[0]
    duplicate = replace(
        manifest,
        descriptors=(descriptor, descriptor),
        coverage_receipt=manifest.coverage_receipt.model_copy(
            update={"descriptor_count": 2, "readable_declaration_count": 2}
        ),
    )
    grammar = QuestionUniverseGrammar.build(locales=("en-US",))

    with pytest.raises(ValueError, match="declaration accounting MUST be unique"):
        generate_question_universe(manifests=(duplicate,), grammar=grammar)

    unavailable = _unavailable_manifest()
    missing_id = replace(unavailable, unavailable=({"reason": "runtime_binding_unavailable"},))
    with pytest.raises(ValueError, match="require a declaration id"):
        generate_question_universe(manifests=(missing_id,), grammar=grammar)

    missing_reason = replace(
        unavailable,
        unavailable=({"declaration_id": unavailable.unavailable[0]["declaration_id"]},),
    )
    with pytest.raises(ValueError, match="require a reason"):
        generate_question_universe(manifests=(missing_reason,), grammar=grammar)

    wrong_unavailable = replace(
        unavailable,
        coverage_receipt=unavailable.coverage_receipt.model_copy(
            update={"unavailable_declaration_ids": ()}
        ),
    )
    with pytest.raises(ValueError, match="unavailable accounting is incomplete"):
        generate_question_universe(manifests=(wrong_unavailable,), grammar=grammar)

    wrong_readable = replace(
        manifest,
        coverage_receipt=manifest.coverage_receipt.model_copy(
            update={"readable_declaration_count": 2}
        ),
    )
    with pytest.raises(ValueError, match="readable declaration accounting is incomplete"):
        generate_question_universe(manifests=(wrong_readable,), grammar=grammar)
