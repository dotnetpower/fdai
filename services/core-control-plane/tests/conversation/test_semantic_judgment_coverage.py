"""A blind second reading keeps a typed judgment from silently dropping a stated constraint."""

from __future__ import annotations

import concurrent.futures
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.conversation.semantic_judgment_coverage import (
    UNCOVERED_CONSTRAINT_CODE,
    JudgmentCoverage,
    detached_named_spans,
    settled_proposal,
    uncovered_constraint_spans,
)
from fdai.core.conversation.semantic_judgment_review import requires_independent_review
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
from fdai.core.conversation.semantic_reasoning_review import resolve_extraction
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanVerifier
from fdai_service_contracts.ontology_query import QueryNodeKind
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
    SemanticTarget,
)

from tests.conversation.test_semantic_judgment import _boundary, _proposal, _SequenceModel
from tests.conversation.test_semantic_planning import (
    _VM_GROUP,
    NOW,
    _ManifestProvider,
    _Model,
    _typed_fixture,
)

_STATE = "실행 중인 VM 보여줘"


def _reading(utterance: str, *quotes: tuple[str, str]) -> dict[str, Any]:
    return {
        "constraints": [
            {"quote": {"text": text, "occurrence": 1}, "role": role} for role, text in quotes
        ],
        "literals": [],
    }


def _coverage(utterance: str, raw: dict[str, Any] | None) -> JudgmentCoverage:
    future: concurrent.futures.Future[Any] = concurrent.futures.Future()
    future.set_result(raw)
    return JudgmentCoverage(future, utterance, 1.0)


def _target(utterance: str, kind: str, value: str) -> dict[str, Any]:
    start = utterance.index(value)
    return {"kind": kind, "value": value, "source_start": start, "source_end": start + len(value)}


def test_uncovered_spans_separate_hard_restrictions_from_named_subjects() -> None:
    utterance = "rg-example에 있는 컨테이너 앱 목록"
    extraction = resolve_extraction(
        _reading(
            utterance,
            ("restricts", "rg-example"),
            ("names", "컨테이너 앱"),
            ("asks", "목록"),
        ),
        utterance,
    )
    assert extraction is not None
    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.contextual_resources",
            targets=[_target(utterance, "resource_group", "rg-example")],
            requested_facets=["resource_collection", "list"],
        )
    )

    assert uncovered_constraint_spans(proposal, extraction, utterance) == ()
    detached = detached_named_spans(proposal, extraction, utterance)
    assert [utterance[span.start : span.end] for span in detached] == ["컨테이너 앱"]


def test_an_omitted_state_restriction_is_repaired_with_only_its_span() -> None:
    state = _target(_STATE, "resource_state_filter", "실행 중인")
    vm = _target(_STATE, "resource_type_filter", "VM")
    model = _SequenceModel(
        [
            _proposal(
                primary_intent="query.contextual_resources",
                targets=[vm],
                requested_facets=["resource_collection", "list"],
            ),
            _proposal(
                primary_intent="query.contextual_resources",
                targets=[state, vm],
                requested_facets=["resource_collection", "list", "current_state"],
            ),
        ]
    )
    coverage = _coverage(_STATE, _reading(_STATE, ("restricts", "실행 중인"), ("names", "VM")))

    result = _boundary(model).judge(
        utterance=_STATE,
        context=(),
        capabilities=({"kind": "function_type", "name": "query.contextual_resources"},),
        coverage=coverage,
    )

    assert result.accepted is True
    assert result.proposal is not None
    assert [target.kind for target in result.proposal.targets] == [
        "resource_state_filter",
        "resource_type_filter",
    ]
    assert model.schema_repairs[1] == (
        {
            "location": "utterance[0:5]",
            "type": "value_error",
            "reason": "semantic proposal omits a stated constraint",
            "quote": "실행 중인",
            "required": "실행 중인 | VM",
        },
    )


def test_a_restriction_no_repair_copies_holds_instead_of_answering() -> None:
    listing = _proposal(
        primary_intent="query.contextual_resources",
        targets=[_target(_STATE, "resource_type_filter", "VM")],
        requested_facets=["resource_collection", "list"],
    )
    model = _SequenceModel([listing, listing, listing])
    coverage = _coverage(_STATE, _reading(_STATE, ("restricts", "실행 중인"), ("names", "VM")))

    result = _boundary(model).judge(
        utterance=_STATE,
        context=(),
        capabilities=({"kind": "function_type", "name": "query.contextual_resources"},),
        coverage=coverage,
    )

    assert result.accepted is False
    assert result.receipt.reason_code == UNCOVERED_CONSTRAINT_CODE
    assert model.calls == 3


