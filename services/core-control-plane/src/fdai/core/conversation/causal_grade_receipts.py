"""Deterministic causal-grade receipts for causal context answers."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import CausalEvidenceGrade

# Required evidence the receipt's own checks prove; any other required item must be named
# as present, so a mechanism never grades on evidence nobody read.
_CHECKED_EVIDENCE = frozenset(
    {
        "complete_activity_window",
        "complete_state_transition_window",
        "confounder_check",
        "mechanism_operation_evidence",
        "repeated_samples",
        "reverse_direction_check",
    }
)
_GRADE_RANK = {
    CausalEvidenceGrade.ASSOCIATION: 0,
    CausalEvidenceGrade.PREDICTIVE_PRECEDENCE: 1,
    CausalEvidenceGrade.QUASI_EXPERIMENTAL: 2,
    CausalEvidenceGrade.INTERVENTIONAL: 3,
}


@dataclass(frozen=True, slots=True)
class CausalMechanismSpec:
    """Reviewed causal mechanism entry with required and refuting reads."""

    mechanism_id: str
    required_evidence: tuple[str, ...]
    refutation_reads: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.mechanism_id.strip():
            raise ValueError("causal mechanism id MUST be non-empty")
        if not self.required_evidence or not self.refutation_reads:
            raise ValueError("causal mechanism requires support and refutation reads")
        if self.required_evidence != tuple(sorted(set(self.required_evidence))):
            raise ValueError("causal mechanism required evidence MUST be sorted and unique")
        if self.refutation_reads != tuple(sorted(set(self.refutation_reads))):
            raise ValueError("causal mechanism refutation reads MUST be sorted and unique")


@dataclass(frozen=True, slots=True)
class CausalGradeReceipt:
    """Verified grade and accounting for one causal mechanism candidate."""

    mechanism_id: str
    grade: CausalEvidenceGrade
    repeated_sample_count: int
    reverse_direction_checked: bool
    confounder_checked: bool
    complete_windows: bool
    mechanism_evidence_refs: tuple[str, ...]
    refutation_refs: tuple[str, ...]
    missing_refutation_reads: tuple[str, ...]
    receipt_digest: str
    # Refutation reads neither run nor reported missing, and reads that refuted the mechanism.
    unaccounted_refutation_reads: tuple[str, ...] = ()
    refuted_reads: tuple[str, ...] = ()


def causal_grade_receipt(
    *,
    mechanism: CausalMechanismSpec,
    repeated_sample_count: int,
    reverse_direction_checked: bool,
    confounder_checked: bool,
    complete_windows: bool,
    mechanism_evidence_refs: tuple[str, ...],
    refutation_refs: tuple[str, ...],
    missing_refutation_reads: tuple[str, ...] = (),
    refutation_reads_run: tuple[str, ...] = (),
    refuted_reads: tuple[str, ...] = (),
    present_evidence: tuple[str, ...] = (),
) -> CausalGradeReceipt:
    """Grade support only when every E8 precondition is present.

    Every refutation read the mechanism names is either run, with or without refuting
    the mechanism, or reported missing; a read that refutes it, a missing one, or one
    left unaccounted keeps the grade at association.
    """

    support = tuple(sorted(set(mechanism_evidence_refs)))
    refutations = tuple(sorted(set(refutation_refs)))
    missing = tuple(sorted(set(missing_refutation_reads)))
    refuted = tuple(sorted(set(refuted_reads)))
    accounted = set(refutation_reads_run) | set(missing)
    unaccounted = tuple(sorted(set(mechanism.refutation_reads) - accounted))
    unproven = set(mechanism.required_evidence) - _CHECKED_EVIDENCE - set(present_evidence)
    if repeated_sample_count < 1:
        raise ValueError("causal grade repeated_sample_count MUST be positive")
    grade = (
        CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
        if repeated_sample_count >= 2
        and reverse_direction_checked
        and confounder_checked
        and complete_windows
        and support
        and refutations
        and not missing
        and not unaccounted
        and not refuted
        and not unproven
        else CausalEvidenceGrade.ASSOCIATION
    )
    body = {
        "mechanism_id": mechanism.mechanism_id,
        "grade": grade.value,
        "repeated_sample_count": repeated_sample_count,
        "reverse_direction_checked": reverse_direction_checked,
        "confounder_checked": confounder_checked,
        "complete_windows": complete_windows,
        "mechanism_evidence_refs": support,
        "refutation_refs": refutations,
        "missing_refutation_reads": missing,
        "unaccounted_refutation_reads": unaccounted,
        "refuted_reads": refuted,
    }
    return CausalGradeReceipt(
        mechanism_id=mechanism.mechanism_id,
        grade=grade,
        repeated_sample_count=repeated_sample_count,
        reverse_direction_checked=reverse_direction_checked,
        confounder_checked=confounder_checked,
        complete_windows=complete_windows,
        mechanism_evidence_refs=support,
        refutation_refs=refutations,
        missing_refutation_reads=missing,
        receipt_digest=content_digest(body),
        unaccounted_refutation_reads=unaccounted,
        refuted_reads=refuted,
    )


def load_causal_mechanism_catalog(raw: object) -> tuple[CausalMechanismSpec, ...]:
    """Load reviewed mechanism specs from rule-catalog data."""

    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValueError("causal mechanism catalog schema_version MUST be 1.0")
    mechanisms = raw.get("mechanisms")
    if not isinstance(mechanisms, list):
        raise ValueError("causal mechanism catalog mechanisms MUST be a list")
    loaded: list[CausalMechanismSpec] = []
    for item in mechanisms:
        if not isinstance(item, dict):
            raise ValueError("causal mechanism entries MUST be objects")
        loaded.append(
            CausalMechanismSpec(
                mechanism_id=_text(item, "id"),
                required_evidence=tuple(sorted(_string_list(item, "required_evidence"))),
                refutation_reads=tuple(sorted(_string_list(item, "refutation_reads"))),
            )
        )
    ids = tuple(item.mechanism_id for item in loaded)
    if ids != tuple(sorted(set(ids))):
        raise ValueError("causal mechanism ids MUST be sorted and unique")
    return tuple(loaded)


def supports_causal_hypothesis(receipt: CausalGradeReceipt) -> bool:
    """Return whether the grade may back a P3 causal hypothesis claim."""

    return _GRADE_RANK[receipt.grade] >= _GRADE_RANK[CausalEvidenceGrade.PREDICTIVE_PRECEDENCE]


def _text(item: dict[str, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"causal mechanism {key} MUST be non-empty text")
    return value


def _string_list(item: dict[str, object], key: str) -> list[str]:
    value = item.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(entry, str) or not entry.strip() for entry in value)
    ):
        raise ValueError(f"causal mechanism {key} MUST be non-empty text list")
    return value


__all__ = [
    "CausalGradeReceipt",
    "CausalMechanismSpec",
    "causal_grade_receipt",
    "load_causal_mechanism_catalog",
    "supports_causal_hypothesis",
]
