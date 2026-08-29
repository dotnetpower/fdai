"""Deterministic qualification reduction for measured ChatOps quality runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    ChatOpsQualityContract,
    QualityDimension,
    QualityHardCap,
    QualityItemMeasurement,
    score_quality_item,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
CHATOPS_QUALIFICATION_EVIDENCE_PURPOSE = "chatops-quality-qualification"


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    """Raw evidence state from which the reducer independently derives hard caps."""

    frozen_blind_corpus: bool
    production_e2e: bool
    latency_slo: bool
    complete_trace: bool
    critical_safety_escape: bool

    def __post_init__(self) -> None:
        values = (
            self.frozen_blind_corpus,
            self.production_e2e,
            self.latency_slo,
            self.complete_trace,
            self.critical_safety_escape,
        )
        if any(type(value) is not bool for value in values):
            raise ValueError("qualification evidence fields MUST be boolean")

    def hard_caps(self, *, corpus_meets_floor: bool) -> tuple[QualityHardCap, ...]:
        caps: list[QualityHardCap] = []
        if not self.frozen_blind_corpus or not corpus_meets_floor:
            caps.append(QualityHardCap.NO_FROZEN_BLIND_CORPUS)
        if not self.production_e2e:
            caps.append(QualityHardCap.NO_PRODUCTION_E2E_EVIDENCE)
        if not self.latency_slo or not self.complete_trace:
            caps.append(QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE)
        if self.critical_safety_escape:
            caps.append(QualityHardCap.CRITICAL_SAFETY_ESCAPE)
        return tuple(caps)


@dataclass(frozen=True, slots=True)
class QualificationItemObservation:
    """One measured item's six normalized components and raw evidence state."""

    item_id: int
    components: tuple[tuple[QualityDimension, float], ...]
    evidence: QualificationEvidence

    def __post_init__(self) -> None:
        QualityItemMeasurement(item_id=self.item_id, components=self.components)