@pytest.mark.parametrize(
    ("utterance", "target", "reading"),
    (
        (
            "bori 관련 리소스 보여줘",
            ("resource_name_filter", "bori"),
            (("restricts", "bori"), ("relates", "관련"), ("names", "리소스")),
        ),
        ("리소스 목록 보여줘", None, (("names", "리소스"), ("asks", "목록"))),
    ),
)
def test_relation_words_and_named_subjects_never_force_a_repair(
    utterance: str,
    target: tuple[str, str] | None,
    reading: tuple[tuple[str, str], ...],
) -> None:
    listing = _proposal(
        primary_intent="query.contextual_resources",
        targets=[] if target is None else [_target(utterance, *target)],
        requested_facets=["resource_collection", "list"],
    )
    model = _SequenceModel([listing])

    result = _boundary(model).judge(
        utterance=utterance,
        context=(),
        capabilities=({"kind": "function_type", "name": "query.contextual_resources"},),
        coverage=_coverage(utterance, _reading(utterance, *reading)),
    )

    assert result.accepted is True
    assert model.calls == 1


def test_a_kind_word_touching_a_copied_group_is_that_groups_head_word() -> None:
    utterance = "rg-example 리소스 그룹에는 어떤 리소스가 있어?"
    extraction = resolve_extraction(
        _reading(
            utterance,
            ("names", "rg-example"),
            ("names", "리소스 그룹"),
            ("names", "리소스가"),
        ),
        utterance,
    )
    assert extraction is not None
    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.contextual_resources",
            targets=[_target(utterance, "resource_group", "rg-example")],
            requested_facets=["resource_collection", "list"],
        )
    )

    detached = detached_named_spans(proposal, extraction, utterance)

    assert [utterance[span.start : span.end] for span in detached] == ["리소스가"]


def test_an_unavailable_reading_reviews_nothing() -> None:
    model = _SequenceModel(
        [
            _proposal(
                primary_intent="query.contextual_resources",
                targets=[_target(_STATE, "resource_type_filter", "VM")],
                requested_facets=["resource_collection", "list"],
            )
        ]
    )

    result = _boundary(model).judge(
        utterance=_STATE,
        context=(),
        capabilities=({"kind": "function_type", "name": "query.contextual_resources"},),
        coverage=_coverage(_STATE, None),
    )

    assert result.accepted is True
    assert model.calls == 1


def test_only_a_target_sharing_the_quote_covers_a_restriction() -> None:
    utterance = "rg-example에 있는 VM"
    extraction = resolve_extraction(
        _reading(utterance, ("restricts", "rg-example에 있는")), utterance
    )
    assert extraction is not None
    group = SemanticTarget(kind="resource_group", value="rg-example", source_start=0, source_end=10)
    vm = SemanticTarget(kind="resource_type_filter", value="VM", source_start=15, source_end=17)

    def proposal(*targets: SemanticTarget) -> SemanticJudgmentProposal:
        return SemanticJudgmentProposal.model_validate(
            _proposal(
                primary_intent="query.contextual_resources",
                targets=[target.model_dump(mode="json") for target in targets],
                requested_facets=["resource_collection", "list"],
            )
        )

    assert uncovered_constraint_spans(proposal(group, vm), extraction, utterance) == ()
    hard = uncovered_constraint_spans(proposal(vm), extraction, utterance)
    assert [utterance[span.start : span.end] for span in hard] == ["rg-example에 있는"]


class _UncoveredBoundary:
    def __init__(self) -> None:
        self.coverage: object | None = None

    def preflight(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(observations=(), attempted=False, failure_kind=None, proposal=None)

    def judge(self, **kwargs: Any) -> Any:
        self.coverage = kwargs.get("coverage")
        return SimpleNamespace(
            accepted=False,
            observations=(),
            proposal=None,
            receipt=SimpleNamespace(
                disposition=SemanticJudgmentDisposition.MALFORMED,
                tier=SimpleNamespace(value="t1"),
                reason_code=UNCOVERED_CONSTRAINT_CODE,
            ),
        )


class _Review:
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []

    def start(self, *, utterance: str, locale: str) -> object:
        self.started.append((utterance, locale))
        return "reading"


def test_the_planner_holds_a_turn_whose_constraint_stayed_uncovered() -> None:
    manifest, _definition = _typed_fixture(groups=(_VM_GROUP,))
    boundary = _UncoveredBoundary()
    review = _Review()
    service = SemanticPlanningService(
        model=_Model(frame=None, plan=None),
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        now=lambda: NOW,
        semantic_judgment=boundary,
        coverage_review=review,  # type: ignore[arg-type]
    )

    outcome = service.plan(
        utterance=_STATE,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale="ko",
    )

    assert review.started == [(_STATE, "ko")]
    assert boundary.coverage == "reading"
    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == UNCOVERED_CONSTRAINT_CODE
    assert outcome.plan is None


@pytest.mark.parametrize(
    ("canonical", "expected"),
    (("resource_state.running", False), (None, True), ("resource_state.invented", True)),
)
def test_state_collections_need_a_second_tier_only_for_ungrounded_states(
    canonical: str | None,
    expected: bool,
) -> None:
    state = _target(_STATE, "resource_state_filter", "실행 중인")
    state["canonical_value"] = canonical
    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.resource_state_inventory",
            targets=[state, _target(_STATE, "resource_type_filter", "VM")],
            requested_facets=["resource_collection", "list", "current_state"],
        )
    )

    assert requires_independent_review(proposal) is expected


