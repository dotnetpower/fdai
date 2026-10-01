"""Off-path Bragi semantic-routing training contract.

The records in this module are inert model-quality evidence. They never alter
Bragi's runtime router; activation requires a separate reviewed composition
input outside this helper.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fdai.agents._framework.pantheon import PANTHEON_NAMES, PANTHEON_SPECS
from fdai.agents._framework.topics import stable_idempotency_key

_MAX_CORPUS_RECORDS = 256
_MAX_HOLDOUT_CASES = 128
_MAX_EVIDENCE_REFS = 16
_MAX_REF_CHARS = 160
_CONTRACT_VERSION = "bragi-intent-training/v1"
_SHA_PREFIX = "sha256:"
_VALID_SOURCES = frozenset(
    {
        "post_turn_review_correction",
        "norns_semantic_feedback",
        "human_resolved_abstention",
    }
)


class IntentTrainingEvaluator(Protocol):
    """Deterministic off-path evaluator for one inert Bragi candidate revision."""

    def evaluate(
        self,
        *,
        baseline_revision: Mapping[str, Any],
        candidate_revision: Mapping[str, Any],
        holdout_cases: Sequence[IntentTrainingEvidence],
    ) -> Sequence[IntentTrainingEvaluationResult]:
        """Return one deterministic result per holdout case."""
        ...


@dataclass(frozen=True, slots=True)
class IntentTrainingEvidence:
    """One consent-filtered, digest-only verified routing outcome."""

    evidence_id: str
    source_kind: str
    principal_scope_digest: str
    consent_ref: str
    input_digest: str
    baseline_owner: str | None
    corrected_owner: str
    baseline_intent: str | None = None
    corrected_intent: str | None = None
    corrected_object_type: str | None = None
    targeted: bool = False
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("training evidence_id MUST be non-empty")
        if self.source_kind not in _VALID_SOURCES:
            raise ValueError("training evidence source_kind is not supported")
        _require_digest(self.principal_scope_digest, "principal_scope_digest")
        if not self.consent_ref.strip():
            raise ValueError("training evidence MUST carry an explicit consent_ref")
        _require_digest(self.input_digest, "input_digest")
        if self.baseline_owner is not None and self.baseline_owner not in PANTHEON_NAMES:
            raise ValueError("training baseline_owner MUST be a Pantheon agent")
        if self.corrected_owner not in PANTHEON_NAMES:
            raise ValueError("training corrected_owner MUST be a Pantheon agent")
        if self.corrected_intent is None and self.corrected_object_type is None:
            raise ValueError("training evidence MUST correct an intent or object type")
        if self.corrected_intent is not None and self.corrected_object_type is not None:
            raise ValueError("training evidence MUST correct exactly one routing signal")
        if len(self.evidence_refs) > _MAX_EVIDENCE_REFS or any(
            not ref.strip() or len(ref) > _MAX_REF_CHARS for ref in self.evidence_refs
        ):
            raise ValueError("training evidence_refs MUST be bounded")
        if not _owner_has_signal(
            self.corrected_owner,
            corrected_intent=self.corrected_intent,
            corrected_object_type=self.corrected_object_type,
        ):
            raise ValueError("training correction MUST match the owner's declared routing signal")


@dataclass(frozen=True, slots=True)
class IntentTrainingEvaluationResult:
    """Deterministic evaluator result for one frozen holdout case."""

    evidence_id: str
    baseline_owner: str | None
    candidate_owner: str | None
    expected_owner: str

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evaluation evidence_id MUST be non-empty")
        if self.baseline_owner is not None and self.baseline_owner not in PANTHEON_NAMES:
            raise ValueError("evaluation baseline_owner MUST be a Pantheon agent")
        if self.candidate_owner is not None and self.candidate_owner not in PANTHEON_NAMES:
            raise ValueError("evaluation candidate_owner MUST be a Pantheon agent")
        if self.expected_owner not in PANTHEON_NAMES:
            raise ValueError("evaluation expected_owner MUST be a Pantheon agent")


@dataclass(frozen=True, slots=True)
class ReviewedIntentTrainingPromotion:
    """External reviewed input allowing a passed candidate to become shadow-ready."""

    review_id: str
    reviewer_principal_digest: str
    approval_ref: str

    def __post_init__(self) -> None:
        if not self.review_id.strip() or not self.approval_ref.strip():
            raise ValueError("promotion review_id and approval_ref MUST be non-empty")
        _require_digest(self.reviewer_principal_digest, "reviewer_principal_digest")


@dataclass(frozen=True, slots=True)
class IntentTrainingRun:
    """Complete inert training result and Bragi-owned audit payload."""

    run_id: str
    payload: dict[str, Any]
    candidate_revision: dict[str, Any] | None
    gate_passed: bool
    published: bool


def build_unbound_training_payload(*, reason: str) -> dict[str, Any]:
    """Return visible no-op evidence for an unbound off-path dependency."""

    run_id = _run_id(("unbound", reason))
    corpus_digest = _digest_value(("unbound", reason))
    candidate_digest = _digest_value(("no-candidate", reason))
    return _base_payload(
        run_id=run_id,
        idempotency_parts=("unbound", reason),
        corpus_digest=corpus_digest,
        candidate_digest=candidate_digest,
        stages={
            "corpus_selection": {
                "status": "no_op",
                "reason": reason,
                "selected_count": 0,
            },
            "candidate_construction": {"status": "not_run"},
            "regression_gate": {"status": "not_run"},
            "promotion_decision": {
                "status": "held",
                "reason": "training_evaluator_unbound",
                "runtime_routing_authority_changed": False,
            },
        },
    )


def evaluate_training_contract(
    corpus: Sequence[IntentTrainingEvidence],
    *,
    evaluator: IntentTrainingEvaluator,
    reviewed_promotion: ReviewedIntentTrainingPromotion | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    """Build and gate one deterministic shadow-only routing evidence revision."""

    selected = _select_corpus(corpus)
    candidate = _candidate_revision(selected)
    corpus_digest = _corpus_digest(selected)
    holdout = tuple(item for item in selected if not item.targeted)
    target_cases = tuple(item for item in selected if item.targeted)
    if not holdout or not target_cases:
        payload = _payload_for_hold(
            selected=selected,
            candidate=candidate,
            corpus_digest=corpus_digest,
            reason="requires_holdout_and_targeted_cases",
        )
        return payload, candidate, False
    results = tuple(
        evaluator.evaluate(
            baseline_revision=_baseline_revision(),
            candidate_revision=candidate,
            holdout_cases=(*holdout, *target_cases),
        )
    )
    gate = _gate_results(results, holdout=holdout, target_cases=target_cases)
    promotion = _promotion_stage(gate, reviewed_promotion=reviewed_promotion)
    run_id = _run_id(tuple(item.evidence_id for item in selected))
    payload = _base_payload(
        run_id=run_id,
        idempotency_parts=("evaluated", tuple(item.evidence_id for item in selected)),
        corpus_digest=corpus_digest,
        candidate_digest=str(candidate["candidate_digest"]),
        stages={
            "corpus_selection": _corpus_stage(selected),
            "candidate_construction": {
                "status": "constructed",
                "candidate_digest": candidate["candidate_digest"],
                "revision": candidate["revision"],
                "entry_count": len(candidate["calibration_entries"]),
                "runtime_routing_authority_changed": False,
            },
            "regression_gate": gate,
            "promotion_decision": promotion,
        },
    )
    return payload, candidate, gate["status"] == "passed"


def _select_corpus(corpus: Sequence[IntentTrainingEvidence]) -> tuple[IntentTrainingEvidence, ...]:
    if len(corpus) > _MAX_CORPUS_RECORDS:
        raise ValueError("training corpus exceeds the bounded record limit")
    if not corpus:
        raise ValueError("training corpus MUST be non-empty")
    selected = tuple(sorted(corpus, key=lambda item: item.evidence_id))
    principal_scopes = {item.principal_scope_digest for item in selected}
    if len(principal_scopes) != len(selected):
        raise ValueError("training corpus MUST not contain duplicate principal scopes")
    return selected


def _candidate_revision(selected: Sequence[IntentTrainingEvidence]) -> dict[str, Any]:
    counts: Counter[tuple[str, str, str]] = Counter()
    lineage: dict[str, list[str]] = {}
    for item in selected:
        signal_kind, signal_value = _signal(item)
        key = (signal_kind, signal_value, item.corrected_owner)
        counts[key] += 1
        lineage.setdefault("|".join(key), []).append(item.input_digest)
    entries = tuple(
        {
            "signal_kind": signal_kind,
            "signal_value": signal_value,
            "owner": owner,
            "support_count": count,
            "lineage_digests": tuple(sorted(lineage["|".join((signal_kind, signal_value, owner))])),
            "authority": "calibration_evidence_only",
        }
        for (signal_kind, signal_value, owner), count in sorted(counts.items())
    )
    digest = hashlib.sha256(_canonical_json({"entries": entries}).encode()).hexdigest()
    return {
        "contract_version": _CONTRACT_VERSION,
        "revision": f"candidate:sha256:{digest}",
        "candidate_digest": f"sha256:{digest}",
        "calibration_entries": list(entries),
        "runtime_routing_authority_changed": False,
        "activation_authority": False,
    }


def _gate_results(
    results: Sequence[IntentTrainingEvaluationResult],
    *,
    holdout: Sequence[IntentTrainingEvidence],
    target_cases: Sequence[IntentTrainingEvidence],
) -> dict[str, Any]:
    if len(results) > _MAX_HOLDOUT_CASES:
        raise ValueError("training evaluation exceeds the bounded holdout limit")
    by_id = {item.evidence_id: item for item in results}
    expected_ids = {item.evidence_id for item in (*holdout, *target_cases)}
    if set(by_id) != expected_ids:
        raise ValueError("training evaluator MUST return exactly one result per case")
    regressions = tuple(
        item.evidence_id
        for item in holdout
        if by_id[item.evidence_id].baseline_owner == item.corrected_owner
        and by_id[item.evidence_id].candidate_owner != item.corrected_owner
    )
    improvements = tuple(
        item.evidence_id
        for item in target_cases
        if by_id[item.evidence_id].baseline_owner != item.corrected_owner
        and by_id[item.evidence_id].candidate_owner == item.corrected_owner
    )
    status = "passed" if not regressions and len(improvements) == len(target_cases) else "failed"
    return {
        "status": status,
        "holdout_count": len(holdout),
        "targeted_count": len(target_cases),
        "regression_count": len(regressions),
        "improvement_count": len(improvements),
        "regression_case_ids": list(regressions),
        "improved_case_ids": list(improvements),
        "runtime_routing_authority_changed": False,
    }


def _promotion_stage(
    gate: Mapping[str, Any],
    *,
    reviewed_promotion: ReviewedIntentTrainingPromotion | None,
) -> dict[str, Any]:
    if gate.get("status") != "passed":
        return {
            "status": "held",
            "reason": "regression_gate_failed",
            "shadow_only": True,
            "runtime_routing_authority_changed": False,
        }
    if reviewed_promotion is None:
        return {
            "status": "held",
            "reason": "requires_explicit_reviewed_promotion_input",
            "shadow_only": True,
            "runtime_routing_authority_changed": False,
        }
    return {
        "status": "shadow_ready",
        "review_id": reviewed_promotion.review_id,
        "approval_ref": reviewed_promotion.approval_ref,
        "reviewer_principal_digest": reviewed_promotion.reviewer_principal_digest,
        "shadow_only": True,
        "activation_authority": False,
        "runtime_routing_authority_changed": False,
    }


def _payload_for_hold(
    *,
    selected: Sequence[IntentTrainingEvidence],
    candidate: Mapping[str, Any],
    corpus_digest: str,
    reason: str,
) -> dict[str, Any]:
    run_id = _run_id(tuple(item.evidence_id for item in selected))
    return _base_payload(
        run_id=run_id,
        idempotency_parts=("held", tuple(item.evidence_id for item in selected), reason),
        corpus_digest=corpus_digest,
        candidate_digest=str(candidate["candidate_digest"]),
        stages={
            "corpus_selection": _corpus_stage(selected),
            "candidate_construction": {
                "status": "constructed",
                "candidate_digest": candidate["candidate_digest"],
                "revision": candidate["revision"],
                "entry_count": len(candidate["calibration_entries"]),
                "runtime_routing_authority_changed": False,
            },
            "regression_gate": {"status": "not_run", "reason": reason},
            "promotion_decision": {
                "status": "held",
                "reason": reason,
                "shadow_only": True,
                "runtime_routing_authority_changed": False,
            },
        },
    )


def _corpus_stage(selected: Sequence[IntentTrainingEvidence]) -> dict[str, Any]:
    return {
        "status": "selected",
        "contract_version": _CONTRACT_VERSION,
        "selected_count": len(selected),
        "max_records": _MAX_CORPUS_RECORDS,
        "selection_rules": {
            "sources": sorted(_VALID_SOURCES),
            "consent_required": True,
            "principal_scope": "sha256_digest_only",
            "raw_bodies_allowed": False,
            "lineage": "digest_only",
        },
        "source_counts": dict(Counter(item.source_kind for item in selected)),
        "targeted_count": sum(1 for item in selected if item.targeted),
        "evidence_refs": sorted({ref for item in selected for ref in item.evidence_refs}),
    }


def _base_payload(
    *,
    run_id: str,
    idempotency_parts: Sequence[Any],
    corpus_digest: str,
    candidate_digest: str,
    stages: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "producer_principal": "Bragi",
        "kind": "bragi_intent_training_evidence",
        "id": run_id,
        "correlation_id": run_id,
        "idempotency_key": stable_idempotency_key(
            "bragi-intent-training",
            *idempotency_parts,
        ),
        "contract_version": _CONTRACT_VERSION,
        "corpus_digest": corpus_digest,
        "candidate_digest": candidate_digest,
        "mode": "off_path_shadow",
        "authority": {
            "routes_runtime_traffic": False,
            "grants_action_authority": False,
            "self_promotion": False,
            "requires_reviewed_promotion_input": True,
        },
        "stages": dict(stages),
    }


def _baseline_revision() -> dict[str, Any]:
    return {
        "contract_version": _CONTRACT_VERSION,
        "revision": "runtime-current",
        "runtime_routing_authority_changed": False,
    }


def _signal(item: IntentTrainingEvidence) -> tuple[Literal["question_domain", "object_type"], str]:
    if item.corrected_intent is not None:
        return "question_domain", item.corrected_intent
    if item.corrected_object_type is None:
        raise ValueError("training evidence MUST contain one corrected signal")
    return "object_type", item.corrected_object_type


def _owner_has_signal(
    owner: str,
    *,
    corrected_intent: str | None,
    corrected_object_type: str | None,
) -> bool:
    spec = next(spec for spec in PANTHEON_SPECS if spec.name == owner)
    if corrected_intent is not None:
        return corrected_intent in spec.question_domains
    if corrected_object_type is not None:
        return corrected_object_type in spec.owns
    return False


def _require_digest(value: str, field_name: str) -> None:
    if not value.startswith(_SHA_PREFIX) or len(value) != len(_SHA_PREFIX) + 64:
        raise ValueError(f"{field_name} MUST be a sha256 digest")
    int(value.removeprefix(_SHA_PREFIX), 16)


def _corpus_digest(selected: Sequence[IntentTrainingEvidence]) -> str:
    entries = tuple(
        {
            "evidence_id": item.evidence_id,
            "source_kind": item.source_kind,
            "principal_scope_digest": item.principal_scope_digest,
            "input_digest": item.input_digest,
            "baseline_owner": item.baseline_owner,
            "corrected_owner": item.corrected_owner,
            "baseline_intent": item.baseline_intent,
            "corrected_intent": item.corrected_intent,
            "corrected_object_type": item.corrected_object_type,
            "targeted": item.targeted,
            "evidence_refs": item.evidence_refs,
        }
        for item in selected
    )
    return _digest_value(entries)


def _digest_value(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _run_id(parts: Sequence[object]) -> str:
    digest = hashlib.sha256(_canonical_json(tuple(parts)).encode()).hexdigest()
    return f"bragi-intent-training-{digest[:32]}"


def _canonical_json(value: object) -> str:
    import json

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


__all__ = [
    "IntentTrainingEvaluator",
    "IntentTrainingEvaluationResult",
    "IntentTrainingEvidence",
    "IntentTrainingRun",
    "ReviewedIntentTrainingPromotion",
    "build_unbound_training_payload",
    "evaluate_training_contract",
]
