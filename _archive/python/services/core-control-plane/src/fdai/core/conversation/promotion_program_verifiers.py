"""Deterministic, model-free verification and arbitration primitives for promotion readiness.

Covers the remaining local promotion-program verifiers:
- Item 27: compiled-plan role coverage verification (`verify_plan_role_coverage`).
- Item 28: terminal clarification hold guard (`enforce_terminal_clarification_hold`).
- Item 29: bounded single-sample release variance policy and closed third-family
  ambiguity arbitration (`evaluate_single_sample_variance_and_ambiguity`,
  `arbitrate_third_family_ambiguity`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

PLAN_CONSTRAINT_UNCOVERED = "semantic_plan_constraint_uncovered"
TERMINAL_CLARIFICATION_HOLD = "judgment_terminal_clarification"
MAX_SINGLE_SAMPLE_RESAMPLES = 1


class AmbiguityVerdict(StrEnum):
    """Closed verdict returned by the third-family ambiguity reader."""

    ONE = "one"
    MULTIPLE = "multiple"
    UNCLEAR = "unclear"


class SingleSampleFailureKind(StrEnum):
    """Closed failure categories for the first compilable form sample."""

    COMPETING_READING = "competing_reading"
    UNFAITHFUL_REVIEW = "unfaithful_review"
    DROPPED_OPERAND_REPAIR = "dropped_operand_repair"
    NON_RECOVERABLE_SCHEMA_ERROR = "non_recoverable_schema_error"


_RESAMPLE_ELIGIBLE_FAILURES = frozenset(
    {
        SingleSampleFailureKind.COMPETING_READING,
        SingleSampleFailureKind.UNFAITHFUL_REVIEW,
        SingleSampleFailureKind.DROPPED_OPERAND_REPAIR,
    }
)
_VALID_AMBIGUITY_VERDICTS = frozenset(item.value for item in AmbiguityVerdict)
_VALID_FAILURE_KINDS = frozenset(item.value for item in SingleSampleFailureKind)


def _normalize_role_tuple(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    cleaned: list[str] = []
    for item in values:
        if (
            not isinstance(item, str)
            or not item.strip()
            or len(item.strip()) > 256
            or any(ord(ch) < 32 for ch in item)
        ):
            raise ValueError("role values MUST be non-empty printable strings <= 256 chars")
        token = item.strip()
        if token not in cleaned:
            cleaned.append(token)
    return tuple(cleaned)


_READING_ROLE_FIELDS = (
    "hard_constraints",
    "measures",
    "groupings",
    "quantities",
    "relations",
    "location_restrictions",
    "lifecycle_restrictions",
    "time_restrictions",
)
_PLAN_ROLE_FIELDS = (
    "bound_predicates",
    "bound_measures",
    "bound_groupings",
    "bound_quantities",
    "bound_paths",
)


@dataclass(frozen=True, slots=True)
class BlindReadingRoleSpec:
    """Roles stated by the blind reading of an operator turn."""

    hard_constraints: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()
    groupings: tuple[str, ...] = ()
    quantities: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    location_restrictions: tuple[str, ...] = ()
    lifecycle_restrictions: tuple[str, ...] = ()
    time_restrictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in _READING_ROLE_FIELDS:
            object.__setattr__(self, name, _normalize_role_tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class CompiledPlanRoleBinding:
    """Roles bound into the compiled query plan."""

    bound_predicates: tuple[str, ...] = ()
    bound_measures: tuple[str, ...] = ()
    bound_groupings: tuple[str, ...] = ()
    bound_quantities: tuple[str, ...] = ()
    bound_paths: tuple[str, ...] = ()
    reads_only_filtered_list: bool = False

    def __post_init__(self) -> None:
        for name in _PLAN_ROLE_FIELDS:
            object.__setattr__(self, name, _normalize_role_tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class PlanRoleCoverageVerdict:
    """Outcome of verifying that a compiled plan covers all stated blind-reading roles."""

    covered: bool
    hold_reason: str | None
    uncovered_roles: tuple[str, ...]
    uncovered_operands: tuple[str, ...] = ()
    release_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "covered": self.covered,
            "hold_reason": self.hold_reason,
            "uncovered_roles": list(self.uncovered_roles),
            "uncovered_operands": list(self.uncovered_operands),
            "release_allowed": self.release_allowed,
        }


def _matches_restriction_binding(
    item: str, *, prefixes: tuple[str, ...], bound_values: frozenset[str]
) -> bool:
    return item in bound_values or any(f"{prefix}:{item}" in bound_values for prefix in prefixes)


def verify_plan_role_coverage(
    reading: BlindReadingRoleSpec | None = None,
    plan: CompiledPlanRoleBinding | None = None,
    **kwargs: Any,
) -> PlanRoleCoverageVerdict:
    """Verify that every role stated in the blind reading is bound in the compiled plan."""

    r = reading or BlindReadingRoleSpec(
        **{k: tuple(kwargs.get(k, ())) for k in _READING_ROLE_FIELDS}
    )
    p = plan or CompiledPlanRoleBinding(
        **{k: tuple(kwargs.get(k, ())) for k in _PLAN_ROLE_FIELDS},
        reads_only_filtered_list=bool(kwargs.get("reads_only_filtered_list", False)),
    )
    predicates = frozenset(p.bound_predicates)
    uncovered_roles: list[str] = []
    uncovered_operands: list[str] = []

    def _add(role_name: str, missing_items: Sequence[str]) -> None:
        if missing_items:
            uncovered_roles.append(role_name)
            uncovered_operands.extend(f"{role_name}:{item}" for item in missing_items)

    for role_name, declared, prefixes in (
        ("hard_constraints", r.hard_constraints, ("predicate", "hard")),
        ("location_restrictions", r.location_restrictions, ("location", "region")),
        ("lifecycle_restrictions", r.lifecycle_restrictions, ("lifecycle", "status", "state")),
        ("time_restrictions", r.time_restrictions, ("time", "window", "as_of")),
    ):
        missing = [
            x
            for x in declared
            if not _matches_restriction_binding(x, prefixes=prefixes, bound_values=predicates)
        ]
        _add(role_name, missing)

    for role_name, declared, bound_set in (
        ("measures", r.measures, frozenset(p.bound_measures)),
        ("groupings", r.groupings, frozenset(p.bound_groupings)),
        ("quantities", r.quantities, frozenset(p.bound_quantities)),
        ("relations", r.relations, frozenset(p.bound_paths)),
    ):
        missing = (
            list(declared)
            if p.reads_only_filtered_list
            else [x for x in declared if x not in bound_set]
        )
        _add(role_name, missing)

    if uncovered_roles:
        return PlanRoleCoverageVerdict(
            False,
            PLAN_CONSTRAINT_UNCOVERED,
            tuple(uncovered_roles),
            tuple(uncovered_operands),
            False,
        )
    return PlanRoleCoverageVerdict(True, None, (), (), True)


@dataclass(frozen=True, slots=True)
class TerminalClarificationDecision:
    """Decision enforcing that ambiguous or clarification judgments never reinterpret via frame."""

    terminal_clarification: bool
    allow_released_reading: bool
    allow_frame_reinterpretation: bool
    disposition: str
    clarification_prompt: str | None = None
    hold_reason: str | None = None


def _parse_ambiguity_verdict(
    verdict: Literal["one", "multiple", "unclear"] | AmbiguityVerdict | None, *, label: str
) -> AmbiguityVerdict | None:
    if verdict is None:
        return None
    raw = verdict.value if isinstance(verdict, AmbiguityVerdict) else str(verdict)
    if raw not in _VALID_AMBIGUITY_VERDICTS:
        raise ValueError(f"unsupported {label}: {verdict!r}")
    return AmbiguityVerdict(raw)


def _parse_failure_kind(
    failure: SingleSampleFailureKind | str | None, *, label: str
) -> SingleSampleFailureKind | None:
    if failure is None:
        return None
    raw = failure.value if isinstance(failure, SingleSampleFailureKind) else str(failure)
    if raw not in _VALID_FAILURE_KINDS:
        raise ValueError(f"unsupported {label}: {failure!r}")
    return SingleSampleFailureKind(raw)


def enforce_terminal_clarification_hold(
    *,
    is_clarification: bool,
    is_ambiguous: bool,
    clarification_prompt: str | None = None,
    has_released_reading: bool = False,
    third_family_verdict: Literal["one", "multiple", "unclear"] | AmbiguityVerdict | None = None,
) -> TerminalClarificationDecision:
    """Block frame reinterpretation on clarification/ambiguous judgment unless 3rd family is one."""
    if not all(
        isinstance(flag, bool) for flag in (is_clarification, is_ambiguous, has_released_reading)
    ):
        raise TypeError("clarification and reading flags MUST be booleans")
    normalized = _parse_ambiguity_verdict(third_family_verdict, label="third_family_verdict")
    if is_clarification or is_ambiguous:
        if has_released_reading and normalized is AmbiguityVerdict.ONE:
            return TerminalClarificationDecision(False, True, False, "released_reading")
        return TerminalClarificationDecision(
            True, False, False, "clarification", clarification_prompt, TERMINAL_CLARIFICATION_HOLD
        )
    if has_released_reading:
        return TerminalClarificationDecision(False, True, False, "released_reading")
    return TerminalClarificationDecision(False, False, True, "current_path_allowed")


@dataclass(frozen=True, slots=True)
class ThirdFamilyAmbiguityInput:
    """Closed third-family ambiguity reader input with only masked text and closed candidates."""

    primary_model_family: str
    secondary_model_family: str
    reader_model_family: str
    masked_utterance: str
    reading_candidates: tuple[str, ...]
    unmasked_utterance: str | None = None
    raw_evidence_rows: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        primary = self.primary_model_family.strip().casefold()
        secondary = self.secondary_model_family.strip().casefold()
        reader = self.reader_model_family.strip().casefold()
        if not primary or not secondary or not reader:
            raise ValueError("primary, secondary, and reader model families MUST be non-empty")
        if primary == secondary or reader in {primary, secondary}:
            raise ValueError(
                "reader_model_family MUST be distinct from both primary and secondary families"
            )
        if self.unmasked_utterance is not None or self.raw_evidence_rows:
            raise ValueError(
                "third-family ambiguity input MUST contain only masked_utterance and candidates"
            )
        if not isinstance(self.masked_utterance, str) or not self.masked_utterance.strip():
            raise ValueError("masked_utterance MUST be a non-empty masked string")
        normalized_candidates = _normalize_role_tuple(self.reading_candidates)
        if not normalized_candidates:
            raise ValueError("reading_candidates MUST contain at least one closed candidate")
        object.__setattr__(self, "reading_candidates", normalized_candidates)


@dataclass(frozen=True, slots=True)
class ThirdFamilyAmbiguityOutcome:
    """Closed verdict from the third-family ambiguity reader."""

    verdict: AmbiguityVerdict
    selected_reading: str | None
    clarification_preserved: bool
    release_allowed: bool


def arbitrate_third_family_ambiguity(
    ambiguity_input: ThirdFamilyAmbiguityInput,
    *,
    selected_candidates: Sequence[str] = (),
    selected_candidate: str | None = None,
    proposed_verdict: Literal["one", "multiple", "unclear"] | AmbiguityVerdict | None = None,
) -> ThirdFamilyAmbiguityOutcome:
    """Arbitrate closed reading candidates using an independent third model family."""

    if not isinstance(ambiguity_input, ThirdFamilyAmbiguityInput):
        raise TypeError("ambiguity_input MUST be a ThirdFamilyAmbiguityInput")
    chosen: list[str] = [selected_candidate] if selected_candidate is not None else []
    for item in selected_candidates:
        if item not in chosen:
            chosen.append(item)
    allowed_candidates = frozenset(ambiguity_input.reading_candidates)
    for item in chosen:
        if item not in allowed_candidates:
            raise ValueError(f"selected candidate {item!r} is not in closed reading_candidates")

    explicit_verdict = _parse_ambiguity_verdict(proposed_verdict, label="proposed_verdict")
    if len(chosen) > 1 or explicit_verdict is AmbiguityVerdict.MULTIPLE:
        return ThirdFamilyAmbiguityOutcome(AmbiguityVerdict.MULTIPLE, None, True, False)
    if len(chosen) == 1 and explicit_verdict in {None, AmbiguityVerdict.ONE}:
        return ThirdFamilyAmbiguityOutcome(AmbiguityVerdict.ONE, chosen[0], False, True)
    return ThirdFamilyAmbiguityOutcome(AmbiguityVerdict.UNCLEAR, None, True, False)


@dataclass(frozen=True, slots=True)
class VarianceAndAmbiguityEvaluation:
    """Combined outcome of single-sample resample policy and third-family ambiguity arbitration."""

    should_resample: bool
    resamples_taken: int
    max_resamples: int
    has_released_reading: bool
    ambiguity_verdict: AmbiguityVerdict | None
    selected_reading: str | None
    terminal_clarification: bool
    allow_released_reading: bool
    allow_frame_reinterpretation: bool
    disposition: str
    hold_reason: str | None


def evaluate_single_sample_variance_and_ambiguity(
    *,
    first_sample_compilable: bool = True,
    first_failure_kind: SingleSampleFailureKind | str | None = None,
    resamples_already_taken: int = 0,
    second_sample_released: bool = False,
    second_failure_kind: SingleSampleFailureKind | str | None = None,
    judgment_is_clarification: bool = False,
    judgment_is_ambiguous: bool = False,
    clarification_prompt: str | None = None,
    ambiguity_input: ThirdFamilyAmbiguityInput | None = None,
    selected_candidates: Sequence[str] = (),
    selected_candidate: str | None = None,
    proposed_ambiguity_verdict: (
        Literal["one", "multiple", "unclear"] | AmbiguityVerdict | None
    ) = None,
) -> VarianceAndAmbiguityEvaluation:
    """Evaluate bounded single-resample recovery and optional third-family ambiguity arbitration."""

    if (
        type(resamples_already_taken) is not int
        or not 0 <= resamples_already_taken <= MAX_SINGLE_SAMPLE_RESAMPLES
    ):
        raise ValueError(f"resamples_already_taken MUST be 0..{MAX_SINGLE_SAMPLE_RESAMPLES}")
    first_failure = _parse_failure_kind(first_failure_kind, label="first_failure_kind")
    second_failure = _parse_failure_kind(second_failure_kind, label="second_failure_kind")

    should_resample = (
        first_sample_compilable
        and first_failure in _RESAMPLE_ELIGIBLE_FAILURES
        and resamples_already_taken < MAX_SINGLE_SAMPLE_RESAMPLES
    )
    resamples_taken = 1 if should_resample else 0
    if first_sample_compilable and first_failure is None:
        has_released_reading = True
    elif should_resample:
        has_released_reading = bool(second_sample_released and second_failure is None)
    else:
        has_released_reading = False

    ambiguity_outcome = (
        arbitrate_third_family_ambiguity(
            ambiguity_input,
            selected_candidates=selected_candidates,
            selected_candidate=selected_candidate,
            proposed_verdict=proposed_ambiguity_verdict,
        )
        if ambiguity_input is not None
        else None
    )
    verdict = ambiguity_outcome.verdict if ambiguity_outcome is not None else None
    selected_reading = ambiguity_outcome.selected_reading if ambiguity_outcome is not None else None

    if judgment_is_clarification or judgment_is_ambiguous:
        decision = enforce_terminal_clarification_hold(
            is_clarification=judgment_is_clarification,
            is_ambiguous=judgment_is_ambiguous,
            clarification_prompt=clarification_prompt,
            has_released_reading=has_released_reading,
            third_family_verdict=verdict,
        )
        return VarianceAndAmbiguityEvaluation(
            should_resample,
            resamples_taken,
            MAX_SINGLE_SAMPLE_RESAMPLES,
            has_released_reading,
            verdict,
            selected_reading if decision.allow_released_reading else None,
            decision.terminal_clarification,
            decision.allow_released_reading,
            decision.allow_frame_reinterpretation,
            decision.disposition,
            decision.hold_reason,
        )

    hold_reason = (
        None
        if has_released_reading
        else (
            second_failure.value
            if should_resample and second_failure is not None
            else (first_failure.value if first_failure is not None else "uncompilable_first_sample")
        )
    )
    return VarianceAndAmbiguityEvaluation(
        should_resample,
        resamples_taken,
        MAX_SINGLE_SAMPLE_RESAMPLES,
        has_released_reading,
        verdict,
        selected_reading,
        False,
        has_released_reading,
        False,
        "released_reading" if has_released_reading else "held",
        hold_reason,
    )


__all__ = [
    "MAX_SINGLE_SAMPLE_RESAMPLES",
    "PLAN_CONSTRAINT_UNCOVERED",
    "TERMINAL_CLARIFICATION_HOLD",
    "AmbiguityVerdict",
    "BlindReadingRoleSpec",
    "CompiledPlanRoleBinding",
    "PlanRoleCoverageVerdict",
    "SingleSampleFailureKind",
    "TerminalClarificationDecision",
    "ThirdFamilyAmbiguityInput",
    "ThirdFamilyAmbiguityOutcome",
    "VarianceAndAmbiguityEvaluation",
    "arbitrate_third_family_ambiguity",
    "enforce_terminal_clarification_hold",
    "evaluate_single_sample_variance_and_ambiguity",
    "verify_plan_role_coverage",
]
