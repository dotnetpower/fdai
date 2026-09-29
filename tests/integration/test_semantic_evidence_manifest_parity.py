"""Seeded Core-to-Operator parity between cited evidence and the terminal evidence manifest.

Each turn crosses the real semantic runtime, query executor, Core processor, projection codec,
Operator ingest, and ``done`` compiler; only the model planner and query data plane are fakes. The
Operator must render exactly the server manifest, cite nothing outside it, and resolve every
manifest reference to a completed receipt. Producer digests must recompute unchanged from the
ingested projection, and Operator ingest enforces the shared ``evidence_digest`` and
``projection_id`` commitments before any terminal event is rendered.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from typing import Any, cast
from uuid import UUID, uuid5

import pytest
from fdai.core.conversation.conversation_preflight_contracts import ConversationPreflightResult
from fdai.core.conversation.intent_graph import build_intent_graph
from fdai.core.conversation.semantic_planning_frame_core import build_semantic_frame
from fdai.core.conversation.semantic_planning_models import (
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal
from fdai.core.ontology_platform import (
    OntologyQueryPlanExecutor,
    QueryNodeHeldError,
    QueryNodeResult,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai_core_service.semantic_turn_processor import SemanticTurnProcessor
from fdai_operator_service.families.conversation.channel_edge.presentation import (
    normalize_terminal_presentation,
)
from fdai_operator_service.families.conversation.channel_edge.renderers import (
    SlackPresentationRenderer,
    TeamsPresentationRenderer,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_done_event_data,
)
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnProjectionConsumer,
)
from fdai_operator_service.postgres_semantic_turn_store import StoredSemanticResult
from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    content_digest,
)
from fdai_service_contracts.semantic_projection import (
    PANTHEON_ASSURANCE_REQUEST_KIND,
    pantheon_assurance_evidence_digest,
    semantic_projection_evidence_digest,
    semantic_projection_id,
)

SEED = 0x0FDA1
TURNS = 1_000
PARTITIONS = 10
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
CATALOG = "sha256:" + "b" * 64
PURPOSE = "operations-review"
AUTHORITIES = (
    EvidenceAuthority.SERVER_INVENTORY_GRAPH,
    EvidenceAuthority.SERVER_METERING,
    EvidenceAuthority.SERVER_SUBSCRIPTION_HEALTH,
    EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
)
PROMPTS = {"en": "Show current operations evidence.", "ko": "현재 운영 근거를 보여 주세요."}
LABELS = ("evidence:inventory", "근거:리소스-상태", "évidence:ünïcødé", "ref:가용성 공백", "e")
VERIFIED = ("answered", "semantic_answer_verified")
INCOMPLETE = ("held", "semantic_evidence_incomplete")
HELD = ("held", "semantic_evidence_held")
EXPECTED = {
    **dict.fromkeys(("verified", "max_refs", "max_ref_chars", "inherited"), VERIFIED),
    "multi_source_authority": VERIFIED,
    "governed_document_citations": ("answered", "semantic_answer_partial"),
    **dict.fromkeys(("overflow_turn", "overflow_goal", "held_overflow", "long_ref"), INCOMPLETE),
    **dict.fromkeys(("unavailable", "failed", "inherited_conflict"), HELD),
    "partial_source": ("answered", "semantic_answer_partial"),
    "empty": ("held", "semantic_evidence_authority_missing"),
    "conflict": ("held", "semantic_evidence_authority_conflict"),
}
OUTCOMES = frozenset({"ok", "incomplete", "held", "failed", "derived_conflict"})
BASE_GENERATED_KINDS = frozenset(EXPECTED) - {
    "governed_document_citations",
    "multi_source_authority",
}


@dataclass(frozen=True, slots=True)
class Node:
    node_id: str
    refs: tuple[str, ...]
    authority: EvidenceAuthority | None
    outcome: str = "ok"
    depends_on: tuple[str, ...] = ()
    authority_inputs: tuple[EvidenceAuthority, ...] = ()
    rows: tuple[Mapping[str, object], ...] | None = None
    kind: QueryNodeKind = QueryNodeKind.OBJECT_SET
    arguments: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"generated node outcome has no handler branch: {self.outcome}")


@dataclass(frozen=True, slots=True)
class Turn:
    index: int
    kind: str
    locale: str
    nodes: tuple[Node, ...]
    authority: EvidenceAuthority
    manifest: tuple[str, ...]
    output_shape: SemanticOutputShape = SemanticOutputShape.RESOURCE_LIST
    evidence_requirements: tuple[str, ...] = ()
    output_node_ids: tuple[str, ...] = ()


def seeded(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311 - deterministic test generator, not crypto


def _refs(rng: random.Random, index: int, count: int, start: int) -> tuple[str, ...]:
    return tuple(f"{rng.choice(LABELS)}:{index}:{start + offset}" for offset in range(count))


def generate(
    rng: random.Random, index: int, kind: str | None = None, *, failure: str | None = None
) -> Turn:
    """Build one seeded turn; ``manifest`` is the oracle for the exact terminal manifest."""
    assert failure is None or (kind == "held_overflow" and failure in {"held", "failed"})
    kind = kind or rng.choice(sorted(BASE_GENERATED_KINDS))
    authority = rng.choice(AUTHORITIES)
    nodes: list[Node] = []
    for position in range(rng.randint(1, 3)):
        refs = _refs(rng, index, rng.randint(1, 4), 4 * position)
        if nodes and rng.random() < 0.5:
            refs = (*refs, rng.choice(nodes[-1].refs))
        if rng.random() < 0.2:
            refs = (*refs, refs[0])
        nodes.append(Node(f"resources-{position + 1}", refs, authority))
    first = nodes[0]
    if kind == "max_refs":
        nodes = [Node("resources-1", _refs(rng, index, 7, 0), authority)]
        nodes.append(Node("resources-2", (*_refs(rng, index, 5, 7), nodes[0].refs[0]), authority))
    elif kind in {"max_ref_chars", "long_ref"}:
        size = 256 if kind == "max_ref_chars" else rng.randint(257, 512)
        nodes = [Node(first.node_id, (*first.refs, "근" * size), authority)]
    elif kind == "overflow_turn":
        nodes = [Node("resources-1", _refs(rng, index, 8, 0), authority)]
        nodes.append(Node("resources-2", _refs(rng, index, rng.randint(5, 12), 8), authority))
    elif kind == "overflow_goal":
        nodes = [Node("resources-1", _refs(rng, index, rng.randint(13, 16), 0), authority)]
    elif kind == "held_overflow":
        drawn = rng.choice(("failed", "held"))  # drawn even when pinned: same later draws
        failing = failure or drawn
        nodes = [Node("resources-1", _refs(rng, index, 9, 0), authority)]
        nodes.append(Node("resources-2", _refs(rng, index, rng.randint(4, 12), 9), authority))
        nodes.append(Node("resources-3", _refs(rng, index, 1, 30), authority, failing))
    elif kind == "empty":
        nodes = [Node(node.node_id, (), None) for node in nodes]
    elif kind == "conflict":
        other = rng.choice([item for item in AUTHORITIES if item is not authority])
        nodes = [first, Node("resources-9", _refs(rng, index, 2, 90), other)]
    elif kind in {"inherited", "inherited_conflict"}:
        derived = (
            rng.choice((None, EvidenceAuthority.SERVER_ONTOLOGY_QUERY))
            if kind == "inherited"
            else rng.choice([item for item in AUTHORITIES if item is not authority])
        )
        outcome = "ok" if kind == "inherited" else "derived_conflict"
        derived_refs = _refs(rng, index, 2, 40)
        nodes = [first, Node("resources-2", derived_refs, derived, outcome, ("resources-1",))]
    elif kind in {"unavailable", "failed", "partial_source"}:
        target = rng.randrange(len(nodes))
        outcome = {"unavailable": "held", "partial_source": "incomplete"}.get(kind, kind)
        nodes[target] = Node(nodes[target].node_id, nodes[target].refs, authority, outcome)
    completed = [node for node in nodes if node.outcome in {"ok", "incomplete"}]
    manifest = () if EXPECTED[kind] == INCOMPLETE else unique_refs(completed)
    return Turn(index, kind, "ko" if index % 2 else "en", tuple(nodes), authority, manifest)


def generate_multi_source(rng: random.Random, index: int) -> Turn:
    """Build one completed answer whose output nodes retain separate authorities."""
    power_refs = _refs(rng, index, rng.randint(1, 3), 0)
    health_refs = _refs(rng, index, rng.randint(1, 3), 8)
    nodes = (
        Node(
            "resource-condition-scope",
            (f"resource-condition-scope:{index}",),
            EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        ),
        Node(
            "resource-condition-power",
            power_refs,
            EvidenceAuthority.SERVER_INVENTORY_GRAPH,
            depends_on=("resource-condition-scope",),
            kind=QueryNodeKind.FUNCTION,
            arguments={"function_name": "query.resource_state_inventory"},
        ),
        Node(
            "resource-condition-health",
            health_refs,
            EvidenceAuthority.SERVER_RESOURCE_HEALTH,
            depends_on=("resource-condition-scope",),
            authority_inputs=(EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
            kind=QueryNodeKind.FUNCTION,
            arguments={"function_name": "query.resource_health_inventory"},
        ),
    )
    return Turn(
        index,
        "multi_source_authority",
        "ko" if index % 2 else "en",
        nodes,
        EvidenceAuthority.SERVER_RESOURCE_HEALTH,
        unique_refs(list(nodes)),
        output_shape=SemanticOutputShape.RESOURCE_CONDITION_SECTIONS,
        output_node_ids=("resource-condition-power", "resource-condition-health"),
    )


def generate_governed_document(rng: random.Random, index: int) -> Turn:
    """Build one governed-document answer with rendered citation lines."""
    refs = _refs(rng, index, rng.randint(1, 3), 0)
    rows: list[Mapping[str, object]] = [
        {
            "record_kind": "summary",
            "access_scope_digest": "sha256:" + "c" * 64,
            "index_generation": index,
            "retrieval_mode": "semantic",
            "source_complete": True,
            "source_limitation": None,
        }
    ]
    rows.extend(
        {
            "record_kind": "excerpt",
            "source_name": f"governed-document-{index}-{position}",
            "locator": f"section-{position}",
            "document_revision": f"rev-{index}-{position}",
            "evidence_ref": ref,
            "text": f"Bounded governed document excerpt {index}-{position}.",
            "display_content_digest": "sha256:" + f"{index:032x}{position:032x}",
            "redaction_applied": False,
        }
        for position, ref in enumerate(refs)
    )
    node = Node(
        "governed-documents",
        refs,
        EvidenceAuthority.SERVER_GOVERNED_DOCUMENT,
        rows=tuple(rows),
    )
    return Turn(
        index,
        "governed_document_citations",
        "ko" if index % 2 else "en",
        (node,),
        EvidenceAuthority.SERVER_GOVERNED_DOCUMENT,
        refs,
        output_shape=SemanticOutputShape.GOVERNED_DOCUMENT_EXCERPTS,
        evidence_requirements=("governed_documents.optional",),
    )


def unique_refs(nodes: list[Node]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref for node in nodes for ref in node.refs))


class Pipeline:
    """Long-lived Operator builder, Core processor, and Operator ingest, as deployed."""

    def __init__(self) -> None:
        self.turn: Turn | None = None
        runtime = SemanticConversationRuntime(
            planner=cast(Any, _Planner(self)),
            executor=OntologyQueryPlanExecutor(
                handlers={
                    QueryNodeKind.FUNCTION: self._handle,
                    QueryNodeKind.OBJECT_SET: self._handle,
                },
                now=lambda: NOW,
            ),
            purpose=PURPOSE,
        )
        self._builder = SemanticTurnEnvelopeBuilder(clock=lambda: NOW)
        self._processor = SemanticTurnProcessor(
            runtime=runtime,
            results=_Results(),
            now=lambda: NOW,
        )
        self._consumer = SemanticTurnProjectionConsumer(cast(Any, _OperatorStore()))

    async def run(self, turn: Turn) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return the Operator-ingested projection and the transported terminal event."""
        self.turn = turn
        envelope = self._builder.build(
            ConversationProposal(
                operation="chat.stream",
                scope=PrincipalScope("operator-1", frozenset({"Reader"})),
                idempotency_key=f"parity-{turn.index}",
                body={
                    "prompt": PROMPTS[turn.locale],
                    "conversation_id": f"conversation-{turn.index}",
                    "turn_sequence": 1,
                    "locale": turn.locale,
                },
            )
        )
        wire = await self._processor.process(envelope)
        if turn.index % 8 == 0:
            assert wire == await self._processor.process(envelope), "replay changed the projection"
        stored = await self._consumer.consume(json.loads(wire))
        assert dict(stored.data) == json.loads(wire), "Operator ingest altered the projection"
        done = semantic_done_event_data(stored.data, locale=turn.locale)
        return dict(stored.data), json.loads(json.dumps(done, ensure_ascii=False))

    async def _handle(
        self, node: OntologyQueryNode, dependencies: Mapping[str, QueryNodeResult]
    ) -> QueryNodeResult:
        del dependencies
        assert self.turn is not None
        spec = next(item for item in self.turn.nodes if item.node_id == node.node_id)
        if spec.outcome == "held":
            raise QueryNodeHeldError("provider_unavailable")
        if spec.outcome == "failed":
            raise RuntimeError("provider read failed")
        complete = spec.outcome != "incomplete"
        rows = (
            tuple(
                QueryRow.from_values(f"{node.node_id}-row-{position}", dict(values))
                for position, values in enumerate(spec.rows)
            )
            if spec.rows is not None
            else (QueryRow.from_values(f"{node.node_id}-row", {"state": "ready"}),)
        )
        table = QueryTable(
            rows=rows,
            complete=complete,
            truncation_reason=None if complete else "source_page_limit",
        )
        return QueryNodeResult(
            value=table,
            evidence_refs=spec.refs,
            authority=spec.authority,
            authority_inputs=spec.authority_inputs,
        )