def test_a_state_collection_without_a_typed_state_still_needs_review() -> None:
    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.resource_state_inventory",
            targets=[_target(_STATE, "resource_type_filter", "VM")],
            requested_facets=["resource_collection", "list", "current_state"],
        )
    )

    assert requires_independent_review(proposal) is True


def test_a_reviewed_name_filter_facet_without_any_operand_is_dropped() -> None:
    utterance = "키 볼트 목록"
    vault = _target(utterance, "resource_type_filter", "키 볼트")
    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.contextual_resources",
            targets=[vault],
            requested_facets=["resource_collection", "list", "name_filter"],
        )
    )
    reviewed = _coverage(utterance, _reading(utterance, ("names", "키 볼트"), ("asks", "목록")))

    settled = settled_proposal(reviewed, proposal)

    assert settled.requested_facets == ("resource_collection", "list")
    assert settled_proposal(None, proposal) is proposal
    assert settled_proposal(_coverage(utterance, None), proposal) is proposal
    named = proposal.model_copy(
        update={
            "targets": (
                *proposal.targets,
                SemanticTarget.model_validate(_target(utterance, "resource_name_filter", "볼트")),
            )
        }
    )
    assert settled_proposal(reviewed, named) is named


@pytest.mark.parametrize(
    ("utterance", "targets", "negation"),
    (
        (
            "실행 중인 VM만 보여줘",
            (("resource_state_filter", "실행 중인"), ("resource_type_filter", "VM")),
            "만",
        ),
        (
            "list only running VMs",
            (("resource_state_filter", "running"), ("resource_type_filter", "VMs")),
            "only",
        ),
        (
            "show VMs that are not running",
            (("resource_type_filter", "VMs"), ("resource_state_exclusion_filter", "running")),
            "not",
        ),
    ),
)
def test_a_negation_word_touching_its_copied_operand_is_covered(
    utterance: str,
    targets: tuple[tuple[str, str], ...],
    negation: str,
) -> None:
    extraction = resolve_extraction(_reading(utterance, ("negates", negation)), utterance)
    assert extraction is not None
    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.contextual_resources",
            targets=[_target(utterance, kind, value) for kind, value in targets],
            requested_facets=["resource_collection", "list"],
        )
    )

    assert uncovered_constraint_spans(proposal, extraction, utterance) == ()


def test_a_negation_standing_apart_from_every_operand_stays_uncovered() -> None:
    utterance = "VM 목록, 단 실행 중이 아닌 것"
    extraction = resolve_extraction(_reading(utterance, ("negates", "아닌")), utterance)
    assert extraction is not None
    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.contextual_resources",
            targets=[_target(utterance, "resource_type_filter", "VM")],
            requested_facets=["resource_collection", "list"],
        )
    )

    assert len(uncovered_constraint_spans(proposal, extraction, utterance)) == 1


def test_an_uncovered_constraint_keeps_its_hold_when_later_attempts_fail_otherwise() -> None:
    listing = _proposal(
        primary_intent="query.contextual_resources",
        targets=[_target(_STATE, "resource_type_filter", "VM")],
        requested_facets=["resource_collection", "list"],
    )
    model = _SequenceModel([listing, {"primary_intent": 7}, {"primary_intent": 7}])
    coverage = _coverage(_STATE, _reading(_STATE, ("restricts", "실행 중인"), ("names", "VM")))

    result = _boundary(model).judge(
        utterance=_STATE,
        context=(),
        capabilities=({"kind": "function_type", "name": "query.contextual_resources"},),
        coverage=coverage,
    )

    assert result.accepted is False
    assert result.receipt.reason_code == UNCOVERED_CONSTRAINT_CODE


def test_rejection_logs_keep_only_bounded_feedback_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from fdai.core.conversation.semantic_judgment_schema_repair import log_rejection
    from pydantic import BaseModel, ValidationError

    class _Strict(BaseModel):
        value: int

    try:
        _Strict.model_validate({"value": "x"})
    except ValidationError as exc:
        error = exc
    logger = logging.getLogger("coverage-log-test")
    with caplog.at_level(logging.WARNING, logger="coverage-log-test"):
        log_rejection(
            error,
            validation_reason=(
                {
                    "location": "utterance[0:5]",
                    "type": "value_error",
                    "reason": "semantic proposal omits a stated constraint",
                    "quote": "실행 중인",
                    "required": "실행 중인 | VM",
                },
            ),
            logger=logger,
        )

    logged = caplog.records[-1].__dict__["validation_reason"]
    assert "실행" not in logged
    assert "utterance[0:5]" in logged
