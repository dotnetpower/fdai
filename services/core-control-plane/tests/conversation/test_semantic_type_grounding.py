"""Unbound subtype filters ground by closed choice where two blind choosers agree."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Iterator, Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.conversation.semantic_judgment_coverage import JudgmentCoverage
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
from fdai.core.conversation.semantic_planning_value_filters import (
    resource_type_filters_are_bound,
)
from fdai.core.conversation.semantic_reasoning_concepts import ConceptShard
from fdai.core.conversation.semantic_type_grounding import (
    ResourceTypeGrounding,
    type_selection_plan,
    unbound_type_filter_values,
    with_grounded_types,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanVerifier
from fdai.core.ontology_platform.property_values import PropertyValueGroup
from fdai_service_contracts.ontology_query import QueryNodeKind
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal, SemanticTarget

from tests.conversation.test_semantic_planning import (
    _RESOURCE_GROUP_GROUP,
    _VM_GROUP,
    NOW,
    _JudgmentBoundary,
    _ManifestProvider,
    _Model,
    _typed_fixture,
)

_CONTAINER_APP_GROUP = PropertyValueGroup(
    id="compute-container-app",
    values=("compute.container-app",),
    terms=("container app", "container apps"),
)
_UTTERANCE = "컨테이너 앱 목록"
_PHRASE = "컨테이너 앱"


class _Choosers:
    """Two blind choosers answering through the closed shard contract."""

    def __init__(self, primary: str | None, second: str | None) -> None:
        self._picks = {False: primary, True: second}
        self.calls: list[tuple[bool, int]] = []

    async def choose_concepts(
        self,
        *,
        utterance: str,
        mentions: tuple[dict[str, Any], ...],
        shard: ConceptShard,
        second: bool = False,
    ) -> Mapping[str, Any] | None:
        self.calls.append((second, shard.index))
        pick = self._picks[second]
        present = {candidate.id for candidate in shard.candidates}
        return {
            "shard_digest": shard.digest,
            "choices": [
                {"mention": item["mention"], "candidate_ids": [pick] if pick in present else []}
                for item in mentions
            ],
        }


@pytest.fixture
def owner_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()


def _judgment(*targets: SemanticTarget) -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal(
        primary_intent="query.contextual_resources",
        targets=targets,
        requested_facets=("resource_collection", "list"),
        confidence=0.97,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )


def _phrase_target() -> SemanticTarget:
    start = _UTTERANCE.index(_PHRASE)
    return SemanticTarget(
        kind="resource_type_filter",
        value=_PHRASE,
        source_start=start,
        source_end=start + len(_PHRASE),
    )


def _plan(
    choosers: _Choosers,
    owner_loop: asyncio.AbstractEventLoop,
    *,
    compiled_answers: Any = None,
) -> Any:
    manifest, _definition = _typed_fixture(groups=(_CONTAINER_APP_GROUP, _VM_GROUP))
    service = SemanticPlanningService(
        model=_Model(frame=None, plan=None),
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(
                QueryNodeKind.OBJECT_SET,
                QueryNodeKind.RELATIONSHIP_TRAVERSAL,
                QueryNodeKind.FUNCTION,
            )
        ),
        now=lambda: NOW,
        semantic_judgment=_JudgmentBoundary(_judgment(_phrase_target())),
        type_grounding=ResourceTypeGrounding(chooser=choosers, owner_loop=owner_loop),
        compiled_answers=compiled_answers,
    )
    return service.plan(
        utterance=_UTTERANCE,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )


def test_agreed_closed_choice_binds_an_unstated_subtype_phrase(
    owner_loop: asyncio.AbstractEventLoop,
) -> None:
    choosers = _Choosers("group:compute-container-app", "group:compute-container-app")

    outcome = _plan(choosers, owner_loop)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    predicates = outcome.plan.nodes[0].arguments["definition"]["predicates"]
    assert {"property": "type", "operator": "equals", "equals": "compute.container-app"} in (
        predicates
    )
    # Every shard was presented to both blind choosers exactly once.
    assert sorted(choosers.calls) == [(False, 0), (True, 0)]


def test_typed_only_never_pays_for_unused_legacy_grounding(
    owner_loop: asyncio.AbstractEventLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "fdai.core.conversation.semantic_planning.start_compiled_answer",
        lambda *args, **kwargs: None,
    )
    choosers = _Choosers("group:compute-container-app", "group:compute-container-app")
    compiled_answers = SimpleNamespace(typed_only=True, speculative_start=False)
    outcome = _plan(choosers, owner_loop, compiled_answers=compiled_answers)

    assert choosers.calls == []
    assert outcome.plan is None
    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_reading_unavailable"


@pytest.mark.parametrize(
    ("primary", "second"),
    (
        ("group:compute-container-app", "group:compute-vm"),
        ("group:compute-container-app", None),
        ("any:resource", "any:resource"),
    ),
)
def test_disagreement_or_no_type_leaves_the_phrase_unbound(
    owner_loop: asyncio.AbstractEventLoop,
    primary: str,
    second: str | None,
) -> None:
    outcome = _plan(_Choosers(primary, second), owner_loop)

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.plan is None


def test_only_unbound_source_grounded_filters_are_grounded() -> None:
    manifest, _definition = _typed_fixture(groups=(_CONTAINER_APP_GROUP, _VM_GROUP))
    utterance = "vm and 컨테이너 앱 목록"
    vm = SemanticTarget(kind="resource_type_filter", value="vm", source_start=0, source_end=2)
    start = utterance.index(_PHRASE)
    phrase = SemanticTarget(
        kind="resource_type_filter",
        value=_PHRASE,
        source_start=start,
        source_end=start + len(_PHRASE),
    )
    misplaced = SemanticTarget(
        kind="resource_type_filter", value="컨테이너", source_start=0, source_end=4
    )

    values = unbound_type_filter_values(
        _judgment(vm, phrase, misplaced),
        utterance=utterance,
        descriptors=manifest.descriptors,
    )

    assert values == (_PHRASE,)


def test_injected_binding_is_limited_to_declared_values() -> None:
    manifest, _definition = _typed_fixture(groups=(_CONTAINER_APP_GROUP,))

    grounded = with_grounded_types(
        manifest.descriptors,
        {_PHRASE: ("compute.container-app", "not-a-declared-type")},
    )

    assert resource_type_filters_are_bound((_PHRASE,), grounded)
    assert not resource_type_filters_are_bound((_PHRASE,), manifest.descriptors)
    resource = next(item for item in grounded if item.get("name") == "Resource")
    turn_groups = [
        group
        for group in resource["properties"]["type"]["value_groups"]
        if str(group["id"]).startswith("turn-grounded:")
    ]
    assert turn_groups == [
        {
            "id": turn_groups[0]["id"],
            "values": ["compute.container-app"],
            "terms": [_PHRASE],
        }
    ]
    # The shared manifest descriptors are never mutated.
    original = next(item for item in manifest.descriptors if item.get("name") == "Resource")
    assert all(
        not str(group["id"]).startswith("turn-grounded:")
        for group in original["properties"]["type"]["value_groups"]
    )


def test_every_catalog_candidate_is_presented_exactly_once() -> None:
    manifest, _definition = _typed_fixture(groups=(_CONTAINER_APP_GROUP, _VM_GROUP))

    plan = type_selection_plan((_PHRASE,), manifest.descriptors, max_shard_bytes=400)

    assert plan is not None
    presented = [
        candidate.id for request in plan.requests for candidate in request.shard.candidates
    ]
    assert len(presented) == len(set(presented))
    assert len(presented) == sum(plan.catalog_sizes.values())
    assert len(plan.requests) > 1


class _ReadingReview:
    """Start a blind reading that already quoted the question's constraints."""

    def __init__(self, reading: dict[str, Any]) -> None:
        self._reading = reading

    def start(self, *, utterance: str, locale: str) -> JudgmentCoverage:
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        future.set_result(self._reading)
        return JudgmentCoverage(future, utterance, 1.0)


