"""Deterministic claim verification (V-CLAIM) for model-authored answers.

The answer author returns structured claims beside its prose. Before display,
V-CLAIM checks that every claim cites verified evidence, that every literal the
prose shows is bound to the evidence cell it renders, that counts equal the
authoritative count, that every result row is accounted for, that required
limitations are stated, and that negative and causal claims have the evidence
they need. Names compare through canonical identities, never substrings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from fdai_service_contracts.answer_claims import (
    MAX_ANSWER_CHARS,
    AnswerClaim,
    AnswerClaimKind,
    AnswerClaimProposition,
    AnswerClaimSpan,
    AnswerEvidenceRef,
    AnswerLiteralBinding,
    ComposedAnswer,
)

from fdai.core.ontology_platform.query_values import QueryTable

from .causal_grade_receipts import CausalGradeReceipt, supports_causal_hypothesis
from .semantic_reasoning_claim_text import (
    NUMBER_QUALIFIERS,
    code_parts,
    literal_shaped,
    text_violations,
    tokens,
)

ClaimKind = AnswerClaimKind
type EvidenceRef = AnswerEvidenceRef
type LiteralBinding = AnswerLiteralBinding
type ClaimProposition = AnswerClaimProposition
type SourceSpan = AnswerClaimSpan


class GoalEvidenceStatus(StrEnum):
    VERIFIED = "verified"
    VERIFIED_EMPTY = "verified_empty"
    UNKNOWN_INCOMPLETE = "unknown_incomplete"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class GoalEvidence:
    """Verified evidence for one goal, as executed and classified by Core."""

    goal_id: str
    status: GoalEvidenceStatus
    tables: Mapping[str, QueryTable] = field(default_factory=dict)
    required_limitations: tuple[str, ...] = ()
    authoritative_count: int | None = None
    causal_evidence: bool = False
    causal_grade_receipts: tuple[CausalGradeReceipt, ...] = ()
    rendered_nodes: frozenset[str] = frozenset()
    possible_only: bool = False


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    """The deterministic V-CLAIM result.

    V-CLAIM checks references, literals, counts, rows, limitations, and restatement
    boundaries; it cannot judge whether ordinary words are entailed. An accepted
    verdict therefore still requires the independent entailment review before any
    answer is shown, and no consumer may treat acceptance alone as display approval.
    """

    accepted: bool
    violations: tuple[str, ...]
    entailment_review_required: Literal[True] = True


def verify_answer_claims(
    answer: ComposedAnswer,
    *,
    evidence: Sequence[GoalEvidence],
    utterance: str,
    known_identities: frozenset[str] = frozenset(),
) -> ClaimVerdict:
    """Return whether every displayed statement is entailed by verified evidence.

    A restatement may repeat only tokens the operator wrote in ``utterance``, and a
    limitation may state only the segments of the codes Core required.
    """

    goals = {item.goal_id: item for item in evidence}
    context = _Context(
        goals=goals,
        required_codes=frozenset(code for goal in evidence for code in goal.required_limitations),
        rows={
            (goal.goal_id, node_id): frozenset(row.row_id for row in table.rows)
            for goal in evidence
            for node_id, table in goal.tables.items()
        },
    )
    violations = list(text_violations(answer.text))
    for claim in answer.claims:
        violations.extend(_claim_violations(claim, answer, context))
    violations.extend(_coverage_violations(answer, goals))
    violations.extend(_undeclared_literals(answer, context, known_identities, utterance))
    unique = tuple(dict.fromkeys(violations))
    return ClaimVerdict(accepted=not unique, violations=unique)


@dataclass(frozen=True, slots=True)
class _Context:
    goals: Mapping[str, GoalEvidence]
    required_codes: frozenset[str]
    rows: Mapping[tuple[str, str], frozenset[str]]


def _claim_violations(claim: AnswerClaim, answer: ComposedAnswer, ctx: _Context) -> list[str]:
    if claim.kind is ClaimKind.LIMITATION:
        return _limitation_violations(claim, ctx)
    violations: list[str] = []
    if claim.limitation_codes:
        violations.append(f"limitation_code_outside_limitation:{claim.id}")
    if claim.kind is ClaimKind.RESTATEMENT:
        return violations + _restatement_violations(claim, answer)
    if not claim.refs:
        violations.append(f"claim_without_evidence:{claim.id}")
    for ref in claim.refs:
        if _cell(ref, ctx.goals) is _MISSING:
            violations.append(f"evidence_ref_unresolved:{claim.id}")
    cited = {ref.goal for ref in claim.refs}
    for literal in claim.literals:
        violations.extend(_literal_violations(claim, literal, answer.text, ctx))
        # A literal may render only a goal its claim cites, so goal checks always apply.
        if literal.ref.goal not in cited:
            violations.append(f"literal_goal_uncited:{claim.id}")
    for goal_id in sorted(cited | {literal.ref.goal for literal in claim.literals}):
        goal = ctx.goals.get(goal_id)
        if goal is not None:
            violations.extend(_goal_claim_violations(claim, goal))
    violations.extend(_proposition_violations(claim, ctx))
    violations.extend(_row_violations(claim, ctx))
    return violations


def _limitation_violations(claim: AnswerClaim, ctx: _Context) -> list[str]:
    violations: list[str] = []
    if not claim.limitation_codes:
        violations.append(f"limitation_without_code:{claim.id}")
    if any(code not in ctx.required_codes for code in claim.limitation_codes):
        violations.append(f"limitation_code_unknown:{claim.id}")
    if claim.literals or claim.rows:
        violations.append(f"limitation_with_literals:{claim.id}")
    return violations


def _restatement_violations(claim: AnswerClaim, answer: ComposedAnswer) -> list[str]:
    violations: list[str] = []
    proposition = claim.proposition
    if claim.literals or claim.rows or claim.refs:
        violations.append(f"restatement_with_evidence:{claim.id}")
    if proposition.polarity != "affirm" or proposition.modality != "observed":
        violations.append(f"restatement_asserts:{claim.id}")
    if any(
        other.kind is not ClaimKind.RESTATEMENT
        and other.span.start < claim.span.end
        and claim.span.start < other.span.end
        for other in answer.claims
    ):
        violations.append(f"restatement_overlaps_claim:{claim.id}")
    return violations


def _literal_violations(
    claim: AnswerClaim, literal: LiteralBinding, text: str, ctx: _Context
) -> list[str]:
    violations: list[str] = []
    shown = text[literal.span.start : literal.span.end]
    cell = _cell(literal.ref, ctx.goals)
    if shown != str(literal.value):
        violations.append(f"literal_text_mismatch:{claim.id}")
    elif cell is _MISSING or not _same_value(cell, literal.value):
        violations.append(f"literal_value_mismatch:{claim.id}")
    if not _inside(literal.span, claim.span):
        violations.append(f"literal_outside_claim:{claim.id}")
    before = text[literal.span.start - 1] if literal.span.start > 0 else ""
    if isinstance(literal.value, int) and before in NUMBER_QUALIFIERS:
        violations.append(f"literal_qualified_by_symbol:{claim.id}")
    return violations


def _goal_claim_violations(claim: AnswerClaim, goal: GoalEvidence) -> list[str]:
    violations: list[str] = []
    proposition = claim.proposition
    if goal.status in {GoalEvidenceStatus.UNAVAILABLE, GoalEvidenceStatus.UNSUPPORTED} and (
        claim.kind is not ClaimKind.NEXT_CHECK
    ):
        violations.append(f"fact_from_unavailable_goal:{claim.id}")
    if proposition.polarity == "deny" and goal.status is not GoalEvidenceStatus.VERIFIED_EMPTY:
        violations.append(f"negative_claim_without_closed_population:{claim.id}")
    counts = [
        item.value
        for item in claim.literals
        if isinstance(item.value, int) and item.ref.goal == goal.goal_id
    ]
    if goal.authoritative_count is not None and (counts or claim.kind is ClaimKind.COUNT):
        if counts != [goal.authoritative_count]:
            violations.append(f"count_differs_from_authority:{claim.id}")
        incomplete = goal.status is GoalEvidenceStatus.UNKNOWN_INCOMPLETE
        if incomplete != (proposition.quantifier == "at_least"):
            violations.append(f"count_quantifier_mismatch:{claim.id}")
    elif claim.kind is ClaimKind.COUNT:
        violations.append(f"count_differs_from_authority:{claim.id}")
    if claim.kind is ClaimKind.CAUSE_HYPOTHESIS and not _has_causal_grade(goal):
        violations.append(f"cause_without_causal_evidence:{claim.id}")
    if claim.kind is not ClaimKind.CAUSE_HYPOTHESIS and proposition.modality == "hypothesis":
        violations.append(f"hypothesis_outside_cause_claim:{claim.id}")
    if (
        goal.possible_only
        and claim.kind is not ClaimKind.NEXT_CHECK
        and proposition.modality != "possible"
    ):
        violations.append(f"impact_stated_as_observed:{claim.id}")
    return violations


def _row_violations(claim: AnswerClaim, ctx: _Context) -> list[str]:
    """Every listed row must exist, and a non-count claim must name each one it lists."""

    violations: list[str] = []
    cited = [(ref.goal, ref.node) for ref in claim.refs]
    known = frozenset().union(*(ctx.rows.get(key, frozenset()) for key in cited))
    rendered = any(
        ref.node in ctx.goals[ref.goal].rendered_nodes
        for ref in claim.refs
        if ref.goal in ctx.goals
    )
    named = {item.ref.row for item in claim.literals}
    for row in claim.rows:
        if row not in known:
            violations.append(f"claim_row_unknown:{claim.id}")
        elif claim.kind is not ClaimKind.COUNT and not rendered and row not in named:
            violations.append(f"claim_row_unshown:{claim.id}")
    return violations


def _proposition_violations(claim: AnswerClaim, ctx: _Context) -> list[str]:
    proposition = claim.proposition
    violations: list[str] = []
    identities = _known_identity_values(ctx)
    for field_name in ("subject", "object"):
        value = getattr(proposition, field_name)
        if value is not None and value not in identities:
            violations.append(f"proposition_{field_name}_unresolved:{claim.id}")
    if proposition.predicate is not None and not any(
        ref.field is not None and proposition.predicate in ref.field for ref in claim.refs
    ):
        violations.append(f"proposition_predicate_unbacked:{claim.id}")
    if proposition.value is not None and not any(
        _same_proposition_value(_cell(ref, ctx.goals), proposition.value) for ref in claim.refs
    ):
        violations.append(f"proposition_value_mismatch:{claim.id}")
    for field_name in ("unit", "currency", "temporal_basis", "time_zone"):
        expected = getattr(proposition, field_name)
        if expected is not None and not any(
            _same_proposition_value(_cell(ref, ctx.goals), str(expected)) for ref in claim.refs
        ):
            violations.append(f"proposition_{field_name}_unbacked:{claim.id}")
    if proposition.causal_class != "none" and not any(
        _has_causal_grade(ctx.goals[ref.goal]) for ref in claim.refs if ref.goal in ctx.goals
    ):
        violations.append(f"proposition_causal_class_unbacked:{claim.id}")
    return violations


def _has_causal_grade(goal: GoalEvidence) -> bool:
    return goal.causal_evidence or any(
        supports_causal_hypothesis(receipt) for receipt in goal.causal_grade_receipts
    )


def _known_identity_values(ctx: _Context) -> set[str]:
    identities: set[str] = set()
    for goal in ctx.goals.values():
        for table in goal.tables.values():
            for row in table.rows:
                identities.add(row.row_id)
                for path in ("id", "object_type", "properties.name", "properties.id"):
                    value = _path(row.values, path)
                    if isinstance(value, str):
                        identities.add(value)
    return identities


def _coverage_violations(answer: ComposedAnswer, goals: Mapping[str, GoalEvidence]) -> list[str]:
    violations: list[str] = []
    stated = {
        code
        for claim in answer.claims
        if claim.kind is ClaimKind.LIMITATION
        for code in claim.limitation_codes
    }
    addressed = {ref.goal for claim in answer.claims for ref in claim.refs}
    for goal in goals.values():
        if goal.goal_id not in addressed and not set(goal.required_limitations) & stated:
            violations.append(f"goal_unaddressed:{goal.goal_id}")
        for code in goal.required_limitations:
            if code not in stated:
                violations.append(f"required_limitation_missing:{goal.goal_id}:{code}")
        if goal.authoritative_count is not None:
            continue
        named = {
            row
            for claim in answer.claims
            if any(ref.goal == goal.goal_id for ref in claim.refs)
            for row in claim.rows
        }
        for node_id, table in goal.tables.items():
            if node_id in goal.rendered_nodes:
                continue
            if any(row.row_id not in named for row in table.rows):
                violations.append(f"result_rows_unaccounted:{goal.goal_id}:{node_id}")
    return violations


def _undeclared_literals(
    answer: ComposedAnswer,
    ctx: _Context,
    known_identities: frozenset[str],
    utterance: str,
) -> list[str]:
    """Reject literal-shaped tokens that no evidence binding, restatement, or code covers.

    This lexes the model's output for validation only; it never infers meaning.
    """

    declared = [item.span for claim in answer.claims for item in claim.literals]
    restatements = [claim.span for claim in answer.claims if claim.kind is ClaimKind.RESTATEMENT]
    limitations = [claim.span for claim in answer.claims if claim.kind is ClaimKind.LIMITATION]
    asked = {token for _start, token in tokens(utterance)}
    parts = frozenset().union(*(code_parts(code) for code in ctx.required_codes))
    identities = set(known_identities)
    for goal in ctx.goals.values():
        for table in goal.tables.values():
            for row in table.rows:
                identities.add(row.row_id)
                name = _path(row.values, "properties.name")
                if isinstance(name, str):
                    identities.add(name)
    violations: list[str] = []
    for start, token in tokens(answer.text):
        if not literal_shaped(token, identities):
            continue
        span = AnswerClaimSpan(start=start, end=start + len(token))
        if any(_inside(span, item) for item in declared):
            continue
        if token in asked and any(_inside(span, item) for item in restatements):
            continue
        if token in parts and any(_inside(span, item) for item in limitations):
            continue
        violations.append(f"undeclared_literal:{start}")
    return violations


class _Missing:
    pass


_MISSING = _Missing()
_EMPTY = QueryTable(rows=(), complete=True)


def _cell(ref: EvidenceRef, goals: Mapping[str, GoalEvidence]) -> Any:
    goal = goals.get(ref.goal)
    table = goal.tables.get(ref.node) if goal is not None else None
    if table is None:
        return _MISSING
    if ref.row is None:
        return table if ref.field is None else _MISSING
    row = next((item for item in table.rows if item.row_id == ref.row), None)
    if row is None:
        return _MISSING
    if ref.field is None:
        return row.row_id
    return _path(row.values, ref.field)


def _path(values: Mapping[str, Any], dotted: str) -> Any:
    current: Any = values
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _same_value(cell: Any, value: str | int) -> bool:
    if isinstance(value, bool) or isinstance(cell, bool):
        return False
    if isinstance(value, int):
        return isinstance(cell, int) and cell == value
    return isinstance(cell, str) and cell == value


def _same_proposition_value(cell: Any, value: str | int | float | bool) -> bool:
    if cell is _MISSING:
        return False
    if isinstance(value, bool):
        return isinstance(cell, bool) and cell is value
    if isinstance(value, int) and not isinstance(value, bool):
        return isinstance(cell, int) and not isinstance(cell, bool) and cell == value
    if isinstance(value, float):
        return isinstance(cell, (int, float)) and not isinstance(cell, bool) and cell == value
    return isinstance(cell, str) and cell == value


def _inside(inner: SourceSpan, outer: SourceSpan) -> bool:
    return bool(outer.start <= inner.start and inner.end <= outer.end)


__all__ = [
    "MAX_ANSWER_CHARS",
    "AnswerClaim",
    "ClaimKind",
    "ClaimProposition",
    "ClaimVerdict",
    "ComposedAnswer",
    "EvidenceRef",
    "GoalEvidence",
    "GoalEvidenceStatus",
    "LiteralBinding",
    "verify_answer_claims",
]
