"""Content-free semantic decision traces for the local development diagnostic channel.

A trace explains how a completed turn was understood: routing, judgment attempts, the planner's
own decision events, closed-choice grounding, the executed intent graph, and the outcome. Model
authored tokens are kept only when they belong to the reviewed repository vocabulary; server
constructed tokens must pass the closed-token grammar. Question, answer, target, predicate, and
draft text never enter a trace.
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from functools import cache
from pathlib import Path
from threading import Lock
from typing import Any

from fdai.shared.telemetry.decision_events import (
    DecisionTurn,
    PendingDecision,
    bind_decision_events,
    current_decision_turn,
    record_decision_observations,
)

_LOGGER = logging.getLogger(__name__)
# Identifiers, enum values, and dotted catalog names. Hyphens, spaces, quotes, and non-ASCII
# text are excluded, so resource names and phrases cannot pass.
_CLOSED_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}(?:[.:][A-Za-z0-9_]{1,63}){0,3}$")
_VOCABULARY_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:[.:][A-Za-z0-9_]+)*")
_VOCABULARY_DIRECTORIES = ("prompts/base", "prompts/packs", "prompts/profiles", "vocabulary")
_REDACTED = "~"
_MAX_ITEMS = 24
_MAX_MODEL_STEPS = 12
_MAX_EVENT_STEPS = 20
_MAX_ALIASES = 256
_TYPE_FILTER_KIND = "resource_type_filter"
_JUDGMENT_KINDS = frozenset({"semantic-judgment", "semantic-judgment-repair"})
_GROUNDING_KINDS = frozenset({"semantic-concept-selection", "semantic-constraint-extraction"})
_SERVER_EVENT_KEYS = frozenset(
    {
        "decline_reason",
        "disposition",
        "failure_type",
        "result",
        "review",
        "plan_source",
        "promotion_rejection_reason",
        "reason",
        "recovery",
        "stage",
        "target_field",
        "temporal_kind",
        "tier",
        "trigger",
        "validation_reason",
    }
)
_SERVER_EVENT_LIST_KEYS = frozenset(
    {
        "direction_swaps",
        "failed_preconditions",
        "form_shapes",
        "goal_limitations",
        "goal_reasons",
        "goal_statuses",
        "notes",
        "pass_dispositions",
        "pass_reasons",
        "review_reasons",
        "route_keys",
        "temporal_keys",
        "uncovered_keys",
        "uncovered_roles",
    }
)
_MODEL_EVENT_KEYS = frozenset(
    {
        "action_posture",
        "discourse_mode",
        "family",
        "operation",
        "output_shape",
        "primary_intent",
        "social_act",
        "target_kind",
    }
)
_MODEL_EVENT_LIST_KEYS = frozenset(
    {
        "facets",
        "grounded_properties",
        "measure_concepts",
        "proposal_object_subjects",
        "requested_facets",
        "secondary_intents",
        "target_kinds",
    }
)
_TYPE_EVENT_LIST_KEYS = frozenset({"canonical_target_types"})
_NUMERIC_EVENT_KEYS = frozenset(
    {
        "attempt",
        "batch_count",
        "clarification_count",
        "compiled_goals",
        "context_items_dropped",
        "context_items_kept",
        "descriptor_bytes",
        "descriptor_count",
        "elapsed_ms",
        "exact_occurrences",
        "failed_precondition_count",
        "grounded_count",
        "hypothesis_count",
        "impact_span_available",
        "lookback_seconds",
        "mention_count",
        "metrics_available",
        "model_calls",
        "operation_matches",
        "presented",
        "query_sides_available",
        "released",
        "service_impact_matches",
        "symptom_span_available",
        "target_available",
        "target_count",
        "target_index",
    }
)
_EVENT_CUES = {
    "conversation_preflight_context_trimmed": "preflight_context_trimmed",
    "conversation_preflight_model_failed": "preflight_model_failed",
    "conversation_preflight_operational_promotion_rejected": "preflight_promotion_rejected",
    "conversation_preflight_operational_shape_rejected": "preflight_shape_rejected",
    "semantic_compiled_answer_veto": "compiled_answer_veto",
    "semantic_direct_response_blocked_by_preflight": "direct_response_blocked",
    "semantic_judgment_assembly_fallback": "prompt_assembly_fallback",
    "semantic_judgment_coverage_unavailable": "coverage_unavailable",
    "semantic_judgment_model_failed": "judgment_model_failed",
    "semantic_judgment_proposal_rejected": "judgment_rejected",
    "semantic_judgment_proposal_retry": "judgment_retry",
    "semantic_judgment_target_span_unresolved": "target_span_unresolved",
    "semantic_manifest_catalog_value_conflict": "manifest_value_conflict",
    "semantic_plan_rejected": "plan_rejected",
    "semantic_planning_candidate_recovered": "candidate_recovered",
    "semantic_planning_candidate_recovery_unavailable": "candidate_recovery_unavailable",
    "semantic_planning_judgment_reused_preflight": "judgment_reused_preflight",
    "semantic_planning_t2_escalated": "t2_escalated",
    "semantic_planning_t2_withheld": "t2_withheld",
    "semantic_type_grounding_skipped": "type_grounding_skipped",
    "semantic_type_grounding_unavailable": "type_grounding_unavailable",
}
_OUTCOME_CUES = frozenset({"advisory_response", "clarification", "held", "unsupported"})
_COMPILED_ANSWER_RESULTS = frozenset(
    {"cancelled", "declined", "failed", "selected", "skipped", "timeout"}
)
_alias_lock = Lock()
_aliases: dict[str, OrderedDict[str, str]] = {"model": OrderedDict(), "session": OrderedDict()}
_alias_counters = {"model": 0, "session": 0}


def observe_semantic_decision(projection: Mapping[str, Any]) -> None:
    """Stage the bound turn's decision trace; the last staged projection is recorded.

    A turn can build a second projection, such as a hold after a wire-budget or result-store
    failure, so the collector records only when the semantic turn ends. This never raises
    into the product turn.
    """

    turn = current_decision_turn()
    if turn is None:
        return
    try:
        semantic_result = projection.get("semantic_result")
        if not isinstance(semantic_result, Mapping):
            return
        steps, cues = semantic_decision_steps(turn, semantic_result)
        turn_sequence = semantic_result.get("turn_sequence")
        turn.pending = PendingDecision(
            session=_alias("session", semantic_result.get("session_id")),
            turn_sequence=turn_sequence
            if isinstance(turn_sequence, int) and _is_count(turn_sequence)
            else None,
            steps=steps,
            cues=cues,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never change the product turn.
        _LOGGER.warning("development_decision_trace_skipped")


def semantic_decision_steps(
    turn: DecisionTurn,
    semantic_result: Mapping[str, Any],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Project model calls, planner events, and the outcome into typed steps and cues."""

    trace = _TraceBuilder()
    for observation in list(turn.observations)[:64]:
        trace.add_model_call(observation)
    trace.add_grounding()
    with turn.lock:
        events = list(turn.events)
        dropped = turn.dropped_events
    for name, extras in events[:_MAX_EVENT_STEPS]:
        trace.add_event(name, extras)
    graph = semantic_result.get("intent_graph")
    if isinstance(graph, Mapping):
        trace.add_intent_graph(graph)
    trace.add_outcome(
        semantic_result,
        dropped + max(0, len(events) - _MAX_EVENT_STEPS),
        planning=(turn.planning_disposition, turn.planning_reason),
    )
    return trace.steps, trace.cues


