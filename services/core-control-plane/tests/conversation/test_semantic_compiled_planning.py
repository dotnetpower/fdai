"""The planner answers from a released compilation only after the current path's gates."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fdai.core.conversation.semantic_judgment_coverage import UNCOVERED_CONSTRAINT_CODE
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import (
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from fdai.core.conversation.semantic_reasoning_form import SourceSpan
from fdai.core.conversation.semantic_reasoning_review import (
    ConstraintExtraction,
    ConstraintRole,
    ExtractedConstraint,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanVerifier
from fdai_service_contracts.ontology_query import QueryNodeKind
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
)

from tests.conversation.test_semantic_judgment import _proposal
from tests.conversation.test_semantic_planning import (
    _VM_GROUP,
    NOW,
    _ManifestProvider,
    _Model,
    _typed_fixture,
)

_UTTERANCE = "VM 목록 보여줘"
_COMPILED = SemanticPlanningOutcome(
    disposition=SemanticPlanningDisposition.UNSUPPORTED,
    reason="compiled_answer_marker",
)


class _Ticket:
    def __init__(
        self,
        result: SemanticPlanningOutcome | None,
        veto: SemanticPlanningOutcome | None = None,
    ) -> None:
        self.result = result
        self.veto_result = veto
        self.vetoed_sources: list[str] = []
        self.vetoed_plans: list[Any] = []
        self.consumed = False
        self.cancelled = False
        self.typed_only = False
        self.decision: str | None = None
        self.details: tuple[str, ...] = ()

    def outcome(self, *, manifest_digest: str, observations: list[Any]) -> Any:
        self.consumed = True
        observations.append(SimpleNamespace(model="form-model", usage=None, trace_call={}))
        return self.result

    def veto(self, plan_source: str, *, manifest_digest: str, plan: Any = None) -> Any:
        self.vetoed_sources.append(plan_source)
        self.vetoed_plans.append(plan)
        return self.veto_result

    def cancel(self) -> None:
        if not self.consumed:
            self.cancelled = True


class _Path:
    def __init__(
        self, result: SemanticPlanningOutcome | None = _COMPILED, *, typed_only: bool = False
    ) -> None:
        self.ticket = _Ticket(result)
        self.ticket.typed_only = typed_only
        self.typed_only = typed_only
        self.starts: list[dict[str, Any]] = []

    def start(self, **arguments: Any) -> _Ticket:
        self.starts.append(arguments)
        return self.ticket


class _Boundary:
    def __init__(
        self,
        disposition: SemanticJudgmentDisposition,
        *,
        proposal: SemanticJudgmentProposal | None = None,
        reason_code: str = "accepted",
    ) -> None:
        self._disposition = disposition
        self._proposal = proposal
        self._reason_code = reason_code

    def preflight(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(observations=(), attempted=False, failure_kind=None, proposal=None)

    def judge(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            accepted=self._disposition is SemanticJudgmentDisposition.ACCEPTED,
            observations=(),
            proposal=self._proposal,
            receipt=SimpleNamespace(
                disposition=self._disposition,
                tier=SimpleNamespace(value="t1"),
                reason_code=self._reason_code,
            ),
        )


def _accepted() -> SemanticJudgmentProposal:
    start = _UTTERANCE.index("VM")
    return SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.contextual_resources",
            targets=[
                {
                    "kind": "resource_type_filter",
                    "value": "VM",
                    "source_start": start,
                    "source_end": start + 2,
                }
            ],
            requested_facets=["resource_collection", "list"],
        )
    )


def _plan(boundary: _Boundary, path: _Path, **arguments: Any) -> tuple[Any, _Model]:
    manifest, _definition = _typed_fixture(groups=(_VM_GROUP,))
    model = _Model(frame=None, plan=None)  # type: ignore[arg-type]
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        now=lambda: NOW,
        semantic_judgment=boundary,  # type: ignore[arg-type]
        compiled_answers=path,  # type: ignore[arg-type]
    )
    outcome = service.plan(
        utterance=_UTTERANCE,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale="ko",
        **arguments,
    )
    return outcome, model


def test_a_released_compilation_answers_before_the_frame_model_runs() -> None:
    path = _Path()
    outcome, model = _plan(
        _Boundary(SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()), path
    )

    assert outcome.reason == "compiled_answer_marker"
    assert model.frame_calls == 0 and model.plan_calls == 0
    assert path.ticket.consumed and not path.ticket.cancelled
    assert [item.model for item in outcome.model_observations] == ["form-model"]
    assert path.starts[0]["utterance"] == _UTTERANCE


def test_a_released_compilation_replaces_an_uncovered_constraint_hold() -> None:
    path = _Path()
    outcome, _model = _plan(
        _Boundary(SemanticJudgmentDisposition.MALFORMED, reason_code=UNCOVERED_CONSTRAINT_CODE),
        path,
    )

    assert outcome.reason == "compiled_answer_marker"
    declined = _Path(result=None)
    held, _model = _plan(
        _Boundary(SemanticJudgmentDisposition.MALFORMED, reason_code=UNCOVERED_CONSTRAINT_CODE),
        declined,
    )
    assert held.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert held.reason == UNCOVERED_CONSTRAINT_CODE


def test_an_ambiguous_judgment_ends_with_its_clarification_and_cancels_the_path() -> None:
    ambiguous = _accepted().model_copy(
        update={"ambiguous": True, "clarification": "Which VM scope should I read?"}
    )
    path = _Path()
    outcome, model = _plan(
        _Boundary(SemanticJudgmentDisposition.CLARIFICATION, proposal=ambiguous), path
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "Which VM scope should I read?"
    assert model.frame_calls == 0
    assert path.ticket.cancelled and not path.ticket.consumed


def test_a_turn_that_needs_document_evidence_never_starts_the_form_path() -> None:
    path = _Path()
    _outcome, _model = _plan(
        _Boundary(SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()),
        path,
        required_document_evidence=True,
    )
    assert path.starts == []


def test_a_released_unsupported_reading_holds_the_word_recovered_plan() -> None:
    vetoed = SemanticPlanningOutcome(
        disposition=SemanticPlanningDisposition.UNSUPPORTED,
        reason="semantic_stated_constraint_unsupported",
    )
    path = _Path(result=None)
    path.ticket.veto_result = vetoed
    outcome, _model = _plan(
        _Boundary(SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()), path
    )

    # The recovered plan was built and verified, then held because the reviewed reading
    # of the same question states an atom that plan never reads.
    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_stated_constraint_unsupported"
    assert [item.model for item in outcome.model_observations] == ["form-model"]
    assert path.ticket.vetoed_sources == ["server_stated_filter"]

    kept = _Path(result=None)
    answered, _model = _plan(
        _Boundary(SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()), kept
    )
    assert answered.disposition is SemanticPlanningDisposition.PLANNED
    assert kept.ticket.vetoed_sources == ["server_stated_filter"]


class _Reading:
    """A blind reading that has already arrived, as the judgment's coverage review holds it."""

    def __init__(self, *roles: str) -> None:
        self.extraction = ConstraintExtraction(
            constraints=tuple(
                ExtractedConstraint(quote=SourceSpan(start=0, end=2), role=ConstraintRole(role))
                for role in roles
            )
        )

    def settled_reading(self) -> ConstraintExtraction:
        return self.extraction