def test_a_detached_named_subtype_the_judgment_omitted_becomes_its_filter(
    owner_loop: asyncio.AbstractEventLoop,
) -> None:
    utterance = "rg-example에 있는 컨테이너 앱 목록"
    manifest, _definition = _typed_fixture(
        groups=(_CONTAINER_APP_GROUP, _RESOURCE_GROUP_GROUP),
        extra_values=("authorization.role-assignment",),
        include_parent_id=True,
    )
    judgment = SemanticJudgmentProposal(
        primary_intent="query.contextual_resources",
        targets=(
            SemanticTarget(
                kind="resource_group", value="rg-example", source_start=0, source_end=10
            ),
        ),
        requested_facets=("resource_collection", "list"),
        confidence=0.97,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )
    choosers = _Choosers("group:compute-container-app", "group:compute-container-app")
    service = SemanticPlanningService(
        model=_Model(frame=None, plan=None),
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(
                QueryNodeKind.OBJECT_SET,
                QueryNodeKind.RELATIONSHIP_TRAVERSAL,
                QueryNodeKind.FUNCTION,
            )
        ),
        now=lambda: NOW,
        semantic_judgment=_JudgmentBoundary(judgment),
        type_grounding=ResourceTypeGrounding(chooser=choosers, owner_loop=owner_loop),
        coverage_review=_ReadingReview(  # type: ignore[arg-type]
            {
                "constraints": [
                    {"quote": {"text": "rg-example에 있는", "occurrence": 1}, "role": "restricts"},
                    {"quote": {"text": "컨테이너 앱", "occurrence": 1}, "role": "names"},
                    {"quote": {"text": "목록", "occurrence": 1}, "role": "asks"},
                ],
                "literals": [],
            }
        ),
    )

    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    _anchor, members = outcome.plan.nodes
    assert {
        "property": "type",
        "operator": "equals",
        "equals": "compute.container-app",
    } in members.arguments["endpoint_predicates"]


