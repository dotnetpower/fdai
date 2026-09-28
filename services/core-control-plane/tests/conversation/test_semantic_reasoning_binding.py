"""Two-phase anchor binding reads exact identities before compilation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_binding import (
    AnchorBinding,
    AnchorBindingReceipt,
    AnchorOutcome,
    GatewayAnchorResolver,
    bind_anchors,
    surface_extensions,
)
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    fixture_anchors,
    fixture_gateway,
    plan_verifier,
    production_manifest,
    span,
)


def _form(utterance: str, anchor: str, form: str = "name") -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": form, "domain": "instance", "span": span(utterance, anchor)}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": span(utterance, "depend on"),
                },
                "cue": span(utterance, "Which"),
                "confidence": 0.9,
            }
        ],
    }


@pytest.mark.parametrize(
    ("text", "form"),
    (("sql-app", "name"), ("sql-app", "identifier"), ("sql-1", "identifier"), ("sql-1", "name")),
)
async def test_a_name_or_identifier_binds_the_same_exact_object(text: str, form: str) -> None:
    utterance = f"Which resources depend on {text}?"

    receipt = await fixture_anchors(admitted(_form(utterance, text, form), utterance))

    (binding,) = receipt.bindings
    assert (binding.outcome, binding.object_id) == (AnchorOutcome.BOUND, "sql-1")
    assert binding.source_generation == "fixture-generation"


async def test_an_absent_anchor_clarifies_instead_of_reading_text() -> None:
    utterance = "Which resources depend on sql-missing?"
    admission = admitted(_form(utterance, "sql-missing"), utterance)

    receipt = await fixture_anchors(admission)
    goal = _compile(admission, utterance, receipt).goals[0]

    assert receipt.bindings[0].outcome is AnchorOutcome.ABSENT
    assert goal.status is GoalStatus.CLARIFY
    assert goal.reasons == ("anchor_not_found:m1",)


@pytest.mark.parametrize(
    ("binding", "status", "reason"),
    (
        (
            AnchorBinding("m1", AnchorOutcome.AMBIGUOUS, candidates=("a", "b")),
            GoalStatus.CLARIFY,
            "anchor_ambiguous:m1",
        ),
        (
            AnchorBinding("m1", AnchorOutcome.INCOMPLETE),
            GoalStatus.UNSUPPORTED,
            "anchor_resolution_incomplete",
        ),
        (
            AnchorBinding("m1", AnchorOutcome.UNAVAILABLE),
            GoalStatus.UNSUPPORTED,
            "anchor_binding_unavailable",
        ),
    ),
)
def test_unbound_anchors_never_compile_a_read(
    binding: AnchorBinding, status: GoalStatus, reason: str
) -> None:
    utterance = "Which resources depend on sql-app?"
    admission = admitted(_form(utterance, "sql-app"), utterance)

    goal = _compile(admission, utterance, AnchorBindingReceipt((binding,))).goals[0]

    assert goal.status is status
    assert goal.reasons == (reason,)
    assert goal.batches == ()


async def test_without_a_resolver_every_anchor_is_unavailable() -> None:
    utterance = "Which resources depend on sql-app?"

    receipt = await bind_anchors(admitted(_form(utterance, "sql-app"), utterance), None)

    assert [item.outcome for item in receipt.bindings] == [AnchorOutcome.UNAVAILABLE]


def _compile(admission: Any, utterance: str, anchors: AnchorBindingReceipt) -> Any:
    return compile_question_form(
        admission,
        concepts=concepts(),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=anchors,
    )


def test_surface_extensions_cover_every_longer_form_within_the_token() -> None:
    utterance = "Is (rg-app) up?"
    start = utterance.index("rg-app")

    forms = surface_extensions(utterance, start, start + len("rg-app"))

    assert set(forms) == {"(rg-app", "rg-app)", "(rg-app)"}
    assert surface_extensions("Is rg-app up?", 3, 9) == ()


async def test_a_longer_exact_name_in_the_same_token_makes_the_anchor_ambiguous() -> None:
    utterance = "What depends on vm-app-01?"
    start = utterance.index("vm-app")
    resolver = GatewayAnchorResolver(
        await fixture_gateway(),
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
        ),
        purpose=PURPOSE,
        as_of=NOW,
    )

    binding = await resolver.resolve(
        "m1", "vm-app", surface_extensions(utterance, start, start + len("vm-app"))
    )

    assert binding.outcome is AnchorOutcome.AMBIGUOUS
    assert binding.candidates == ("vm-1",)


async def test_a_particle_after_a_name_still_binds_the_exact_name() -> None:
    utterance = "sql-app에 의존하는 리소스는?"
    form = {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": span(utterance, "sql-app")}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": span(utterance, "의존하는"),
                },
                "cue": span(utterance, "리소스는"),
                "confidence": 0.9,
            }
        ],
    }
    resolver = GatewayAnchorResolver(
        await fixture_gateway(),
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
        ),
        purpose=PURPOSE,
        as_of=NOW,
    )

    receipt = await bind_anchors(admitted(form, utterance), resolver, utterance=utterance)

    assert [(item.outcome, item.object_id) for item in receipt.bindings] == [
        (AnchorOutcome.BOUND, "sql-1")
    ]


async def test_too_many_longer_forms_leave_the_anchor_incomplete() -> None:
    resolver = GatewayAnchorResolver(
        await fixture_gateway(),
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
        ),
        purpose=PURPOSE,
        as_of=NOW,
    )
    extensions = tuple(f"sql-app{'가' * 40}{index}" for index in range(900))

    binding = await resolver.resolve("m1", "sql-app", extensions)

    assert binding.outcome is AnchorOutcome.INCOMPLETE


async def test_a_differently_cased_name_binds_the_same_object() -> None:
    utterance = "Which resources depend on SQL-App?"

    receipt = await fixture_anchors(admitted(_form(utterance, "SQL-App"), utterance))

    (binding,) = receipt.bindings
    assert (binding.outcome, binding.object_id) == (AnchorOutcome.BOUND, "sql-1")


class _Spy:
    """Record every read and answer the name read with the given objects."""

    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = names
        self.definitions: list[Any] = []

    async def materialize(self, definition: Any, *, projection_request: Any) -> Any:
        from types import SimpleNamespace

        self.definitions.append(definition)
        (predicate,) = definition.predicates
        objects = (
            [SimpleNamespace(id=f"object-{index}") for index, _ in enumerate(self.names)]
            if predicate.property == "name"
            else []
        )
        return SimpleNamespace(
            receipt=SimpleNamespace(complete=True, source_generation="spy-generation"),
            materialization=SimpleNamespace(graph=SimpleNamespace(objects=objects)),
        )


async def test_names_that_differ_only_in_case_are_ambiguous_and_reads_stay_bounded() -> None:
    from fdai.core.conversation.semantic_reasoning_binding import ANCHOR_CANDIDATE_LIMIT
    from fdai.core.ontology_platform import ObjectPredicateOperator

    request = ProjectionRequest(
        caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
    )
    spy = _Spy(("app-1", "App-1"))
    resolver = GatewayAnchorResolver(
        spy,  # type: ignore[arg-type]
        projection_request=request,
        purpose=PURPOSE,
        as_of=NOW,
    )

    binding = await resolver.resolve("m1", "APP-1")

    assert binding.outcome is AnchorOutcome.AMBIGUOUS
    assert binding.candidates == ("object-0", "object-1")
    # Every read filters in the store by one identity predicate within the candidate limit.
    assert [
        (item.predicates[0].property, item.predicates[0].operator) for item in spy.definitions
    ] == [
        ("id", ObjectPredicateOperator.EQUALS),
        ("name", ObjectPredicateOperator.EQUALS_IGNORE_CASE),
    ]
    assert all(item.limit == ANCHOR_CANDIDATE_LIMIT for item in spy.definitions)


async def test_a_resolver_reads_at_the_gateway_clock_and_names_a_stale_read() -> None:
    gateway = await fixture_gateway()
    request = ProjectionRequest(
        caller_role=CeilingRole.READER, declared_purposes=frozenset({PURPOSE})
    )
    reads: list[None] = []

    def clock() -> Any:
        reads.append(None)
        return NOW

    live = GatewayAnchorResolver(gateway, projection_request=request, purpose=PURPOSE, as_of=clock)
    stale = GatewayAnchorResolver(
        gateway, projection_request=request, purpose=PURPOSE, as_of=NOW - timedelta(minutes=1)
    )

    bound = await live.resolve("m1", "sql-app")
    unbound = await stale.resolve("m1", "sql-app")

    assert bound.outcome is AnchorOutcome.BOUND and bound.object_id == "sql-1"
    assert len(reads) >= 1
    assert unbound.outcome is AnchorOutcome.UNAVAILABLE
    assert unbound.reason == "as_of_stale"
    assert (
        AnchorBindingReceipt((unbound,)).digest
        != AnchorBindingReceipt((AnchorBinding("m1", AnchorOutcome.UNAVAILABLE),)).digest
    )