class _TraceBuilder:
    """Accumulate ordered steps and cues that point at the step to inspect."""

    def __init__(self) -> None:
        self.steps: list[dict[str, object]] = []
        self.cues: list[dict[str, object]] = []
        self._model_steps = 0
        self._grounding_models: list[str] = []
        self._grounding_statuses: list[str] = []
        self._preflight_spans: list[tuple[int, int]] = []
        self._preflight_step: int | None = None
        self._judgment_spans: list[tuple[int, int]] | None = None
        self._judgment_steps: list[int] = []
        self._type_target = False
        self._type_predicate = False
        self._model_frame = False
        self._model_plan = False

    def add_model_call(self, observation: object) -> None:
        call = getattr(observation, "trace_call", None)
        if not isinstance(call, Mapping):
            return
        raw_kind = call.get("kind")
        kind = raw_kind if isinstance(raw_kind, str) else ""
        model = _alias("model", getattr(observation, "model", None))
        if kind in _GROUNDING_KINDS:
            self._grounding_models.append(model)
            self._grounding_statuses.append(_server_token(call.get("status")))
            return
        if self._model_steps >= _MAX_MODEL_STEPS:
            return
        self._model_steps += 1
        stage = _stage(kind)
        attributes: dict[str, object] = {
            "model": model,
            "status": _server_token(call.get("status")),
        }
        duration = call.get("duration_ms")
        if _is_count(duration):
            attributes["duration_ms"] = duration
        index = len(self.steps)
        redactions = _Redactions()
        attributes.update(self._call_attributes(stage, _response_body(call), index, redactions))
        if redactions.count:
            attributes["unreviewed_tokens"] = redactions.count
            self._cue("unreviewed_model_token", index)
        self.steps.append({"stage": stage, "attributes": attributes})

    def _call_attributes(
        self,
        stage: str,
        body: Mapping[str, Any] | None,
        index: int,
        redact: _Redactions,
    ) -> dict[str, object]:
        if body is None:
            return {"parsed": False}
        if stage == "preflight":
            targets = _targets(body.get("operational_targets"), redact)
            self._preflight_spans = [span for _kind, span in targets if span is not None]
            self._preflight_step = index
            self._type_target |= any(kind == _TYPE_FILTER_KIND for kind, _span in targets)
            if body.get("context_dependency") == "active_thread":
                self._cue("active_thread_dependency", index)
            return {
                "family": redact.token(body.get("operational_family")),
                "topics": redact.tokens(body.get("request_topics")),
                "context_dependency": redact.token(body.get("context_dependency")),
                "operational_signal": redact.token(body.get("operational_signal")),
                "knowledge_signal": redact.token(body.get("knowledge_signal")),
                "social_act": redact.token(body.get("social_act")),
                "window": redact.token(body.get("operational_window")),
                "facets": redact.tokens(body.get("operational_facets")),
                "target_kinds": tuple(kind for kind, _span in targets),
                "general_answer": body.get("general_answer") is not None,
                "confidence_pct": _percent(body.get("confidence")),
            }
        if stage == "judgment":
            targets = _targets(body.get("targets"), redact)
            self._judgment_spans = [span for _kind, span in targets if span is not None]
            self._judgment_steps.append(index)
            self._type_target |= any(kind == _TYPE_FILTER_KIND for kind, _span in targets)
            if body.get("ambiguous") is True:
                self._cue("judgment_ambiguous", index)
            return {
                "attempt": len(self._judgment_steps),
                "intent": redact.token(body.get("primary_intent")),
                "secondary": redact.tokens(body.get("secondary_intents")),
                "target_kinds": tuple(kind for kind, _span in targets),
                "canonical_targets": sum(
                    1
                    for item in _mappings(body.get("targets"))
                    if item.get("canonical_value") is not None
                ),
                "facets": redact.tokens(body.get("requested_facets")),
                "ambiguous": body.get("ambiguous") is True,
                "alternatives": len(_list(body.get("alternatives"))),
                "unresolved_terms": len(_list(body.get("unresolved_terms"))),
                "clarification": body.get("clarification") is not None,
                "direct_response": body.get("direct_response") is not None,
                "discourse_mode": redact.token(body.get("discourse_mode")),
                "action_posture": redact.token(body.get("action_posture")),
                "confidence_pct": _percent(body.get("confidence")),
            }
        if stage == "frame":
            self._model_frame = True
            self._cue("model_frame_call", index)
            unresolved = len(_list(body.get("unresolved_terms")))
            if unresolved:
                self._cue("frame_unresolved_terms", index)
            subjects = [
                item.split("=", 1)[0]
                for item in _list(body.get("subject_constraints"))
                if isinstance(item, str)
            ]
            return {
                "operation": redact.token(body.get("operation")),
                "output_shape": redact.token(body.get("output_shape")),
                "measures": redact.tokens(body.get("measure_concepts")),
                "subjects": redact.tokens(subjects),
                "subject_constraints": len(_list(body.get("subject_constraints"))),
                "clarification_requirements": redact.tokens(body.get("clarification_requirements")),
                "evidence_requirements": len(_list(body.get("evidence_requirements"))),
                "unresolved_terms": unresolved,
                "clarification": body.get("clarification") is not None,
                "confidence_pct": _percent(body.get("confidence")),
            }
        if stage == "plan":
            self._model_plan = True
            self._cue("model_plan_call", index)
            nodes = _mappings(body.get("nodes"))
            predicates = _predicates(nodes, redact)
            self._type_predicate |= any(item.startswith("type:") for item in predicates)
            return {
                "nodes": len(nodes),
                "node_kinds": redact.tokens(item.get("kind") for item in nodes),
                "output_kinds": redact.tokens(item.get("output_kind") for item in nodes),
                "predicates": predicates,
                "outputs": len(_list(body.get("output_node_ids"))),
            }
        if stage == "adaptive.plan":
            if body.get("route") == "adaptive":
                self._cue("adaptive_takeover", index)
            if body.get("context_dependency") == "active_thread":
                self._cue("active_thread_dependency", index)
            goals = _mappings(body.get("goals"))
            return {
                "route": redact.token(body.get("route")),
                "context_dependency": redact.token(body.get("context_dependency")),
                "social_act": redact.token(body.get("social_act")),
                "action_requested": body.get("action_requested") is True,
                "goal_kinds": redact.tokens(item.get("kind") for item in goals),
                "goals": len(goals),
                "draft_sections": len(_mappings(_mapping(body.get("draft")).get("sections"))),
            }
        if stage in {"adaptive.review", "adaptive.verify"}:
            return {
                "safe": body.get("safe") is True,
                "complete": body.get("complete") is True,
                "supported_goals": len(_list(body.get("supported_goal_ids"))),
                "issues": len(_list(body.get("issues"))),
            }
        if stage in {"adaptive.refine", "adaptive.answer"}:
            return {"sections": len(_mappings(body.get("sections")))}
        return {"fields": len(body)}

    def add_grounding(self) -> None:
        if not self._grounding_models:
            return
        self.steps.append(
            {
                "stage": "grounding",
                "attributes": {
                    "calls": len(self._grounding_models),
                    "models": tuple(dict.fromkeys(self._grounding_models))[:_MAX_ITEMS],
                    "statuses": tuple(dict.fromkeys(self._grounding_statuses))[:_MAX_ITEMS],
                },
            }
        )

    def add_event(self, name: str, extras: Mapping[str, object]) -> None:
        index = len(self.steps)
        redact = _Redactions()
        attributes: dict[str, object] = {}
        for key, value in sorted(extras.items()):
            if len(attributes) >= 31:
                break
            if key in _SERVER_EVENT_KEYS:
                attributes[key] = _server_token(value)
            elif key in _SERVER_EVENT_LIST_KEYS:
                attributes[key] = _server_tokens(value)
            elif key in _MODEL_EVENT_KEYS:
                attributes[key] = redact.token(value)
            elif key in _MODEL_EVENT_LIST_KEYS:
                attributes[key] = redact.tokens(value)
            elif key in _TYPE_EVENT_LIST_KEYS:
                attributes[key] = tuple(
                    item if isinstance(item, str) and item in _resource_type_ids() else _REDACTED
                    for item in _items(value)
                )
            elif key in _NUMERIC_EVENT_KEYS and (_is_count(value) or isinstance(value, bool)):
                attributes[key] = value
        if redact.count:
            attributes["unreviewed_tokens"] = redact.count
            self._cue("unreviewed_model_token", index)
        stage = f"event.{name}"[:64] if _CLOSED_TOKEN.fullmatch(name) else "event.other"
        self.steps.append({"stage": stage, "attributes": attributes})
        cue = _EVENT_CUES.get(name)
        if cue is not None:
            self._cue(cue, index)
        result = extras.get("result")
        if name == "semantic_compiled_answer_completed" and result in _COMPILED_ANSWER_RESULTS:
            self._cue(f"compiled_answer_{result}", index)

    def add_intent_graph(self, graph: Mapping[str, Any]) -> None:
        goals = _mappings(graph.get("goals"))
        predicates = _predicates(goals, None)
        self._type_predicate |= any(item.startswith("type:") for item in predicates)
        arguments = [_mapping(goal.get("arguments")) for goal in goals]
        self.steps.append(
            {
                "stage": "intent_graph",
                "attributes": {
                    "goals": len(goals),
                    "capabilities": _server_tokens(goal.get("capability") for goal in goals),
                    "intents": _server_tokens(goal.get("intent") for goal in goals),
                    "dependencies": sum(len(_list(goal.get("depends_on"))) for goal in goals),
                    "predicates": predicates,
                    "link_types": _server_tokens(
                        link for argument in arguments for link in _list(argument.get("link_types"))
                    ),
                    "directions": _server_tokens(
                        argument.get("direction") for argument in arguments
                    ),
                    "action_posture": _server_token(graph.get("action_posture")),
                    "clarification": graph.get("clarification") is not None,
                    "confidence_pct": _percent(graph.get("confidence")),
                },
            }
        )

    def add_outcome(
        self,
        semantic_result: Mapping[str, Any],
        dropped_events: int,
        *,
        planning: tuple[object, object] = (None, None),
    ) -> None:
        index = len(self.steps)
        disposition = _server_token(semantic_result.get("disposition"))
        reason_code = _server_token(semantic_result.get("reason_code"))
        attributes: dict[str, object] = {
            "route": _server_token(semantic_result.get("semantic_route")),
            "disposition": disposition,
            "reason_code": reason_code,
            "planning_disposition": _server_token(planning[0]),
            "planning_reason": _server_token(planning[1]),
            "checks_completed": _count(semantic_result.get("checks_completed")),
            "checks_total": _count(semantic_result.get("checks_total")),
            "plan_bound": semantic_result.get("plan_digest") is not None,
            "model_frame_calls": int(self._model_frame),
            "model_plan_calls": int(self._model_plan),
            "dropped_events": dropped_events,
        }
        observation = semantic_result.get("assurance_observation")
        if isinstance(observation, Mapping):
            frame = _mapping(observation.get("frame"))
            read_performed = observation.get("read_performed")
            posture = _server_token(observation.get("evidence_posture"))
            attributes.update(
                {
                    "operation": _server_token(frame.get("operation")),
                    "output_shape": _server_token(frame.get("output_shape")),
                    "subject_types": _server_tokens(frame.get("subject_types")),
                    "measure_concepts": _server_tokens(frame.get("measure_concepts")),
                    "temporal_scope": _server_token(frame.get("temporal_scope")),
                    "capabilities": _server_tokens(observation.get("capabilities")),
                    "object_types": _server_tokens(observation.get("object_types")),
                    "link_types": _server_tokens(observation.get("link_types")),
                    "function_types": _server_tokens(observation.get("function_types")),
                    "ontology_paths": len(_list(observation.get("ontology_paths"))),
                    "evidence_posture": posture,
                    "read_performed": read_performed is True,
                    "limitation_kinds": _server_tokens(observation.get("limitation_kinds")),
                }
            )
            if read_performed is False:
                self._cue("no_ontology_read", index)
            if posture == "incomplete":
                self._cue("evidence_incomplete", index)
        adaptive = semantic_result.get("adaptive_answer")
        if isinstance(adaptive, Mapping):
            attributes.update(
                {
                    "adaptive_quality": _server_token(adaptive.get("quality_status")),
                    "adaptive_goals": len(_list(adaptive.get("goals"))),
                    "adaptive_refinements": len(_list(adaptive.get("refinements"))),
                }
            )
        self.steps.append({"stage": "outcome", "attributes": attributes})
        if (
            self._preflight_step is not None
            and self._judgment_spans is not None
            and any(
                not any(_overlaps(span, other) for other in self._judgment_spans)
                for span in self._preflight_spans
            )
        ):
            self._cue("preflight_target_uncovered", self._preflight_step)
        if self._type_target and not self._type_predicate:
            self._cue("type_target_unbound", index)
        if disposition in _OUTCOME_CUES:
            self._cue(f"{disposition}_outcome", index)
        if reason_code == "semantic_answer_partial":
            self._cue("partial_answer", index)
        if dropped_events:
            self._cue("events_truncated", index)

    def _cue(self, code: str, step: int) -> None:
        if len(self.cues) < 32 and {"code": code, "step": step} not in self.cues:
            self.cues.append({"code": code, "step": step})