class _Planner:
    """Stand in for the model-backed planner with one exact verified plan."""

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline

    def preflight(self, **_: object) -> ConversationPreflightResult:
        return ConversationPreflightResult(proposal=None)

    def plan(self, *, principal: Principal, **_: object) -> SemanticPlanningOutcome:
        turn = self._pipeline.turn
        assert turn is not None
        frame = build_semantic_frame(
            SemanticFrameProposal(
                operation=SemanticOperation.SELECT,
                output_shape=turn.output_shape,
                evidence_requirements=turn.evidence_requirements,
                investigation=None,
                confidence=1.0,
            ),
            utterance=PROMPTS[turn.locale],
            context=(str(turn.index),),
        )
        nodes = tuple(
            OntologyQueryNode(
                node_id=node.node_id,
                kind=node.kind,
                depends_on=node.depends_on,
                arguments_json=json.dumps(
                    dict(node.arguments or {}),
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                output_kind="object_set",
            )
            for node in turn.nodes
        )
        body: dict[str, Any] = {
            "ontology_release_digest": RELEASE,
            "semantic_catalog_digest": CATALOG,
            "problem_frame_digest": frame.frame_digest,
            "purpose": PURPOSE,
            "caller_role": principal.role.value,
            "output_node_ids": turn.output_node_ids or tuple(node.node_id for node in nodes),
        }
        wire_nodes = [node.model_dump(mode="json") for node in nodes]
        digest = content_digest(
            {**body, "schema_version": "1.0.0", "nodes": wire_nodes, "execution_authority": False}
        )
        plan = OntologyQueryPlan(**body, nodes=nodes, plan_digest=digest)
        return SemanticPlanningOutcome(
            disposition=SemanticPlanningDisposition.PLANNED,
            reason="semantic_plan_verified",
            manifest_digest=CATALOG,
            frame=frame,
            plan=plan,
            intent_graph=build_intent_graph(frame=frame, plan=plan, confidence=1.0),
        )


class _Results:
    def __init__(self) -> None:
        self._results: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self._results.get(key)

    async def claim(self, key: str, digest: str) -> str:
        return "claim"

    async def release(self, key: str, digest: str, claim_id: str) -> bool:
        return True

    async def put_if_absent(self, key: str, projection: bytes) -> bool:
        return self._results.setdefault(key, projection) is projection


class _OperatorStore:
    async def project_semantic_turn_result(
        self, *, projection: Mapping[str, object]
    ) -> StoredSemanticResult:
        return StoredSemanticResult(
            sequence=1,
            event="semantic_turn_result",
            request_id=cast(str, projection["request_id"]),
            principal_id="operator-1",
            projection_id=cast(str, projection["projection_id"]),
            data=dict(projection),
            duplicate=False,
        )


def cited(value: object) -> list[str]:
    """Collect every evidence reference cited anywhere in one terminal payload."""
    if isinstance(value, list):
        return [ref for item in value for ref in cited(item)]
    if not isinstance(value, Mapping):
        return []
    found: list[str] = []
    for key, item in value.items():
        if key == "evidence_refs" and isinstance(item, list):
            found.extend(ref for ref in item if isinstance(ref, str))
        else:
            found.extend(cited(item))
    return found


def violations(turn: Turn, projection: Mapping[str, Any], done: Mapping[str, Any]) -> list[str]:
    """Return every parity or fail-closed invariant the generated turn breaks."""
    semantic = projection["semantic_result"]
    manifest = tuple(semantic["evidence_refs"])
    verification = done["verification"]
    goals = (semantic.get("intent_graph_evidence") or {}).get("goals") or []
    completed = [goal for goal in goals if goal.get("status") == "completed"]
    resolvable = {ref for goal in completed for ref in goal.get("evidence_refs", [])}
    identity = {key: value for key, value in projection.items() if key != "projection_id"}
    identity_digest = content_digest(identity).removeprefix("sha256:")
    answered = semantic["disposition"] == "answered"
    checks = {
        "outcome_mismatch": (semantic["disposition"], semantic["reason_code"])
        != EXPECTED[turn.kind],
        "manifest_differs_from_server_receipts": manifest != turn.manifest,
        "manifest_not_unique": len(manifest) != len(set(manifest)),
        "verification_refs_differ": tuple(verification["evidence_refs"]) != manifest,
        "cited_ref_outside_manifest": not set(cited(done)) <= set(manifest),
        "manifest_ref_unresolvable": not set(manifest) <= resolvable,
        "evidence_digest_not_recomputable": projection["evidence_digest"]
        != content_digest(semantic),
        "projection_id_not_recomputable": projection["projection_id"]
        != str(uuid5(UUID(int=0), f"{projection['request_id']}\0{identity_digest}")),
        "receipt_digest_changed": answered
        and done["semantic_receipt"].get("execution_receipt_digest")
        != semantic["execution_receipt_digest"],
        "empty_or_held_turn_verified": verification["status"] == "verified"
        and (not answered or not manifest),
        "partial_source_not_consistent": turn.kind == "partial_source"
        and verification["status"] != "consistent",
        "server_authority_not_preserved": answered
        and turn.kind not in {"multi_source_authority"}
        and (verification["authority"], done["source"]) != (turn.authority.value,) * 2,
    }
    return [name for name, failed in checks.items() if failed]


@cache
def generated_turns() -> tuple[Turn, ...]:
    """Return the complete seeded stream; generation is independent of processing order."""
    rng = seeded(SEED)
    return tuple(generate(rng, index) for index in range(TURNS))


def test_generated_turn_stream_covers_every_kind_locale_and_failure_mode() -> None:
    turns = generated_turns()
    kinds = Counter(turn.kind for turn in turns)
    held_modes = {turn.nodes[-1].outcome for turn in turns if turn.kind == "held_overflow"}

    assert len(turns) == TURNS
    partitions = [turns[partition::PARTITIONS] for partition in range(PARTITIONS)]
    assert sorted(turn.index for part in partitions for turn in part) == list(range(TURNS))
    assert set(kinds) == BASE_GENERATED_KINDS and min(kinds.values()) >= 40
    assert Counter(turn.locale for turn in turns) == Counter({"en": TURNS // 2, "ko": TURNS // 2})
    assert held_modes == {"held", "failed"}


@pytest.mark.parametrize("partition", range(PARTITIONS))
async def test_generated_turns_keep_evidence_references_and_manifest_in_parity(
    partition: int,
) -> None:
    pipeline = Pipeline()
    failures: Counter[tuple[str, str]] = Counter()
    for turn in generated_turns()[partition::PARTITIONS]:
        projection, done = await pipeline.run(turn)
        failures.update((turn.kind, name) for name in violations(turn, projection, done))

    assert not failures


@cache
def multi_source_turns() -> tuple[Turn, ...]:
    """Return deterministic multi-authority turns independent of processing order."""
    rng = seeded(SEED ^ 0xA710)
    return tuple(generate_multi_source(rng, index) for index in range(TURNS))


@cache
def governed_document_turns() -> tuple[Turn, ...]:
    """Return deterministic governed-document citation turns."""
    rng = seeded(SEED ^ 0xD0C5)
    return tuple(generate_governed_document(rng, index) for index in range(TURNS))


def _authority_receipts(
    projection: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    goals = projection["semantic_result"]["intent_graph_evidence"]["goals"]
    return {
        goal["authority"]: tuple(goal.get("evidence_refs", ()))
        for goal in goals
        if goal.get("status") == "completed" and goal.get("authority")
    }


@pytest.mark.parametrize("partition", range(PARTITIONS))
async def test_multi_source_authority_answers_keep_each_authority_receipted(
    partition: int,
) -> None:
    pipeline = Pipeline()
    failures: Counter[tuple[str, str]] = Counter()
    for turn in multi_source_turns()[partition::PARTITIONS]:
        projection, done = await pipeline.run(turn)
        failures.update((turn.kind, name) for name in violations(turn, projection, done))
        receipts = _authority_receipts(projection)
        verification = done["verification"]
        source_verifications = verification.get("source_verifications", [])
        source_authorities = {
            item.get("authority") for item in source_verifications if isinstance(item, Mapping)
        }
        checks = {
            "multi_source_not_declared": verification["authority"]
            != "multiple_authoritative_sources",
            "inventory_authority_missing": EvidenceAuthority.SERVER_INVENTORY_GRAPH.value
            not in receipts,
            "health_authority_missing": EvidenceAuthority.SERVER_RESOURCE_HEALTH.value
            not in receipts,
            "inventory_receipt_substituted": not set(
                receipts[EvidenceAuthority.SERVER_INVENTORY_GRAPH.value]
            )
            <= set(turn.manifest),
            "health_receipt_substituted": not set(
                receipts[EvidenceAuthority.SERVER_RESOURCE_HEALTH.value]
            )
            <= set(turn.manifest),
            "source_verifications_not_authority_scoped": source_authorities
            != {
                EvidenceAuthority.SERVER_INVENTORY_GRAPH.value,
                EvidenceAuthority.SERVER_RESOURCE_HEALTH.value,
            },
        }
        failures.update((turn.kind, name) for name, failed in checks.items() if failed)

    assert not failures


def _pantheon_assurance(index: int) -> dict[str, object]:
    trace_digest = "a" * 64 if index % 2 == 0 else "b" * 64
    prompt_digest = "c" * 64 if index % 2 == 0 else "d" * 64
    return {
        "schema_version": "1.0.0",
        "answer": f"Bounded Pantheon assurance answer {index}.",
        "answer_generation": {
            "mode": "agent_projection",
            "model_identity": None,
            "model_family": None,
        },
        "pantheon_evaluator_models": [],
        "assessment_id": f"conversation-assessment:{index}",
        "assessment_state": "completed",
        "assessment_reasons": ["deterministic_seeded_consensus"],
        "trace_receipt_id": f"trace-receipt-{index}",
        "pantheon_trace": {"receipt_digest": trace_digest, "latency_ms": index % 97},
        "pantheon_observations": {"read_only": True, "case_index": index},
        "pantheon_semantic_reviews": [],
        "pantheon_prompt_profiles": {
            "answer_participants": [
                {
                    "agent": "Odin",
                    "prompt_version": "odin-v1",
                    "system_text_sha256": prompt_digest,
                    "situation": "audience=operator;phase=direct;tier=T1;locale=en",
                }
            ],
            "evaluator_profiles": [],
        },
        "pantheon_diagnostic": {
            "score": 30,
            "verdict": "passed",
            "case_index": index,
        },
        "execution_authority": False,
    }


class _PantheonRuntime:
    async def evaluate(self, request: object, *, case_id: str) -> Mapping[str, object]:
        del request
        return _pantheon_assurance(int(case_id.removeprefix("case-")))


class PantheonPipeline:
    """Core Pantheon assurance processor path plus Operator ingest and presentation."""

    def __init__(self) -> None:
        self._builder = SemanticTurnEnvelopeBuilder(clock=lambda: NOW)
        self._processor = SemanticTurnProcessor(
            runtime=None,
            results=_Results(),
            pantheon_assurance=cast(Any, _PantheonRuntime()),
            now=lambda: NOW,
        )
        self._consumer = SemanticTurnProjectionConsumer(cast(Any, _OperatorStore()))

    async def run(self, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
        envelope = self._builder.build(
            ConversationProposal(
                operation="chat.stream",
                scope=PrincipalScope("operator-1", frozenset({"Reader"})),
                idempotency_key=f"pantheon-parity-{index}",
                body={
                    "prompt": "Run bounded Pantheon assurance.",
                    "conversation_id": f"pantheon-conversation-{index}",
                    "turn_sequence": 1,
                    "locale": "en",
                    "purpose": f"conversation-assurance:case-{index}",
                },
            )
        )
        wire = await self._processor.process(envelope)
        stored = await self._consumer.consume(json.loads(wire))
        done = semantic_done_event_data(stored.data, locale="en")
        return dict(stored.data), json.loads(json.dumps(done, ensure_ascii=False))


@pytest.mark.parametrize("partition", range(PARTITIONS))
async def test_pantheon_assurance_traces_keep_core_operator_commitments(
    partition: int,
) -> None:
    pipeline = PantheonPipeline()
    failures: Counter[tuple[int, str]] = Counter()
    for index in range(partition, TURNS, PARTITIONS):
        projection, done = await pipeline.run(index)
        payload = cast(Mapping[str, object], projection["payload"])
        assurance = cast(Mapping[str, object], payload["pantheon_assurance"])
        checks = {
            "request_kind_not_pantheon": payload.get("request_kind")
            != PANTHEON_ASSURANCE_REQUEST_KIND,
            "evidence_digest_not_recomputable": projection["evidence_digest"]
            != semantic_projection_evidence_digest(projection),
            "projection_id_not_recomputable": projection["projection_id"]
            != semantic_projection_id(projection),
            "pantheon_digest_not_recomputable": projection["evidence_digest"]
            != pantheon_assurance_evidence_digest(assurance),
            "trace_receipt_substituted": done.get("trace_receipt_id")
            != assurance["trace_receipt_id"],
            "diagnostic_substituted": done.get("pantheon_diagnostic")
            != assurance["pantheon_diagnostic"],
            "answer_substituted": done.get("answer") != assurance["answer"],
            "execution_authority_granted": done.get("execution_authority") is not False,
        }
        failures.update((index, name) for name, failed in checks.items() if failed)

    assert not failures


def _fallback_evidence_refs(text: str) -> tuple[str, ...]:
    marker = "\n\nEvidence:\n"
    if marker not in text:
        return ()
    evidence = text.split(marker, 1)[1].split("\n\nAuthority:", 1)[0]
    if evidence == "- none recorded":
        return ()
    return tuple(line.removeprefix("- ") for line in evidence.splitlines())


@pytest.mark.parametrize("partition", range(PARTITIONS))
async def test_channel_adapters_render_exact_terminal_manifest_without_extra_citations(
    partition: int,
) -> None:
    pipeline = Pipeline()
    slack = SlackPresentationRenderer()
    teams = TeamsPresentationRenderer()
    failures: Counter[tuple[str, str]] = Counter()
    for turn in generated_turns()[partition::PARTITIONS]:
        projection, done = await pipeline.run(turn)
        failures.update((turn.kind, name) for name in violations(turn, projection, done))
        envelope = normalize_terminal_presentation(done)
        slack_payload = slack.render(envelope)
        teams_payload = teams.render(envelope)
        checks = {
            "channel_envelope_manifest_differs": envelope.evidence_refs != turn.manifest,
            "slack_manifest_differs": _fallback_evidence_refs(slack_payload.fallback_text)
            != turn.manifest,
            "teams_manifest_differs": _fallback_evidence_refs(teams_payload.fallback_text)
            != turn.manifest,
            "slack_payload_omitted_mandatory_refs": not all(
                ref in json.dumps(slack_payload.body, ensure_ascii=False) for ref in turn.manifest
            ),
            "teams_payload_omitted_mandatory_refs": not all(
                ref in json.dumps(teams_payload.body, ensure_ascii=False) for ref in turn.manifest
            ),
        }
        failures.update((turn.kind, name) for name, failed in checks.items() if failed)

    assert not failures


@pytest.mark.parametrize("partition", range(PARTITIONS))
async def test_governed_document_citations_resolve_to_manifest_and_receipts(
    partition: int,
) -> None:
    pipeline = Pipeline()
    failures: Counter[tuple[str, str]] = Counter()
    for turn in governed_document_turns()[partition::PARTITIONS]:
        projection, done = await pipeline.run(turn)
        failures.update((turn.kind, name) for name in violations(turn, projection, done))
        answer = done["answer"]
        cited_refs = tuple(ref for ref in turn.manifest if f"`{ref}`" in answer)
        receipts = _authority_receipts(projection)
        checks = {
            "governed_document_authority_missing": done["verification"]["authority"]
            != EvidenceAuthority.SERVER_GOVERNED_DOCUMENT.value,
            "citation_not_rendered": cited_refs != turn.manifest,
            "governed_receipt_missing": receipts.get(
                EvidenceAuthority.SERVER_GOVERNED_DOCUMENT.value
            )
            != turn.manifest,
        }
        failures.update((turn.kind, name) for name, failed in checks.items() if failed)

    assert not failures