@dataclass(frozen=True, slots=True)
class QualificationRun:
    """One complete, source-bound observation of all 50 rubric items."""

    run_id: str
    started_at: str
    completed_at: str
    items: tuple[QualificationItemObservation, ...]

    def __post_init__(self) -> None:
        _bounded_token(self.run_id, "run_id")
        started = _timestamp(self.started_at, "started_at")
        completed = _timestamp(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("qualification run completed_at MUST NOT precede started_at")
        item_ids = tuple(item.item_id for item in self.items)
        if item_ids != tuple(range(1, 51)):
            raise ValueError("qualification run MUST contain item ids 1 through 50 in order")


@dataclass(frozen=True, slots=True)
class QualificationCorpus:
    """Content-addressed corpus metadata without hidden prompts or labels."""

    corpus_id: str
    corpus_version: str
    content_digest: str
    turn_count: int
    english_turns: int
    korean_turns: int

    def __post_init__(self) -> None:
        _bounded_token(self.corpus_id, "corpus_id")
        _bounded_token(self.corpus_version, "corpus_version")
        _digest(self.content_digest, "corpus content_digest")
        counts = (self.turn_count, self.english_turns, self.korean_turns)
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("qualification corpus counts MUST be non-negative integers")
        if self.english_turns + self.korean_turns != self.turn_count:
            raise ValueError("qualification locale counts MUST equal turn_count")


@dataclass(frozen=True, slots=True)
class QualificationProvenance:
    """Pinned source and evaluator configuration for a qualification batch."""

    source_revision: str
    contract_version: str
    contract_digest: str
    runner_version: str
    evaluator_versions: tuple[str, ...]
    model_identifiers: tuple[str, ...]
    deployment_identifiers: tuple[str, ...]
    run_configuration_digest: str

    def __post_init__(self) -> None:
        if _REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("source_revision MUST be a full lowercase git object id")
        _bounded_token(self.contract_version, "contract_version")
        _digest(self.contract_digest, "contract_digest")
        _bounded_token(self.runner_version, "runner_version")
        _token_set(self.evaluator_versions, "evaluator_versions")
        _token_set(self.model_identifiers, "model_identifiers")
        _token_set(self.deployment_identifiers, "deployment_identifiers")
        _digest(self.run_configuration_digest, "run_configuration_digest")


@dataclass(frozen=True, slots=True)
class ChatOpsQualificationBatch:
    """Measured qualification input that carries no promotion or execution authority."""

    qualification_id: str
    provenance: QualificationProvenance
    corpus: QualificationCorpus
    runs: tuple[QualificationRun, ...]

    def __post_init__(self) -> None:
        _bounded_token(self.qualification_id, "qualification_id")
        if not self.runs:
            raise ValueError("qualification batch MUST contain at least one run")
        run_ids = tuple(run.run_id for run in self.runs)
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("qualification run_id values MUST be unique")


@dataclass(frozen=True, slots=True)
class QualificationRunScore:
    run_id: str
    weighted_score: float
    final_score: float
    applied_caps: tuple[QualityHardCap, ...]
    passed: bool


@dataclass(frozen=True, slots=True)
class QualificationItemResult:
    item_id: int
    name: str
    metric: str
    minimum_score: float
    run_scores: tuple[QualificationRunScore, ...]
    worst_score: float
    passed: bool


@dataclass(frozen=True, slots=True)
class ChatOpsQualificationScorecard:
    """Stable no-authority scorecard for an externally measured qualification batch."""

    qualification_id: str
    provenance: QualificationProvenance
    corpus: QualificationCorpus
    runs: tuple[QualificationRun, ...]
    items: tuple[QualificationItemResult, ...]
    run_count: int
    minimum_runs: int
    minimum_turns: int
    minimum_turns_per_locale: int
    decision_evidence_receipt_digest: str | None
    decision_evidence_verification_bundle_digest: str | None
    qualified: bool
    gaps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload["content_digest"] = hashlib.sha256(canonical.encode()).hexdigest()
        return payload

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "evidence_kind": "chatops_quality_qualification_scorecard",
            "qualification_authority": False,
            "qualification_id": self.qualification_id,
            "provenance": {
                "source_revision": self.provenance.source_revision,
                "contract_version": self.provenance.contract_version,
                "contract_digest": self.provenance.contract_digest,
                "runner_version": self.provenance.runner_version,
                "evaluator_versions": list(self.provenance.evaluator_versions),
                "model_identifiers": list(self.provenance.model_identifiers),
                "deployment_identifiers": list(self.provenance.deployment_identifiers),
                "run_configuration_digest": self.provenance.run_configuration_digest,
            },
            "corpus": {
                "corpus_id": self.corpus.corpus_id,
                "corpus_version": self.corpus.corpus_version,
                "content_digest": self.corpus.content_digest,
                "turn_count": self.corpus.turn_count,
                "english_turns": self.corpus.english_turns,
                "korean_turns": self.corpus.korean_turns,
            },
            "runs": [
                {
                    "run_id": run.run_id,
                    "started_at": run.started_at,
                    "completed_at": run.completed_at,
                }
                for run in self.runs
            ],
            "run_count": self.run_count,
            "decision_evidence_receipt_digest": self.decision_evidence_receipt_digest,
            "decision_evidence_verification_bundle_digest": (
                self.decision_evidence_verification_bundle_digest
            ),
            "requirements": {
                "minimum_runs": self.minimum_runs,
                "minimum_turns": self.minimum_turns,
                "minimum_turns_per_locale": self.minimum_turns_per_locale,
            },
            "items": [
                {
                    "item_id": item.item_id,
                    "name": item.name,
                    "metric": item.metric,
                    "minimum_score": item.minimum_score,
                    "run_scores": [
                        {
                            "run_id": score.run_id,
                            "weighted_score": score.weighted_score,
                            "final_score": score.final_score,
                            "applied_caps": [cap.value for cap in score.applied_caps],
                            "passed": score.passed,
                        }
                        for score in item.run_scores
                    ],
                    "worst_score": item.worst_score,
                    "passed": item.passed,
                }
                for item in self.items
            ],
            "qualified": self.qualified,
            "gaps": list(self.gaps),
        }