class _Redactions:
    """Keep model-authored tokens only when the reviewed vocabulary contains them."""

    def __init__(self) -> None:
        self.count = 0

    def token(self, value: object) -> str:
        if value is None:
            return "none"
        if isinstance(value, str) and _CLOSED_TOKEN.fullmatch(value) and _reviewed(value):
            return value
        self.count += 1
        return _REDACTED

    def tokens(self, values: object) -> tuple[str, ...]:
        return tuple(self.token(item) for item in _items(values))


def _reviewed(value: str) -> bool:
    vocabulary = _reviewed_vocabulary()
    return value in vocabulary or all(part in vocabulary for part in re.split(r"[.:]", value))


@cache
def _reviewed_vocabulary() -> frozenset[str]:
    """Collect words from the reviewed, customer-agnostic prompt and vocabulary catalogs."""

    try:
        from fdai.runtime.configuration import _resolve_catalog_root

        root = _resolve_catalog_root()
    except Exception:  # noqa: BLE001 - an unavailable catalog redacts every model token.
        return frozenset()
    words: set[str] = set()
    for directory in _VOCABULARY_DIRECTORIES:
        base = Path(root) / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix in {".yaml", ".yml", ".json"} and path.is_file():
                words.update(_VOCABULARY_WORD.findall(path.read_text("utf-8", errors="ignore")))
    return frozenset(words)