def test_an_omitted_subtype_a_reviewed_entry_states_binds_without_a_turn_group(
    owner_loop: asyncio.AbstractEventLoop,
) -> None:
    utterance = "fdai 관련 리소스 그룹 목록"
    manifest, _definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    judgment = SemanticJudgmentProposal(
        primary_intent="query.contextual_resources",
        targets=(
            SemanticTarget(kind="resource_name_filter", value="fdai", source_start=0, source_end=4),
        ),
        requested_facets=("resource_collection", "list", "name_filter"),
        confidence=0.97,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )
    service = SemanticPlanningService(
        model=_Model(frame=None, plan=None),
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        now=lambda: NOW,
        semantic_judgment=_JudgmentBoundary(judgment),
        type_grounding=ResourceTypeGrounding(
            chooser=_Choosers("group:resource-group", "group:resource-group"),
            owner_loop=owner_loop,
        ),
        coverage_review=_ReadingReview(  # type: ignore[arg-type]
            {
                "constraints": [
                    {"quote": {"text": "fdai", "occurrence": 1}, "role": "restricts"},
                    {"quote": {"text": "리소스 그룹", "occurrence": 1}, "role": "names"},
                    {"quote": {"text": "목록", "occurrence": 1}, "role": "asks"},
                ],
                "literals": [],
            }
        ),
    )

    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    predicates = outcome.plan.nodes[0].arguments["definition"]["predicates"]
    assert {"property": "name", "operator": "contains", "equals": "fdai"} in predicates
    assert {"property": "type", "operator": "equals", "equals": "resource-group"} in predicates
