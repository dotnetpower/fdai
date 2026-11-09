"""Deterministic anti-hallucination guards for ontology planning, claims, and adjudication.

Enforces the 12-point anti-hallucination contract across FDAI's operating ontology:
1. V-PROV & V-LEVEL on compiled and legacy plans reject nil UUIDs and schema/instance confusion.
2. Subtractive-only rubric folding uses `min(aggregate_confidence, rubric_min_score)`.
3. Empty-result posture requires closed-population proof for `VERIFIED_EMPTY`;
   otherwise it returns `UNKNOWN_INCOMPLETE`.
4. Cross-authority adjudication withholds contested values and demotes the authority ceiling.
5. Gateway `as_of` cutoff binding and 3-axis bitemporal record window verification.
6. Causal attribution is blocked until competing hypotheses are refuted.
7. ResultSetHandle and cached-result Principal/purpose/source-state reauthorization.
8. Multi-format document distillation requires complete span accounting and 3-family consensus
   for PDF, Office, OCR, and Korean inputs.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from fdai.core.mscp_profile import MscpAuthorityCeiling

if TYPE_CHECKING:
    from fdai.core.conversation.epistemic_coverage import EpistemicStatus

_NIL_UUID_RE = re.compile(
    r"\b0{8}[-_:]0{4}[-_:]0{4}[-_:]0{4}[-_:]0{12}\b"
    r"|(?:^|[-_:])0{4,}$"
    r"|^<[^>]+>$"
    r"|^(?:unknown|null|none|todo|placeholder|example|dummy)$",
    re.I,
)
_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_REQUIRED_RUBRIC_CRITERIA = (
    "faithfulness",
    "evidence_action_alignment",
    "completeness",
    "reasoning_coherence",
)

AUTHORITY_PRECEDENCE: Mapping[str, int] = {
    "catalog_as_code": 100,
    "provider_observed": 90,
    "telemetry_observed": 90,
    "event_bus_registry": 85,
    "projection_owned": 80,
    "pantheon_owned": 75,
    "document_distilled": 60,
    "derived": 40,
}


@dataclass(frozen=True, slots=True)
class PlanGuardVerdict:
    """Outcome of V-PROV and V-LEVEL verification for a compiled or legacy plan."""

    accepted: bool
    violations: tuple[str, ...] = ()
    execution_authority: Literal[False] = False


def enforce_plan_operand_and_level_guard(
    *,
    goal_level: Literal["instance", "schema"],
    function_names: Sequence[str],
    operands: Sequence[str],
    grounded_operands: frozenset[str],
) -> PlanGuardVerdict:
    """Reject invented or nil-UUID operands and schema/instance confusion."""
    violations: list[str] = []
    schema_only_fns = {
        "query.manifest",
        "query.ontology_declaration",
        "query.ontology_relationships",
        "query.resource_class_closure",
    }
    for fn in function_names:
        if goal_level == "instance" and fn in schema_only_fns:
            violations.append(f"v_level_instance_goal_uses_schema_function:{fn}")
        elif goal_level == "schema" and fn not in schema_only_fns:
            violations.append(f"v_level_schema_goal_uses_instance_function:{fn}")

    for op in operands:
        norm = op.strip()
        if not norm:
            violations.append("v_prov_empty_operand")
            continue
        if _NIL_UUID_RE.search(norm) or norm == "0" * 32:
            violations.append(f"v_prov_nil_identifier_invented:{norm}")
            continue
        if norm not in grounded_operands:
            violations.append(f"v_prov_operand_without_source:{norm}")

    return PlanGuardVerdict(accepted=not violations, violations=tuple(violations))


@dataclass(frozen=True, slots=True)
class SubtractiveRubricVerdict:
    """Subtractive-only rubric folding result (`confidence <= aggregate_confidence`)."""

    decision: Literal["pass", "fail", "abstain", "disagree"]
    folded_confidence: float
    reasons: tuple[str, ...]
    execution_authority: Literal[False] = False


def evaluate_subtractive_rubric_enforcement(
    *,
    aggregate_confidence: float,
    criterion_scores: Mapping[str, float] | Sequence[tuple[str, float]],
    thresholds: Mapping[str, float],
    existing_reasons: Sequence[str] = (),
    proposer_publisher: str = "openai",
    judge_publisher: str = "anthropic",
) -> SubtractiveRubricVerdict:
    """Fold scores with `min()`, preserving `cross_check_below_quorum` as `disagree`."""
    reasons = list(existing_reasons)
    if (
        isinstance(aggregate_confidence, bool)
        or not math.isfinite(float(aggregate_confidence))
        or not (0.0 <= float(aggregate_confidence) <= 1.0)
    ):
        reasons.append("rubric_score_invalid_or_nonfinite")
        return SubtractiveRubricVerdict(
            decision="abstain",
            folded_confidence=0.0,
            reasons=tuple(dict.fromkeys(reasons)),
        )
    if not proposer_publisher.strip() or not judge_publisher.strip():
        reasons.append("rubric_publisher_missing")
        return SubtractiveRubricVerdict(
            decision="abstain",
            folded_confidence=0.0,
            reasons=tuple(dict.fromkeys(reasons)),
        )
    if proposer_publisher.strip().casefold() == judge_publisher.strip().casefold():
        reasons.append("rubric_judge_shares_proposer_publisher")
        return SubtractiveRubricVerdict(
            decision="abstain",
            folded_confidence=0.0,
            reasons=tuple(dict.fromkeys(reasons)),
        )
    if isinstance(criterion_scores, Mapping):
        pairs = list(criterion_scores.items())
    else:
        pairs = list(criterion_scores)
    keys = [str(k) for k, _ in pairs]
    if len(keys) != len(set(keys)) or any(k not in _REQUIRED_RUBRIC_CRITERIA for k in keys):
        reasons.append("rubric_duplicate_or_unknown_criterion")
        return SubtractiveRubricVerdict(
            decision="abstain",
            folded_confidence=0.0,
            reasons=tuple(dict.fromkeys(reasons)),
        )
    score_map: dict[str, float] = {}
    for k, raw_v in pairs:
        if (
            isinstance(raw_v, bool)
            or not math.isfinite(float(raw_v))
            or not (0.0 <= float(raw_v) <= 1.0)
        ):
            reasons.append("rubric_score_invalid_or_nonfinite")
            return SubtractiveRubricVerdict(
                decision="abstain",
                folded_confidence=0.0,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        score_map[str(k)] = float(raw_v)
    if any(c not in score_map for c in _REQUIRED_RUBRIC_CRITERIA):
        reasons.append("rubric_criterion_missing")
        return SubtractiveRubricVerdict(
            decision="abstain",
            folded_confidence=0.0,
            reasons=tuple(dict.fromkeys(reasons)),
        )
    min_score = min(score_map[c] for c in _REQUIRED_RUBRIC_CRITERIA)
    folded = max(0.0, min(float(aggregate_confidence), min_score))
    failed: list[str] = []
    for c in _REQUIRED_RUBRIC_CRITERIA:
        th = thresholds.get(c, 0.8)
        if isinstance(th, bool) or not math.isfinite(float(th)) or not (0.0 <= float(th) <= 1.0):
            reasons.append("rubric_threshold_invalid_or_nonfinite")
            return SubtractiveRubricVerdict(
                decision="abstain",
                folded_confidence=0.0,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        if score_map[c] < float(th):
            failed.append(f"rubric_below_threshold:{c}")
    reasons.extend(failed)
    if any(r.startswith("cross_check_below_quorum") for r in reasons):
        return SubtractiveRubricVerdict(
            decision="disagree",
            folded_confidence=folded,
            reasons=tuple(dict.fromkeys(reasons)),
        )
    if failed:
        return SubtractiveRubricVerdict(
            decision="fail",
            folded_confidence=folded,
            reasons=tuple(dict.fromkeys(reasons)),
        )
    return SubtractiveRubricVerdict(
        decision="pass",
        folded_confidence=folded,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def resolve_epistemic_empty_posture(
    *,
    row_count: int,
    source_complete: bool,
    truncated: bool,
    link_coverage_complete: bool,
    stale: bool = False,
    conflicting: bool = False,
) -> EpistemicStatus:
    """Prevent false-empty hallucination: `VERIFIED_EMPTY` requires closed-population proof."""
    from fdai.core.conversation.epistemic_coverage import EpistemicStatus

    if isinstance(row_count, bool) or row_count < 0:
        raise ValueError("row_count MUST be a non-negative integer")
    if conflicting:
        return EpistemicStatus.UNKNOWN_CONFLICT
    if stale:
        return EpistemicStatus.UNKNOWN_STALE
    if row_count > 0:
        return (
            EpistemicStatus.VERIFIED_ANSWER
            if (source_complete and not truncated and link_coverage_complete)
            else EpistemicStatus.QUALIFIED_ANSWER
        )
    if source_complete and not truncated and link_coverage_complete:
        return EpistemicStatus.VERIFIED_EMPTY
    return EpistemicStatus.UNKNOWN_INCOMPLETE


@dataclass(frozen=True, slots=True)
class CrossAuthorityAdjudicationResult:
    """Outcome of adjudicating independent observations across authority classes."""

    status: Literal["agreed", "subordinated_lower_authority", "contested_withheld"]
    resolved_value: Any | None
    withheld: bool
    conflicting_sources: tuple[str, ...]
    ceiling: MscpAuthorityCeiling
    execution_authority: Literal[False] = False


def adjudicate_cross_authority_observations(
    observations: Sequence[tuple[str, str, Any]],
) -> CrossAuthorityAdjudicationResult:
    """Adjudicate `(source_id, authority_class, value)` tuples without averaging or latest-wins."""
    if not observations:
        return CrossAuthorityAdjudicationResult(
            status="contested_withheld",
            resolved_value=None,
            withheld=True,
            conflicting_sources=(),
            ceiling=MscpAuthorityCeiling.HOLD,
        )
    by_source: dict[str, Any] = {}
    for src_id, auth_cls, val in observations:
        if not str(src_id).strip() or auth_cls not in AUTHORITY_PRECEDENCE:
            return CrossAuthorityAdjudicationResult(
                status="contested_withheld",
                resolved_value=None,
                withheld=True,
                conflicting_sources=tuple(
                    sorted({str(s) for s, _, _ in observations if str(s).strip()})
                ),
                ceiling=MscpAuthorityCeiling.HOLD,
            )
        if src_id in by_source and by_source[src_id] != val:
            return CrossAuthorityAdjudicationResult(
                status="contested_withheld",
                resolved_value=None,
                withheld=True,
                conflicting_sources=(src_id,),
                ceiling=MscpAuthorityCeiling.HOLD,
            )
        by_source[src_id] = val
    ranked = sorted(
        observations,
        key=lambda item: AUTHORITY_PRECEDENCE[item[1]],
        reverse=True,
    )
    top_rank = AUTHORITY_PRECEDENCE[ranked[0][1]]
    top_tier = [item for item in ranked if AUTHORITY_PRECEDENCE[item[1]] == top_rank]
    first_val = top_tier[0][2]
    if all(item[2] == first_val for item in top_tier):
        all_agree = all(item[2] == first_val for item in ranked)
        return CrossAuthorityAdjudicationResult(
            status="agreed" if all_agree else "subordinated_lower_authority",
            resolved_value=first_val,
            withheld=False,
            conflicting_sources=()
            if all_agree
            else tuple(sorted({item[0] for item in ranked if item[2] != first_val})),
            ceiling=MscpAuthorityCeiling.PRESERVE if all_agree else MscpAuthorityCeiling.HOLD,
        )
    return CrossAuthorityAdjudicationResult(
        status="contested_withheld",
        resolved_value=None,
        withheld=True,
        conflicting_sources=tuple(sorted({item[0] for item in top_tier})),
        ceiling=MscpAuthorityCeiling.HOLD,
    )


@dataclass(frozen=True, slots=True)
class GatewayAsOfBinding:
    """Bound gateway cutoff receipt rejecting stale or naive-timestamp temporal claims."""

    accepted: bool
    cutoff: datetime | None
    reason: str | None = None


def bind_gateway_as_of_cutoff(
    *,
    requested_as_of: datetime,
    gateway_now: datetime,
    max_skew_seconds: int = 30,
) -> GatewayAsOfBinding:
    """Verify timezone-awareness and freshness skew at anchor-binding time."""
    if isinstance(max_skew_seconds, bool) or max_skew_seconds < 1:
        raise ValueError("max_skew_seconds MUST be a positive integer")
    if requested_as_of.tzinfo is None or gateway_now.tzinfo is None:
        return GatewayAsOfBinding(False, None, "as_of_timezone_naive")
    skew = (gateway_now.astimezone(UTC) - requested_as_of.astimezone(UTC)).total_seconds()
    if skew < -5.0:
        return GatewayAsOfBinding(False, None, "as_of_in_future")
    if skew > float(max_skew_seconds):
        return GatewayAsOfBinding(False, None, "as_of_stale")
    return GatewayAsOfBinding(True, requested_as_of.astimezone(UTC), None)


def resolve_bitemporal_record_window(
    records: Sequence[Mapping[str, Any]],
    *,
    valid_at: datetime,
    known_at: datetime,
) -> tuple[Mapping[str, Any], ...]:
    """Filter by `effective_from`, `effective_to`, and `recorded_time` bounds."""
    if valid_at.tzinfo is None or known_at.tzinfo is None:
        raise ValueError("bitemporal query timestamps MUST be timezone-aware")
    matched: list[Mapping[str, Any]] = []
    for rec in records:
        eff_from = rec.get("effective_from")
        eff_to = rec.get("effective_to")
        rec_time = rec.get("recorded_time")
        if not isinstance(eff_from, datetime) or not isinstance(rec_time, datetime):
            continue
        if eff_from.tzinfo is None or rec_time.tzinfo is None:
            continue
        if eff_to is not None:
            if not isinstance(eff_to, datetime) or eff_to.tzinfo is None or eff_to < eff_from:
                continue
        if rec_time > known_at:
            continue
        if eff_from <= valid_at and (eff_to is None or valid_at < eff_to):
            matched.append(rec)
    return tuple(matched)


@dataclass(frozen=True, slots=True)
class CausalRefutationGateResult:
    """Result of verifying refutation reads and competing causal hypotheses before causal claims."""

    can_claim_cause: bool
    posture: Literal["verified_cause", "cause_hypothesis_only", "insufficient_refutation_reads"]
    unresolved_competitors: tuple[str, ...]


def verify_causal_competitor_refutation_gate(
    *,
    refutation_reads_completed: int,
    min_refutation_reads: int = 2,
    competitor_dispositions: Mapping[str, str],
) -> CausalRefutationGateResult:
    """Allow causal claim only when >=2 refutation reads ran and all competitors are `refuted`."""
    if isinstance(refutation_reads_completed, bool) or isinstance(min_refutation_reads, bool):
        raise ValueError("refutation read counts MUST be integers, not booleans")
    unresolved = tuple(
        sorted(cid for cid, disp in competitor_dispositions.items() if disp != "refuted")
    )
    if refutation_reads_completed < max(1, min_refutation_reads):
        return CausalRefutationGateResult(
            can_claim_cause=False,
            posture="insufficient_refutation_reads",
            unresolved_competitors=unresolved,
        )
    if unresolved or not competitor_dispositions:
        return CausalRefutationGateResult(
            can_claim_cause=False,
            posture="cause_hypothesis_only",
            unresolved_competitors=unresolved,
        )
    return CausalRefutationGateResult(
        can_claim_cause=True,
        posture="verified_cause",
        unresolved_competitors=(),
    )


def reauthorize_cached_or_handle_read(
    *,
    cached_principal_scope_digest: str,
    cached_purpose: str,
    cached_source_state_digest: str,
    current_principal_scope_digest: str,
    current_purpose: str,
    current_source_state_digest: str,
    expires_at: datetime,
    now: datetime,
    requested_row_ids: Sequence[str] = (),
    handle_row_ids: Sequence[str] = (),
) -> tuple[bool, str | None]:
    """Reauthorize a `ResultSetHandle` or cached graph read against current ACL/source state."""
    for dg in (
        cached_principal_scope_digest,
        cached_source_state_digest,
        current_principal_scope_digest,
        current_source_state_digest,
    ):
        if _DIGEST_RE.fullmatch(dg) is None:
            return False, "invalid_scope_or_source_digest"
    if expires_at.tzinfo is None or now.tzinfo is None:
        return False, "naive_expiry_timestamp"
    if now >= expires_at:
        return False, "prior_result_expired"
    if cached_principal_scope_digest != current_principal_scope_digest:
        return False, "prior_result_foreign_principal"
    if cached_purpose != current_purpose:
        return False, "prior_result_purpose_mismatch"
    if cached_source_state_digest != current_source_state_digest:
        return False, "prior_result_source_state_changed"
    if requested_row_ids:
        allowed_rows = set(handle_row_ids)
        if any(not str(r).strip() or r not in allowed_rows for r in requested_row_ids):
            return False, "prior_result_row_not_in_handle"
    return True, None


def verify_multiformat_distillation_conformance_gate(
    *,
    covered_partitions: Sequence[str],
    unaccounted_span_count: int,
    distinct_model_families: Sequence[str],
    agreeing_families_count: int,
) -> tuple[bool, str | None]:
    """Require full PDF/Office/OCR/Korean accounting and diverse 3-family consensus."""
    required = {"en_markdown", "en_native_pdf", "en_office", "ko_office", "ko_ocr_pdf"}
    missing = sorted(required - set(covered_partitions))
    if missing:
        return False, f"missing_required_partitions:{','.join(missing)}"
    if unaccounted_span_count > 0:
        return False, f"unaccounted_claim_spans:{unaccounted_span_count}"
    families = {f.strip().casefold() for f in distinct_model_families if f.strip()}
    if len(families) < 3:
        return False, "council_requires_three_distinct_model_families"
    if agreeing_families_count < 2:
        return False, "council_below_consensus_quorum"
    return True, None


__all__ = [
    "AUTHORITY_PRECEDENCE",
    "CausalRefutationGateResult",
    "CrossAuthorityAdjudicationResult",
    "GatewayAsOfBinding",
    "PlanGuardVerdict",
    "SubtractiveRubricVerdict",
    "adjudicate_cross_authority_observations",
    "bind_gateway_as_of_cutoff",
    "enforce_plan_operand_and_level_guard",
    "evaluate_subtractive_rubric_enforcement",
    "reauthorize_cached_or_handle_read",
    "resolve_bitemporal_record_window",
    "resolve_epistemic_empty_posture",
    "verify_causal_competitor_refutation_gate",
    "verify_multiformat_distillation_conformance_gate",
]