@cache
def _resource_type_ids() -> frozenset[str]:
    try:
        from fdai.runtime.control_loop_catalogs import load_resource_types

        return frozenset(load_resource_types().ids())
    except Exception:  # noqa: BLE001 - an unavailable vocabulary only redacts type values.
        return frozenset()


def _alias(kind: str, value: object) -> str:
    """Return a process-local alias that neither reveals nor links the underlying value."""

    if not isinstance(value, str) or not value:
        return _REDACTED if kind == "model" else "s0"
    prefix = "model-" if kind == "model" else "s"
    with _alias_lock:
        table = _aliases[kind]
        alias = table.get(value)
        if alias is None:
            _alias_counters[kind] = _alias_counters[kind] % 999_999 + 1
            alias = f"{prefix}{_alias_counters[kind]}"
            table[value] = alias
            if len(table) > _MAX_ALIASES:
                table.popitem(last=False)
        else:
            table.move_to_end(value)
        return alias


def _stage(kind: str) -> str:
    if kind == "conversation-preflight":
        return "preflight"
    if kind in _JUDGMENT_KINDS:
        return "judgment"
    if kind == "semantic-planning-frame":
        return "frame"
    if kind == "semantic-planning-plan":
        return "plan"
    if kind.startswith("adaptive-") and _CLOSED_TOKEN.fullmatch(kind[9:]):
        return f"adaptive.{kind[9:]}"[:64]
    token = kind.replace("-", "_")
    return f"call.{token}"[:64] if _CLOSED_TOKEN.fullmatch(token) else "call.other"


