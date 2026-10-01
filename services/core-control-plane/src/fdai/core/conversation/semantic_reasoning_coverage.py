"""Deterministic coverage receipt over the closed question-form factor space.

Each cell is one synthetic admitted form built only from closed enum values and
placeholder spans. The receipt records which cells compile into verified plans
and the typed reason for every other cell, so coverage is measured, never
assumed. No model is called and no instance is read.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest

from .semantic_reasoning_admission import (
    AdmissionDisposition,
    SpanAccounting,
    admit_question_form,
)
from .semantic_reasoning_binding import (
    AnchorBinding,
    AnchorBindingReceipt,
    AnchorOutcome,
    anchor_mentions,
)
from .semantic_reasoning_compiler import compile_question_form
from .semantic_reasoning_concepts import ConceptBinding, ConceptOutcome, ConceptSelectionReceipt
from .semantic_reasoning_form import (
    SENSE_ROLES,
    GoalOperation,
    MeasureKind,
    MentionDomain,
    MentionForm,
    RelationReach,
    RelationSense,
    SemanticQuestionForm,
    SubjectRole,
    TimeKind,
)
from .semantic_reasoning_handles import (
    ReferenceBinding,
    ReferenceOutcome,
    ReferenceReceipt,
    reference_anchors,
)

_UTTERANCE = "anchor-a scope-b concept-c fragment-d cue-e time-f state-g ref-h"
_PRIOR_ROWS = ("object-prior-1", "object-prior-2")
_SPANS = {
    token: {"start": _UTTERANCE.index(token), "end": _UTTERANCE.index(token) + len(token)}
    for token in _UTTERANCE.split()
}
_RELATION_OPERATIONS = (
    GoalOperation.SELECT,
    GoalOperation.TRAVERSE,
    GoalOperation.IMPACT,
    GoalOperation.COUNT,
    GoalOperation.PATH,
)
_OTHER_OPERATIONS = (
    GoalOperation.AGGREGATE,
    GoalOperation.RANK,
    GoalOperation.COMPARE_WINDOWS,
    GoalOperation.COMPARE_ENTITIES,
    GoalOperation.DIFF_VERSIONS,
    GoalOperation.EXPLAIN_CAUSE,
    GoalOperation.VERIFY_EVIDENCE,
    GoalOperation.DIAGNOSE,
    GoalOperation.DRAFT_ACTION,
)
_COLLECTION_FILTERS = ("none", "type", "name_fragment", "scope", "state", "health", "region")
_CONCEPT_VALUES = {
    MentionDomain.RESOURCE_TYPE: ("compute.vm",),
    MentionDomain.OBJECT_TYPE: ("Resource",),
    MentionDomain.DECLARATION_KIND: ("object",),
    MentionDomain.STATE: ("resource_state.running",),
    MentionDomain.HEALTH: ("resource_health.unhealthy",),
    MentionDomain.METRIC: ("resource.cpu.utilization_pct",),
    MentionDomain.REGION: ("koreacentral",),
    MentionDomain.PROPERTY: ("retention.backup.days",),
}
# Every synthetic anchor is a PostgreSQL server, a type with a reviewed backup retention path.
_ANCHOR_TYPE = "postgresql-server"


@dataclass(frozen=True, slots=True)
class CoverageCell:
    cell_id: str
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReasoningCoverageReceipt:
    """Per-cell outcomes plus status and reason histograms."""

    manifest_release_digest: str
    cells: tuple[CoverageCell, ...]

    @property
    def status_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(cell.status for cell in self.cells).items()))

    @property
    def reason_counts(self) -> dict[str, int]:
        return dict(
            sorted(Counter(reason for cell in self.cells for reason in cell.reasons).items())
        )

    @property
    def compiled_cells(self) -> tuple[str, ...]:
        return tuple(sorted(cell.cell_id for cell in self.cells if cell.status == "compiled"))

    @property
    def digest(self) -> str:
        return content_digest(
            [
                {"cell": cell.cell_id, "status": cell.status, "reasons": list(cell.reasons)}
                for cell in self.cells
            ]
        )


def reasoning_coverage_receipt(
    *,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    purpose: str,
    evaluation_time: datetime,
    default_lookback_seconds: int,
) -> ReasoningCoverageReceipt:
    """Compile every closed factor cell and record its outcome."""

    cells: list[CoverageCell] = []
    for cell_id, raw in _cells():
        try:
            form = SemanticQuestionForm.model_validate(raw)
        except ValueError:
            cells.append(CoverageCell(cell_id, "inadmissible", ("form_contract_invalid",)))
            continue
        # A closed cell is a synthetic form over one fixed utterance, so it measures
        # compilation of admissible forms; word accounting is a per-utterance check.
        admission = admit_question_form(
            form, utterance=_UTTERANCE, accounting=SpanAccounting(required=False)
        )
        if admission.disposition is not AdmissionDisposition.ADMITTED:
            cells.append(CoverageCell(cell_id, "inadmissible", admission.reasons))
            continue
        # A closed cell with a reference ranges over a synthetic earlier answer of two rows.
        references = ReferenceReceipt(
            tuple(
                ReferenceBinding(
                    mention.id,
                    ReferenceOutcome.BOUND,
                    mention.form,
                    row_ids=_PRIOR_ROWS[:1] if mention.form is MentionForm.ORDINAL else _PRIOR_ROWS,
                    handle_id="handle-coverage",
                )
                for mention in form.mentions
                if mention.form in {MentionForm.ANAPHOR, MentionForm.ORDINAL}
            )
        )
        anchors = AnchorBindingReceipt(
            tuple(
                AnchorBinding(
                    item,
                    AnchorOutcome.BOUND,
                    object_id=f"object-{item}",
                    resource_type=_ANCHOR_TYPE,
                )
                for item in anchor_mentions(admission)
            )
        )
        compilation = compile_question_form(
            admission,
            concepts=_concepts(form),
            anchors=reference_anchors(anchors, references),
            references=references,
            manifest=manifest,
            verifier=verifier,
            purpose=purpose,
            evaluation_time=evaluation_time,
            default_lookback_seconds=default_lookback_seconds,
            utterance=_UTTERANCE,
        )
        goal = compilation.goals[0]
        cells.append(CoverageCell(cell_id, goal.status.value, goal.reasons))
    return ReasoningCoverageReceipt(manifest.release_digest, tuple(cells))


def _role_pairs(sense: RelationSense) -> tuple[tuple[SubjectRole, SubjectRole], ...]:
    source, target = SENSE_ROLES[sense]
    return ((source, target), (target, source), (SubjectRole.EITHER, SubjectRole.EITHER))


def _concepts(form: SemanticQuestionForm) -> ConceptSelectionReceipt:
    return ConceptSelectionReceipt(
        bindings=tuple(
            ConceptBinding(
                mention.id,
                mention.domain,
                ConceptOutcome.ACCEPTED,
                candidate_ids=tuple(f"value:{item}" for item in _CONCEPT_VALUES[mention.domain]),
                values=_CONCEPT_VALUES[mention.domain],
            )
            for mention in form.mentions
            if mention.domain in _CONCEPT_VALUES
        )
    )


def _cells() -> Iterator[tuple[str, dict[str, Any]]]:
    for operation in _RELATION_OPERATIONS:
        for sense in RelationSense:
            for anchor_role, result_role in _role_pairs(sense):
                for reach in RelationReach:
                    relation = {
                        "sense": sense.value,
                        "anchor_role": anchor_role.value,
                        "result_role": result_role.value,
                        "reach": reach.value,
                        "cue": _SPANS["cue-e"],
                    }
                    yield (
                        f"instance.{operation.value}.{sense.value}.{anchor_role.value}.{reach.value}",
                        _form(operation.value, subject="anchor", relation=relation),
                    )
    for sense in RelationSense:
        for anchor_role, result_role in _role_pairs(sense)[:2]:
            relation = {
                "sense": sense.value,
                "anchor": "m2",
                "anchor_role": anchor_role.value,
                "result_role": result_role.value,
                "cue": _SPANS["cue-e"],
            }
            yield (
                f"instance.select.results.{sense.value}.{anchor_role.value}",
                _form("select", subject="resource_type", relation=relation, object_anchor=True),
            )
    for anchor_role, result_role in _role_pairs(RelationSense.DEPENDENCY):
        relation = {
            "sense": RelationSense.DEPENDENCY.value,
            "scope": "all_kinds",
            "anchor_role": anchor_role.value,
            "result_role": result_role.value,
            "cue": _SPANS["cue-e"],
        }
        yield (
            f"instance.traverse.all_kinds.{anchor_role.value}",
            _form("traverse", subject="anchor", relation=relation),
        )
    yield "instance.impact.implied", _form("impact", subject="anchor")
    for operation in (GoalOperation.SELECT, GoalOperation.COUNT):
        for subject in ("none", "resource_type", "object_type"):
            for filter_role in _COLLECTION_FILTERS:
                yield (
                    f"instance.{operation.value}.{subject}.{filter_role}",
                    _form(operation.value, subject=subject, filter_role=filter_role),
                )
    for measure in MeasureKind:
        yield (
            f"instance.lookup.{measure.value}",
            _form("lookup", subject="anchor", measure=measure.value),
        )
    yield (
        "instance.lookup.property.bound",
        _form("lookup", subject="anchor", measure="property", measure_domain="property"),
    )
    for history_measure in ("none", "change", "event", "state"):
        for time in TimeKind:
            yield (
                f"instance.history.{history_measure}.{time.value}",
                _form("history", subject="anchor", measure=history_measure, time=time),
            )
    for operation in _OTHER_OPERATIONS:
        # A why question is admitted only in its canonical explain_cause and cause-want form.
        want = "cause" if operation is GoalOperation.EXPLAIN_CAUSE else "fact"
        yield (
            f"instance.{operation.value}",
            _form(operation.value, subject="anchor", measure="state", want=want),
        )
    yield (
        "instance.compare_windows.metric.two_windows",
        _form(
            "compare_windows",
            subject="anchor",
            measure="metric",
            measure_domain="metric",
            time=TimeKind.TWO_WINDOWS,
        ),
    )
    yield (
        "instance.compare_entities.state.two_anchors",
        _form("compare_entities", subject="anchor", measure="state", counterpart=True),
    )
    for want in ("cause", "verification", "completeness"):
        relation = {
            "sense": "dependency",
            "anchor_role": "dependency",
            "result_role": "dependent",
            "cue": _SPANS["cue-e"],
        }
        yield (
            f"instance.traverse.want.{want}",
            _form("traverse", subject="anchor", relation=relation, want=want),
        )
    prior_relation = {
        "sense": "dependency",
        "anchor_role": "dependency",
        "result_role": "dependent",
        "cue": _SPANS["cue-e"],
    }
    yield (
        "instance.traverse.prior_result",
        _form("traverse", subject="anaphor", relation=prior_relation),
    )
    yield (
        "instance.traverse.prior_result.ordinal",
        _form("traverse", subject="ordinal", relation=prior_relation),
    )
    for narrowed in ("select", "count"):
        for subject, suffix in (("anaphor", ""), ("ordinal", ".ordinal")):
            yield (
                f"instance.{narrowed}.prior_result{suffix}",
                _form(narrowed, subject=subject),
            )
    yield (
        "instance.traverse.prior_result.subset",
        _form(
            "traverse",
            subject="anaphor",
            relation={**prior_relation, "anchor": "m2"},
            object_anchor=True,
        ),
    )
    for schema_operation in ("describe_schema", "traverse", "select", "count"):
        for subject in ("object_type", "declaration_kind", "resource_type"):
            yield (
                f"schema.{schema_operation}.{subject}",
                _form(schema_operation, subject=subject, level="schema"),
            )


def _form(
    operation: str,
    *,
    subject: str,
    level: str = "instance",
    relation: dict[str, Any] | None = None,
    filter_role: str = "none",
    measure: str | None = None,
    measure_domain: str | None = None,
    time: TimeKind = TimeKind.CURRENT,
    want: str = "fact",
    object_anchor: bool = False,
    counterpart: bool = False,
) -> dict[str, Any]:
    mentions: list[dict[str, Any]] = []
    goal: dict[str, Any] = {
        "id": "g1",
        "level": level,
        "operation": operation,
        "cue": _SPANS["cue-e"],
        "confidence": 0.95,
        "want": want,
    }
    if subject == "anchor":
        mentions.append(_mention("m1", "name", "instance", "anchor-a"))
        goal.update(subject="m1", subject_scope="anchor")
    elif subject in {"anaphor", "ordinal"}:
        # A reference has its own words, apart from any named anchor it is narrowed by.
        mention = _mention("m1", subject, "instance", "ref-h")
        if subject == "ordinal":
            mention["position"] = 1
        mentions.append(mention)
        goal.update(subject="m1", subject_scope="prior_result")
    elif subject == "none":
        goal.update(subject_scope="collection")
    else:
        mentions.append(_mention("m1", "concept", subject, "concept-c"))
        goal.update(subject="m1", subject_scope="anchor" if level == "schema" else "collection")
    if object_anchor:
        mentions.append(_mention("m2", "name", "instance", "anchor-a"))
    if counterpart:
        mentions.append(_mention("m2", "name", "instance", "scope-b"))
        goal["counterpart"] = "m2"
    if relation is not None:
        goal["relation"] = relation
    if filter_role != "none":
        mention_id = f"m{len(mentions) + 1}"
        token, form, domain = {
            "type": ("scope-b", "concept", "resource_type"),
            "name_fragment": ("fragment-d", "value", "instance"),
            "scope": ("scope-b", "name", "instance"),
            "state": ("state-g", "concept", "state"),
            "health": ("state-g", "concept", "health"),
            "region": ("state-g", "concept", "region"),
        }[filter_role]
        mentions.append(_mention(mention_id, form, domain, token))
        goal["filters"] = [{"role": filter_role, "mention": mention_id}]
    if measure is not None and measure != "none":
        goal["measure"] = {"kind": measure}
        if measure_domain is not None:
            mention_id = f"m{len(mentions) + 1}"
            mentions.append(_mention(mention_id, "concept", measure_domain, "concept-c"))
            goal["measure"]["mention"] = mention_id
    goal["time"] = _time(time)
    return {"mentions": mentions, "goals": [goal]}


def _mention(mention_id: str, form: str, domain: str, token: str) -> dict[str, Any]:
    return {"id": mention_id, "form": form, "domain": domain, "span": _SPANS[token]}


def _time(kind: TimeKind) -> dict[str, Any]:
    if kind is TimeKind.WINDOW:
        return {
            "kind": kind.value,
            "value": {"duration": {"amount": 3, "unit": "day"}},
            "cue": _SPANS["time-f"],
        }
    if kind is TimeKind.AS_OF:
        return {"kind": kind.value, "value": {"calendar_offset_days": -1}, "cue": _SPANS["time-f"]}
    if kind is TimeKind.TWO_WINDOWS:
        return {
            "kind": kind.value,
            "windows": (
                {"duration": {"amount": 5, "unit": "minute"}},
                {"duration": {"amount": 5, "unit": "minute"}},
            ),
            "cue": _SPANS["time-f"],
        }
    return {"kind": kind.value}


__all__ = ["CoverageCell", "ReasoningCoverageReceipt", "reasoning_coverage_receipt"]