def evaluate_chatops_qualification(
    batch: ChatOpsQualificationBatch,
    *,
    contract: ChatOpsQualityContract = CHATOPS_QUALITY_CONTRACT_V1,
    decision_evidence: DecisionEvidenceAdmission | None = None,
    evaluated_at: datetime | None = None,
) -> ChatOpsQualificationScorecard:
    """Reduce measured runs and qualify only independently admitted evidence."""

    if batch.provenance.contract_version != contract.version:
        raise ValueError("qualification contract_version does not match the installed contract")
    if batch.provenance.contract_digest != contract.content_digest:
        raise ValueError("qualification contract_digest does not match the installed contract")

    corpus_meets_floor = (
        batch.corpus.turn_count >= contract.minimum_turns
        and batch.corpus.english_turns >= contract.minimum_turns_per_locale
        and batch.corpus.korean_turns >= contract.minimum_turns_per_locale
    )
    results: list[QualificationItemResult] = []
    for item in contract.items:
        run_scores: list[QualificationRunScore] = []
        for run in batch.runs:
            observation = run.items[item.item_id - 1]
            caps = observation.evidence.hard_caps(corpus_meets_floor=corpus_meets_floor)
            score = score_quality_item(
                QualityItemMeasurement(
                    item_id=item.item_id,
                    components=observation.components,
                    triggered_caps=caps,
                ),
                contract=contract,
            )
            run_scores.append(
                QualificationRunScore(
                    run_id=run.run_id,
                    weighted_score=score.weighted_score,
                    final_score=score.final_score,
                    applied_caps=score.applied_caps,
                    passed=score.passed,
                )
            )
        worst_score = min(score.final_score for score in run_scores)
        results.append(
            QualificationItemResult(
                item_id=item.item_id,
                name=item.name,
                metric=item.metric,
                minimum_score=item.minimum_score,
                run_scores=tuple(run_scores),
                worst_score=worst_score,
                passed=worst_score >= item.minimum_score,
            )
        )

    gaps: list[str] = []
    if len(batch.runs) < contract.minimum_runs:
        gaps.append(f"run_count={len(batch.runs)}<minimum_runs={contract.minimum_runs}")
    if batch.corpus.turn_count < contract.minimum_turns:
        gaps.append(f"turn_count={batch.corpus.turn_count}<minimum_turns={contract.minimum_turns}")
    if batch.corpus.english_turns < contract.minimum_turns_per_locale:
        gaps.append(
            "english_turns="
            f"{batch.corpus.english_turns}"
            f"<minimum_turns_per_locale={contract.minimum_turns_per_locale}"
        )
    if batch.corpus.korean_turns < contract.minimum_turns_per_locale:
        gaps.append(
            "korean_turns="
            f"{batch.corpus.korean_turns}"
            f"<minimum_turns_per_locale={contract.minimum_turns_per_locale}"
        )
    failed_items = [str(item.item_id) for item in results if not item.passed]
    if failed_items:
        gaps.append(f"items_below_threshold={','.join(failed_items)}")
    if decision_evidence is None:
        gaps.append("decision_evidence_admission_missing")
    elif evaluated_at is None:
        gaps.append("decision_evidence_evaluation_time_missing")
    else:
        reasons = assess_decision_evidence_admission(
            decision_evidence,
            expected_evidence_digest=chatops_qualification_evidence_digest(batch),
            expected_scope_digest=chatops_qualification_scope_digest(batch),
            expected_purpose_id=CHATOPS_QUALIFICATION_EVIDENCE_PURPOSE,
            expected_source_revision=batch.provenance.source_revision,
            evaluated_at=evaluated_at,
        )
        gaps.extend(f"decision_evidence_{reason.value}" for reason in reasons)

    return ChatOpsQualificationScorecard(
        qualification_id=batch.qualification_id,
        provenance=batch.provenance,
        corpus=batch.corpus,
        runs=batch.runs,
        items=tuple(results),
        run_count=len(batch.runs),
        minimum_runs=contract.minimum_runs,
        minimum_turns=contract.minimum_turns,
        minimum_turns_per_locale=contract.minimum_turns_per_locale,
        decision_evidence_receipt_digest=(
            decision_evidence.receipt_digest if decision_evidence is not None else None
        ),
        decision_evidence_verification_bundle_digest=(
            decision_evidence.verification_bundle_digest if decision_evidence is not None else None
        ),
        qualified=not gaps,
        gaps=tuple(gaps),
    )