def _response_body(call: Mapping[str, Any]) -> Mapping[str, Any] | None:
    response = call.get("response")
    content = response.get("content") if isinstance(response, Mapping) else None
    if not isinstance(content, str) or not content:
        return None
    try:
        body = json.loads(content, strict=False)
    except ValueError:
        return None
    return body if isinstance(body, Mapping) else None


def _targets(value: object, redact: _Redactions) -> list[tuple[str, tuple[int, int] | None]]:
    targets: list[tuple[str, tuple[int, int] | None]] = []
    for item in _mappings(value)[:_MAX_ITEMS]:
        start, end = item.get("source_start"), item.get("source_end")
        span = (
            (start, end)
            if isinstance(start, int) and isinstance(end, int) and _is_count(start) and start <= end
            else None
        )
        targets.append((redact.token(item.get("kind")), span))
    return targets


def _predicates(
    containers: Sequence[Mapping[str, Any]],
    redact: _Redactions | None,
) -> tuple[str, ...]:
    """Return predicate property and operator pairs; values stay out except reviewed types."""

    found: list[str] = []
    pending: list[tuple[object, int]] = [(item, 0) for item in containers]
    while pending and len(found) < _MAX_ITEMS:
        value, depth = pending.pop(0)
        if depth > 6:
            continue
        if isinstance(value, Mapping):
            prop, operator = value.get("property"), value.get("operator")
            if isinstance(prop, str) and isinstance(operator, str):
                check = redact.token if redact is not None else _server_token
                token = f"{check(prop)}:{check(operator)}"
                typed = value.get("equals")
                if prop == "type" and isinstance(typed, str) and typed in _resource_type_ids():
                    token = f"{token}:{typed}"
                found.append(token)
                continue
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list | tuple):
            pending.extend((item, depth + 1) for item in value)
    return tuple(found)