class _CoverageReview:
    def __init__(self, reading: _Reading) -> None:
        self._reading = reading

    def start(self, *, utterance: str, locale: str) -> _Reading:
        return self._reading


def _plan_with_reading(*roles: str) -> Any:
    manifest, _definition = _typed_fixture(groups=(_VM_GROUP,))
    service = SemanticPlanningService(
        model=_Model(frame=None, plan=None),  # type: ignore[arg-type]
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        now=lambda: NOW,
        semantic_judgment=_Boundary(  # type: ignore[arg-type]
            SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()
        ),
        coverage_review=_CoverageReview(_Reading(*roles)),  # type: ignore[arg-type]
    )
    return service.plan(
        utterance=_UTTERANCE,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale="ko",
    )


def test_a_stated_grouping_or_relation_holds_a_plan_that_reads_only_a_list() -> None:
    grouped = _plan_with_reading("names", "groups")
    related = _plan_with_reading("names", "relates")
    listed = _plan_with_reading("names", "restricts")

    # The verified list reads neither the grouping nor the relation the blind reading found.
    assert grouped.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert grouped.reason == "semantic_plan_constraint_uncovered"
    assert grouped.hold_details == ("role:groups",)
    assert related.hold_details == ("role:relates",)
    # A restriction stays with the judgment's coverage review, so the list still answers.
    assert listed.disposition is SemanticPlanningDisposition.PLANNED


def test_the_veto_sees_the_plan_the_current_path_verified() -> None:
    path = _Path(result=None)
    outcome, _model = _plan(
        _Boundary(SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()), path
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert path.ticket.vetoed_plans == [outcome.plan]


def test_typed_only_ends_a_declined_read_with_its_decision_and_never_the_legacy_cascade() -> None:
    path = _Path(result=None, typed_only=True)
    path.ticket.decision = "unsupported"
    outcome, model = _plan(
        _Boundary(SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()), path
    )

    # The stated-filter recovery would have answered this list from the judgment's words.
    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_stated_constraint_unsupported"
    assert (model.frame_calls, model.plan_calls) == (0, 0)
    assert path.ticket.vetoed_sources == []

    unverified = _Path(result=None, typed_only=True)
    unverified.ticket.decision = "unverified"
    held, _model = _plan(
        _Boundary(SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()), unverified
    )
    assert held.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert held.reason == "semantic_reading_unverified"


def test_typed_only_holds_a_read_whose_form_path_never_started() -> None:
    path = _Path(result=None, typed_only=True)
    outcome, model = _plan(
        _Boundary(SemanticJudgmentDisposition.ACCEPTED, proposal=_accepted()),
        path,
        required_document_evidence=True,
    )

    assert path.starts == []
    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_reading_unavailable"
    assert (model.frame_calls, model.plan_calls) == (0, 0)


def test_typed_only_still_ends_an_ambiguous_judgment_with_its_clarification() -> None:
    ambiguous = _accepted().model_copy(
        update={"ambiguous": True, "clarification": "Which VM scope should I read?"}
    )
    path = _Path(typed_only=True)
    outcome, _model = _plan(
        _Boundary(SemanticJudgmentDisposition.CLARIFICATION, proposal=ambiguous), path
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert path.ticket.cancelled