def chatops_qualification_evidence_digest(batch: ChatOpsQualificationBatch) -> str:
    """Return the canonical digest of every qualification observation and input."""

    return content_digest(
        {
            "corpus": {
                "content_digest": batch.corpus.content_digest,
                "corpus_id": batch.corpus.corpus_id,
                "corpus_version": batch.corpus.corpus_version,
                "english_turns": batch.corpus.english_turns,
                "korean_turns": batch.corpus.korean_turns,
                "turn_count": batch.corpus.turn_count,
            },
            "provenance": {
                "contract_digest": batch.provenance.contract_digest,
                "contract_version": batch.provenance.contract_version,
                "deployment_identifiers": batch.provenance.deployment_identifiers,
                "evaluator_versions": batch.provenance.evaluator_versions,
                "model_identifiers": batch.provenance.model_identifiers,
                "run_configuration_digest": batch.provenance.run_configuration_digest,
                "runner_version": batch.provenance.runner_version,
                "source_revision": batch.provenance.source_revision,
            },
            "qualification_id": batch.qualification_id,
            "runs": [
                {
                    "completed_at": run.completed_at,
                    "items": [
                        {
                            "components": [
                                (dimension.value, value) for dimension, value in item.components
                            ],
                            "evidence": {
                                "complete_trace": item.evidence.complete_trace,
                                "critical_safety_escape": item.evidence.critical_safety_escape,
                                "frozen_blind_corpus": item.evidence.frozen_blind_corpus,
                                "latency_slo": item.evidence.latency_slo,
                                "production_e2e": item.evidence.production_e2e,
                            },
                            "item_id": item.item_id,
                        }
                        for item in run.items
                    ],
                    "run_id": run.run_id,
                    "started_at": run.started_at,
                }
                for run in batch.runs
            ],
        }
    )


def chatops_qualification_scope_digest(batch: ChatOpsQualificationBatch) -> str:
    """Return the decision scope bound to one corpus and qualification contract."""

    return content_digest(
        {
            "contract_version": batch.provenance.contract_version,
            "corpus_content_digest": batch.corpus.content_digest,
            "corpus_id": batch.corpus.corpus_id,
            "corpus_version": batch.corpus.corpus_version,
            "qualification_id": batch.qualification_id,
        }
    )


def _bounded_token(value: str, field: str) -> None:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be a bounded portable token")


def _digest(value: str, field: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be a lowercase SHA-256 digest")


def _token_set(values: tuple[str, ...], field: str) -> None:
    if not values or len(values) != len(set(values)):
        raise ValueError(f"{field} MUST contain unique values")
    for value in values:
        _bounded_token(value, field)


def _timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} MUST be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} MUST be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} MUST include a timezone")
    return parsed


__all__ = [
    "CHATOPS_QUALIFICATION_EVIDENCE_PURPOSE",
    "ChatOpsQualificationBatch",
    "ChatOpsQualificationScorecard",
    "QualificationCorpus",
    "QualificationEvidence",
    "QualificationItemObservation",
    "QualificationItemResult",
    "QualificationProvenance",
    "QualificationRun",
    "QualificationRunScore",
    "chatops_qualification_evidence_digest",
    "chatops_qualification_scope_digest",
    "evaluate_chatops_qualification",
]
