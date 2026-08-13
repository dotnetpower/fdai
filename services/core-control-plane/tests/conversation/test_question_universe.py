"""Declaration-derived finite question-universe generation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation.question_universe import (
    QuestionCaseClass,
    QuestionExclusionReason,
    QuestionUniverseGrammar,
    generate_question_universe,
)
from fdai.core.ontology_platform import QueryManifest, build_query_manifest
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release

SCOPE_DIGEST = "sha256:" + "f" * 64


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


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"locales": ()}, "locales MUST be non-empty"),
        ({"locales": ("english",)}, "locales MUST be canonical"),
        ({"locales": ("en-US",), "case_classes": ()}, "case classes MUST be non-empty"),
        ({"locales": ("en-US",), "path_depths": (0,)}, "path depths MUST be in"),
        ({"locales": ("en-US",), "result_bounds": (100_001,)}, "result bounds MUST be in"),
        ({"locales": ("en-US",), "max_cases": 0}, "max_cases MUST be in"),
    ),
)
def test_grammar_rejects_empty_or_out_of_bounds_axes(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        QuestionUniverseGrammar.build(**kwargs)  # type: ignore[arg-type]

    valid = QuestionUniverseGrammar.build(locales=("en-US",))
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
