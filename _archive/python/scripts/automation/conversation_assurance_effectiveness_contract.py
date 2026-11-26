"""Owner-only contracts for conversation-assurance effectiveness evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fdai.core.conversation_assurance import read_private_text
from fdai.core.conversation_assurance.pantheon_ledger import (
    write_private_text_exclusive,
)
from scripts.automation.conversation_assurance_answer_gate import (
    MANDATORY_RUBRIC_NAMES,
    RUBRIC_NAMES,
    RUBRIC_VERSION,
)

_DIGEST = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")
_REVISION = re.compile(r"^[a-f0-9]{40}$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_IDENTITY_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_GIT_REF = re.compile(r"^(?!.*(?:\.\.|@\{|//))[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_MAX_BYTES = 1024 * 1024
_Z_95 = 1.959963984540054


def canonical_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class EffectivenessPolicy:
    schema_version: str
    policy_id: str
    cohort_id: str
    authoritative_base_ref: str
    required_locales: tuple[str, ...]
    minimum_pairs: int
    minimum_pairs_per_locale: int
    minimum_improvement_rate: float
    minimum_pair_ratio_delta: float
    confidence_level: float
    maximum_regressions: int
    maximum_environment_hold_rate: float
    maximum_latency_ms_per_measured_run: int
    maximum_model_calls_per_measured_run: float
    maximum_cost_usd_per_measured_run: float

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("effectiveness policy schema version is unsupported")
        if any(_TOKEN.fullmatch(value) is None for value in (self.policy_id, self.cohort_id)):
            raise ValueError("effectiveness policy identity MUST be bounded")
        if _GIT_REF.fullmatch(self.authoritative_base_ref) is None:
            raise ValueError("effectiveness policy base ref is invalid")
        if (
            self.authoritative_base_ref == "HEAD"
            or _REVISION.fullmatch(self.authoritative_base_ref) is not None
        ):
            raise ValueError("effectiveness policy requires a named base ref")
        if (
            not self.required_locales
            or len(self.required_locales) != len(set(self.required_locales))
            or any(_TOKEN.fullmatch(value) is None for value in self.required_locales)
        ):
            raise ValueError("effectiveness policy locales MUST be unique bounded tokens")
        if self.required_locales != ("en", "ko"):
            raise ValueError("effectiveness policy locales MUST be canonical English and Korean")
        if not 2 <= self.minimum_pairs <= 10_000:
            raise ValueError("effectiveness minimum pairs MUST be in [2, 10000]")
        if not 1 <= self.minimum_pairs_per_locale <= self.minimum_pairs:
            raise ValueError("effectiveness locale minimum is invalid")
        if self.minimum_pairs_per_locale * len(self.required_locales) > self.minimum_pairs:
            raise ValueError("effectiveness locale floors exceed the cohort minimum")
        for value, name in (
            (self.minimum_improvement_rate, "improvement rate"),
            (self.minimum_pair_ratio_delta, "pair ratio delta"),
            (self.maximum_environment_hold_rate, "environment hold rate"),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"effectiveness {name} MUST be in [0, 1]")
        if self.minimum_pair_ratio_delta <= 0:
            raise ValueError("effectiveness pair ratio delta MUST be positive")
        if self.confidence_level != 0.95:
            raise ValueError("effectiveness policy supports confidence level 0.95 only")
        if not 0 <= self.maximum_regressions <= self.minimum_pairs:
            raise ValueError("effectiveness maximum regressions is invalid")
        if self.maximum_latency_ms_per_measured_run < 1:
            raise ValueError("effectiveness latency ceiling MUST be positive")
        for value, name in (
            (self.maximum_model_calls_per_measured_run, "model call ceiling"),
            (self.maximum_cost_usd_per_measured_run, "cost ceiling"),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"effectiveness {name} MUST be finite and positive")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EffectivenessPolicy:
        locales = value.get("required_locales")
        if not isinstance(locales, list) or any(not isinstance(item, str) for item in locales):
            raise ValueError("effectiveness policy locales are invalid")
        return cls(
            schema_version=_string(value, "schema_version"),
            policy_id=_string(value, "policy_id"),
            cohort_id=_string(value, "cohort_id"),
            authoritative_base_ref=_string(value, "authoritative_base_ref"),
            required_locales=tuple(locales),
            minimum_pairs=_integer(value, "minimum_pairs"),
            minimum_pairs_per_locale=_integer(value, "minimum_pairs_per_locale"),
            minimum_improvement_rate=_number(value, "minimum_improvement_rate"),
            minimum_pair_ratio_delta=_number(value, "minimum_pair_ratio_delta"),
            confidence_level=_number(value, "confidence_level"),
            maximum_regressions=_integer(value, "maximum_regressions"),
            maximum_environment_hold_rate=_number(value, "maximum_environment_hold_rate"),
            maximum_latency_ms_per_measured_run=_integer(
                value, "maximum_latency_ms_per_measured_run"
            ),
            maximum_model_calls_per_measured_run=_number(
                value, "maximum_model_calls_per_measured_run"
            ),
            maximum_cost_usd_per_measured_run=_number(value, "maximum_cost_usd_per_measured_run"),
        )

    @property
    def content_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class EffectivenessAssessment:
    schema_version: str
    run_id: str
    case_id: str
    question_fingerprint: str
    measurement_revision: str
    trace_receipt_digest: str
    locale: str
    rubric_version: str
    measurement_profile_digest: str
    evidence_snapshot_digest: str
    total_score: int
    max_score: int
    mandatory_gate_passed: bool
    objective_oracle_applicable: bool
    objective_oracle_passed: bool
    hard_zero_count: int
    technical_verified: bool
    failed_rubrics: tuple[str, ...]
    mandatory_gate_failures: tuple[str, ...]
    latency_ms: int
    model_call_count: int
    cost_usd: float | None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("effectiveness assessment schema version is unsupported")
        for value in (self.run_id, self.case_id, self.locale, self.rubric_version):
            if _TOKEN.fullmatch(value) is None:
                raise ValueError("effectiveness assessment tokens MUST be bounded")
        if (
            _DIGEST.fullmatch(self.question_fingerprint) is None
            or _DIGEST.fullmatch(self.trace_receipt_digest) is None
            or _REVISION.fullmatch(self.measurement_revision) is None
        ):
            raise ValueError("effectiveness assessment lineage is invalid")
        if self.rubric_version != RUBRIC_VERSION:
            raise ValueError("effectiveness assessment rubric version is unsupported")
        for value in (self.measurement_profile_digest, self.evidence_snapshot_digest):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError("effectiveness assessment digests MUST be SHA-256")
        if not 0 <= self.total_score <= self.max_score or self.max_score < 1:
            raise ValueError("effectiveness assessment score is invalid")
        if self.objective_oracle_applicable and not self.objective_oracle_passed:
            if self.mandatory_gate_passed:
                raise ValueError("a failed objective oracle cannot pass the mandatory gate")
        if self.hard_zero_count < 0:
            raise ValueError("effectiveness hard-zero count MUST be non-negative")
        if any(_TOKEN.fullmatch(value) is None for value in self.failed_rubrics):
            raise ValueError("effectiveness failed rubrics MUST be bounded tokens")
        if (
            len(self.failed_rubrics) != len(set(self.failed_rubrics))
            or any(value not in RUBRIC_NAMES for value in self.failed_rubrics)
            or len(self.failed_rubrics) != self.max_score - self.total_score
        ):
            raise ValueError("effectiveness failed rubrics are inconsistent")
        allowed_mandatory_failures = {*MANDATORY_RUBRIC_NAMES, "objective_oracle"}
        if (
            len(self.mandatory_gate_failures) != len(set(self.mandatory_gate_failures))
            or any(
                value not in allowed_mandatory_failures for value in self.mandatory_gate_failures
            )
            or self.mandatory_gate_passed != (not self.mandatory_gate_failures)
        ):
            raise ValueError("effectiveness mandatory gate evidence is inconsistent")
        failed_mandatory_rubrics = set(self.failed_rubrics) & MANDATORY_RUBRIC_NAMES
        if not failed_mandatory_rubrics.issubset(self.mandatory_gate_failures):
            raise ValueError("effectiveness mandatory rubric failure is missing")
        oracle_failed = "objective_oracle" in self.mandatory_gate_failures
        if (
            not self.objective_oracle_applicable
            and (not self.objective_oracle_passed or oracle_failed)
        ) or (self.objective_oracle_applicable and self.objective_oracle_passed == oracle_failed):
            raise ValueError("effectiveness objective oracle evidence is inconsistent")
        if self.technical_verified != ("verification" not in self.mandatory_gate_failures):
            raise ValueError("effectiveness technical verification is inconsistent")
        if self.latency_ms < 0 or self.model_call_count < 0:
            raise ValueError("effectiveness performance metrics MUST be non-negative")
        if self.cost_usd is not None and (not math.isfinite(self.cost_usd) or self.cost_usd < 0):
            raise ValueError("effectiveness cost MUST be finite and non-negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EffectivenessAssessment:
        failed = value.get("failed_rubrics")
        if not isinstance(failed, list) or any(not isinstance(item, str) for item in failed):
            raise ValueError("effectiveness failed rubrics are invalid")
        mandatory_failures = value.get("mandatory_gate_failures")
        if not isinstance(mandatory_failures, list) or any(
            not isinstance(item, str) for item in mandatory_failures
        ):
            raise ValueError("effectiveness mandatory gate failures are invalid")
        raw_cost = value.get("cost_usd")
        return cls(
            schema_version=_string(value, "schema_version"),
            run_id=_string(value, "run_id"),
            case_id=_string(value, "case_id"),
            question_fingerprint=_string(value, "question_fingerprint"),
            measurement_revision=_string(value, "measurement_revision"),
            trace_receipt_digest=_string(value, "trace_receipt_digest"),
            locale=_string(value, "locale"),
            rubric_version=_string(value, "rubric_version"),
            measurement_profile_digest=_string(value, "measurement_profile_digest"),
            evidence_snapshot_digest=_string(value, "evidence_snapshot_digest"),
            total_score=_integer(value, "total_score"),
            max_score=_integer(value, "max_score"),
            mandatory_gate_passed=_boolean(value, "mandatory_gate_passed"),
            objective_oracle_applicable=_boolean(value, "objective_oracle_applicable"),
            objective_oracle_passed=_boolean(value, "objective_oracle_passed"),
            hard_zero_count=_integer(value, "hard_zero_count"),
            technical_verified=_boolean(value, "technical_verified"),
            failed_rubrics=tuple(failed),
            mandatory_gate_failures=tuple(mandatory_failures),
            latency_ms=_integer(value, "latency_ms"),
            model_call_count=_integer(value, "model_call_count"),
            cost_usd=(None if raw_cost is None else _strict_number(raw_cost, "cost_usd")),
        )

    @property
    def assurance_passed(self) -> bool:
        oracle_passed = not self.objective_oracle_applicable or self.objective_oracle_passed
        return (
            self.total_score / self.max_score >= 0.9
            and self.mandatory_gate_passed
            and oracle_passed
            and self.hard_zero_count == 0
            and self.technical_verified
        )

    @property
    def content_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class RemediationEvidence:
    schema_version: str
    run_id: str
    source_revision: str
    remediation_revision: str
    changed_paths_digest: str
    changed_path_count: int
    validation_receipt_digest: str
    hardening_digest: str
    owning_paths: tuple[str, ...]
    task_owned_only: bool

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("remediation evidence schema version is unsupported")
        if _TOKEN.fullmatch(self.run_id) is None:
            raise ValueError("remediation evidence run id MUST be bounded")
        if any(
            _REVISION.fullmatch(value) is None
            for value in (self.source_revision, self.remediation_revision)
        ):
            raise ValueError("remediation evidence revisions MUST be Git SHAs")
        for value in (
            self.changed_paths_digest,
            self.validation_receipt_digest,
            self.hardening_digest,
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError("remediation evidence digests MUST be SHA-256")
        if self.changed_path_count < 1:
            raise ValueError("remediation evidence requires changed paths")
        if not self.owning_paths or any(
            not path or path.startswith("/") or ".." in Path(path).parts
            for path in self.owning_paths
        ):
            raise ValueError("remediation owning paths MUST be relative repository paths")
        if self.owning_paths != tuple(sorted(set(self.owning_paths))):
            raise ValueError("remediation owning paths MUST be sorted and unique")
        if not self.task_owned_only:
            raise ValueError("remediation evidence cannot admit unrelated paths")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RemediationEvidence:
        paths = value.get("owning_paths")
        if not isinstance(paths, list) or any(not isinstance(item, str) for item in paths):
            raise ValueError("remediation owning paths are invalid")
        return cls(
            schema_version=_string(value, "schema_version"),
            run_id=_string(value, "run_id"),
            source_revision=_string(value, "source_revision"),
            remediation_revision=_string(value, "remediation_revision"),
            changed_paths_digest=_string(value, "changed_paths_digest"),
            changed_path_count=_integer(value, "changed_path_count"),
            validation_receipt_digest=_string(value, "validation_receipt_digest"),
            hardening_digest=_string(value, "hardening_digest"),
            owning_paths=tuple(paths),
            task_owned_only=_boolean(value, "task_owned_only"),
        )

    @property
    def content_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class PairCustodyReceipt:
    schema_version: str
    receipt_id: str
    policy_digest: str
    cohort_id: str
    comparison_group_id: str
    authoritative_base_ref: str
    declared_revision: str
    baseline_corpus_digest: str
    holdout_corpus_digest: str
    custodian_identity_digest: str
    locale: str
    suite: str
    expected_primary_agent: str
    expected_routing_method: str
    t2_expectation: str
    challenge_family: str
    objective_oracle: str
    content_disclosed_to_repair_agent: bool
    qualification_authority: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("pair custody schema version is unsupported")
        if _TOKEN.fullmatch(self.receipt_id) is None:
            raise ValueError("pair custody receipt id MUST be bounded")
        for value in (
            self.cohort_id,
            self.comparison_group_id,
            self.locale,
            self.suite,
            self.expected_routing_method,
            self.t2_expectation,
            self.challenge_family,
            self.objective_oracle,
        ):
            if _TOKEN.fullmatch(value) is None:
                raise ValueError("pair custody contract tokens MUST be bounded")
        if _IDENTITY_TOKEN.fullmatch(self.expected_primary_agent) is None:
            raise ValueError("pair custody expected agent MUST be bounded")
        if (
            _GIT_REF.fullmatch(self.authoritative_base_ref) is None
            or self.authoritative_base_ref == "HEAD"
            or _REVISION.fullmatch(self.authoritative_base_ref) is not None
        ):
            raise ValueError("pair custody base ref is invalid")
        if _REVISION.fullmatch(self.declared_revision) is None:
            raise ValueError("pair custody revision MUST be a Git SHA")
        for value in (
            self.policy_digest,
            self.baseline_corpus_digest,
            self.holdout_corpus_digest,
            self.custodian_identity_digest,
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError("pair custody digests MUST be SHA-256")
        if self.baseline_corpus_digest == self.holdout_corpus_digest:
            raise ValueError("pair custody requires distinct baseline and holdout corpora")
        if self.custodian_identity_digest in {
            self.policy_digest,
            self.baseline_corpus_digest,
            self.holdout_corpus_digest,
        }:
            raise ValueError("pair custody identity digest MUST be independent")
        if self.content_disclosed_to_repair_agent:
            raise ValueError("a disclosed holdout cannot claim blind custody")
        if self.qualification_authority or self.execution_authority:
            raise ValueError("pair custody grants no qualification or execution authority")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PairCustodyReceipt:
        return cls(
            schema_version=_string(value, "schema_version"),
            receipt_id=_string(value, "receipt_id"),
            policy_digest=_string(value, "policy_digest"),
            cohort_id=_string(value, "cohort_id"),
            comparison_group_id=_string(value, "comparison_group_id"),
            authoritative_base_ref=_string(value, "authoritative_base_ref"),
            declared_revision=_string(value, "declared_revision"),
            baseline_corpus_digest=_string(value, "baseline_corpus_digest"),
            holdout_corpus_digest=_string(value, "holdout_corpus_digest"),
            custodian_identity_digest=_string(value, "custodian_identity_digest"),
            locale=_string(value, "locale"),
            suite=_string(value, "suite"),
            expected_primary_agent=_string(value, "expected_primary_agent"),
            expected_routing_method=_string(value, "expected_routing_method"),
            t2_expectation=_string(value, "t2_expectation"),
            challenge_family=_string(value, "challenge_family"),
            objective_oracle=_string(value, "objective_oracle"),
            content_disclosed_to_repair_agent=_boolean(value, "content_disclosed_to_repair_agent"),
            qualification_authority=_boolean(value, "qualification_authority"),
            execution_authority=_boolean(value, "execution_authority"),
        )

    @property
    def content_digest(self) -> str:
        return canonical_digest(asdict(self))


def read_policy(path: Path) -> EffectivenessPolicy:
    return EffectivenessPolicy.from_mapping(_private_mapping(path))


def write_policy(path: Path, policy: EffectivenessPolicy) -> None:
    _write_contract(path, asdict(policy))


def read_assessment(path: Path) -> EffectivenessAssessment:
    return EffectivenessAssessment.from_mapping(_private_mapping(path))


def read_remediation_evidence(path: Path) -> RemediationEvidence:
    return RemediationEvidence.from_mapping(_private_mapping(path))


def read_pair_custody_receipt(path: Path) -> PairCustodyReceipt:
    return PairCustodyReceipt.from_mapping(_private_mapping(path))


def write_assessment(path: Path, assessment: EffectivenessAssessment) -> None:
    _write_contract(path, asdict(assessment))


def write_remediation_evidence(path: Path, evidence: RemediationEvidence) -> None:
    _write_contract(path, asdict(evidence))


def write_pair_custody_receipt(path: Path, receipt: PairCustodyReceipt) -> None:
    _write_contract(path, asdict(receipt))


def compose_assessment(
    *,
    run_id: str,
    case_id: str,
    question_fingerprint: str,
    measurement_revision: str,
    locale: str,
    answer_gate: Mapping[str, object],
    browser_evidence: Mapping[str, object],
) -> EffectivenessAssessment:
    mandatory = answer_gate.get("mandatory_gate")
    if not isinstance(mandatory, Mapping):
        raise ValueError("effectiveness answer gate is invalid")
    oracle = mandatory.get("objective_oracle")
    if not isinstance(oracle, Mapping):
        raise ValueError("effectiveness objective oracle is invalid")
    mandatory_failures = mandatory.get("failures")
    if not isinstance(mandatory_failures, list) or any(
        not isinstance(item, str) for item in mandatory_failures
    ):
        raise ValueError("effectiveness mandatory gate failures are invalid")
    rubrics = answer_gate.get("rubrics")
    if not isinstance(rubrics, list):
        raise ValueError("effectiveness rubric evidence is invalid")
    failed: list[str] = []
    scores: list[int | None] = []
    rubric_names: list[str] = []
    for item in rubrics:
        if not isinstance(item, Mapping):
            raise ValueError("effectiveness rubric evidence is invalid")
        name = item.get("name")
        score = item.get("score")
        if not isinstance(name, str) or isinstance(score, bool) or score not in {0, 1, None}:
            raise ValueError("effectiveness rubric evidence is invalid")
        if score == 0:
            failed.append(name)
        rubric_names.append(name)
        scores.append(score)
    if tuple(rubric_names) != RUBRIC_NAMES:
        raise ValueError("effectiveness rubrics MUST use canonical order")
    total_score = _integer(answer_gate, "total_score")
    max_score = _integer(answer_gate, "max_score")
    if total_score != sum(item or 0 for item in scores) or max_score != sum(
        item is not None for item in scores
    ):
        raise ValueError("effectiveness answer gate totals are inconsistent")
    raw_cost = browser_evidence.get("cost_usd")
    return EffectivenessAssessment(
        schema_version="1.0.0",
        run_id=run_id,
        case_id=case_id,
        question_fingerprint=question_fingerprint,
        measurement_revision=measurement_revision,
        trace_receipt_digest=_string(browser_evidence, "trace_receipt_digest"),
        locale=locale,
        rubric_version=_string(answer_gate, "rubric_version"),
        measurement_profile_digest=_string(browser_evidence, "measurement_profile_digest"),
        evidence_snapshot_digest=_string(browser_evidence, "evidence_snapshot_digest"),
        total_score=total_score,
        max_score=max_score,
        mandatory_gate_passed=_mapping_boolean(mandatory, "passed"),
        objective_oracle_applicable=_mapping_boolean(oracle, "applicable"),
        objective_oracle_passed=_mapping_boolean(oracle, "passed"),
        hard_zero_count=_integer(browser_evidence, "hard_zero_count"),
        technical_verified=_boolean(answer_gate, "technical_verified"),
        failed_rubrics=tuple(failed),
        mandatory_gate_failures=tuple(mandatory_failures),
        latency_ms=_integer(browser_evidence, "latency_ms"),
        model_call_count=_integer(browser_evidence, "model_call_count"),
        cost_usd=(None if raw_cost is None else _strict_number(raw_cost, "cost_usd")),
    )


def wilson_lower_bound(*, successes: int, trials: int) -> float | None:
    if trials == 0:
        return None
    proportion = successes / trials
    denominator = 1 + (_Z_95**2 / trials)
    centre = proportion + (_Z_95**2 / (2 * trials))
    margin = _Z_95 * math.sqrt(
        (proportion * (1 - proportion) / trials) + (_Z_95**2 / (4 * trials**2))
    )
    return max(0.0, (centre - margin) / denominator)


def _private_mapping(path: Path) -> dict[str, object]:
    try:
        value = json.loads(read_private_text(path, max_bytes=_MAX_BYTES))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("effectiveness private contract is invalid") from error
    if not isinstance(value, Mapping):
        raise ValueError("effectiveness private contract is invalid")
    return {str(key): item for key, item in value.items()}


def _write_contract(path: Path, value: Mapping[str, Any]) -> None:
    content = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    write_private_text_exclusive(path, content, max_bytes=_MAX_BYTES)


def _string(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str):
        raise ValueError(f"effectiveness {name} MUST be a string")
    return item


def _integer(value: Mapping[str, object], name: str) -> int:
    item = value.get(name)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"effectiveness {name} MUST be an integer")
    return item


def _number(value: Mapping[str, object], name: str) -> float:
    return _strict_number(value.get(name), name)


def _strict_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"effectiveness {name} MUST be numeric")
    return float(value)


def _boolean(value: Mapping[str, object], name: str) -> bool:
    item = value.get(name)
    if type(item) is not bool:
        raise ValueError(f"effectiveness {name} MUST be boolean")
    return item


def _mapping_boolean(value: Mapping[object, object], name: str) -> bool:
    item = value.get(name)
    if type(item) is not bool:
        raise ValueError(f"effectiveness {name} MUST be boolean")
    return item


__all__ = [
    "EffectivenessAssessment",
    "EffectivenessPolicy",
    "PairCustodyReceipt",
    "RemediationEvidence",
    "canonical_digest",
    "compose_assessment",
    "read_assessment",
    "read_policy",
    "read_pair_custody_receipt",
    "read_remediation_evidence",
    "wilson_lower_bound",
    "write_assessment",
    "write_policy",
    "write_pair_custody_receipt",
    "write_remediation_evidence",
]