def _server_token(value: object) -> str:
    if isinstance(value, str):
        if _CLOSED_TOKEN.fullmatch(value):
            return value
        # A server code with a span suffix, such as review_uncovered:asks:3-5, keeps its closed
        # code prefix; the suffix is dropped, never shown.
        head = value
        while ":" in head:
            head = head.rsplit(":", 1)[0]
            if _CLOSED_TOKEN.fullmatch(head):
                return head
    return "none" if value is None else _REDACTED


def _server_tokens(values: object) -> tuple[str, ...]:
    return tuple(_server_token(item) for item in _items(values))


def _items(values: object) -> list[object]:
    if isinstance(values, str):
        # Planner log events join closed tokens with commas.
        parts: list[object] = [item for item in values.split(",") if item]
        return parts[:_MAX_ITEMS]
    if isinstance(values, Iterable) and not isinstance(values, bytes | Mapping):
        return list(values)[:_MAX_ITEMS]
    return []


def _percent(value: object) -> int:
    if isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 1:
        return round(value * 100)
    return -1


def _count(value: object) -> int:
    return value if isinstance(value, int) and _is_count(value) else -1


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000_000


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[Mapping[str, Any]]:
    return [item for item in _list(value) if isinstance(item, Mapping)]


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


__all__ = [
    "bind_decision_events",
    "observe_semantic_decision",
    "record_decision_observations",
    "semantic_decision_steps",
]
