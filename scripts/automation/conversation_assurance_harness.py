"""Resumable state contract for one conversation-improvement run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

_DIGEST = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")
_REVISION = re.compile(r"^[a-f0-9]{40}$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_MIN_HARDENING_ROUNDS = 10
_FORBIDDEN_CASE_IDS = frozenset({"held-terminal-fidelity-heimdall-en-2"})
_TRAJECTORY_PHASE_ORDER = (
    "input",
    "plan",
    "collaboration",
    "evidence",
    "verification",
    "answer",
)
_TRAJECTORY_PHASES = frozenset(_TRAJECTORY_PHASE_ORDER)
_TOKEN_SIMILARITY_LIMIT = 0.85
_NON_CODE_REASON_PREFIXES = (
    "provider_",
    "evidence_",
    "evaluator_",
    "authorization_",
    "auth_",
    "operator_",
    "challenge_",
    "measurement_contract_",
)


class ImprovementState(StrEnum):
    PREPARED = "prepared"
    DRY_RUN_VALIDATED = "dry_run_validated"
    BROWSER_ARMED = "browser_armed"
    MEASURED = "measured"
    HELD = "held"
    HARDENING_REQUIRED = "hardening_required"
    HARDENING = "hardening"
    COMPLETED = "completed"


class FailureClass(StrEnum):
    CODE_DEFECT = "code_defect"
    PROVIDER_OR_EVIDENCE_UNAVAILABLE = "provider_or_evidence_unavailable"
    AUTHORIZATION_OR_CONFIGURATION = "authorization_or_configuration"
    BASELINE_FAILURE = "baseline_failure"
    EVALUATION_CONTRACT_DEFECT = "evaluation_contract_defect"


class GateState(StrEnum):
    NOT_OBSERVED = "not_observed"
    PASSED = "passed"
    FAILED = "failed"
    HELD = "held"


class FindingSeverity(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_RANK = {
    FindingSeverity.NONE: 0,
    FindingSeverity.LOW: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.HIGH: 3,
    FindingSeverity.CRITICAL: 4,
}


@dataclass(frozen=True, slots=True)
class PresentationGate:
    state: GateState = GateState.NOT_OBSERVED
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(_TOKEN.fullmatch(reason) is None for reason in self.reasons):
            raise ValueError("presentation gate reasons MUST be bounded machine tokens")
        if self.state is GateState.PASSED and self.reasons:
            raise ValueError("a passed presentation gate MUST NOT retain failure reasons")
        if self.state in {GateState.FAILED, GateState.HELD} and not self.reasons:
            raise ValueError("a failed or held presentation gate requires a reason")


@dataclass(frozen=True, slots=True)
class MeasurementOutcome:
    terminal_state: str
    answer_generation_state: str
    assessment_state: str
    assessment_reasons: tuple[str, ...] = ()
    score: int | None = None
    verdict: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.terminal_state,
            self.answer_generation_state,
            self.assessment_state,
            *self.assessment_reasons,
        ):
            if _TOKEN.fullmatch(value) is None:
                raise ValueError("measurement states and reasons MUST be bounded machine tokens")
        if self.assessment_state == "completed":
            if self.score is None or self.verdict is None:
                raise ValueError("a completed assessment requires score and verdict")
        elif self.score is not None or self.verdict is not None:
            raise ValueError("an incomplete assessment MUST NOT report score or verdict")


@dataclass(frozen=True, slots=True)
class BrowserRunObservation:
    """Content-free browser evidence for one measured terminal turn."""

    run_id: str
    case_id: str
    question_fingerprint: str
    session_id: str
    purpose: str
    request_sequence: int
    request_sha256: str
    trace_receipt_digest: str
    run_record_present: bool
    phase_states: tuple[tuple[str, str], ...]
    model_trace_enabled: bool
    omitted_model_calls: int
    expected_call_kinds: tuple[str, ...]
    observed_call_kinds: tuple[str, ...]
    prompt_manifests_match: bool
    prompt_profiles_visible: bool
    system_layer_order_valid: bool
    untrusted_data_separated: bool
    preparing_answer_seen: bool
    early_answer_exposed: bool
    preparing_answer_overlapped_terminal: bool
    terminal_transition_completed: bool
    sensitive_output_detected: bool

    def __post_init__(self) -> None:
        if _TOKEN.fullmatch(self.run_id) is None or _TOKEN.fullmatch(self.case_id) is None:
            raise ValueError("browser observation run and case ids MUST be bounded")
        if self.session_id != f"pantheon-assurance:{self.run_id}":
            raise ValueError("browser observation session does not match the run")
        if self.purpose != f"conversation-assurance:{self.case_id}":
            raise ValueError("browser observation purpose does not match the case")
        if self.request_sequence != 1:
            raise ValueError("browser observation MUST describe the first request")
        if any(
            _DIGEST.fullmatch(value) is None
            for value in (
                self.question_fingerprint,
                self.request_sha256,
                self.trace_receipt_digest,
            )
        ):
            raise ValueError("browser observation digests MUST be SHA-256")
        if self.omitted_model_calls < 0:
            raise ValueError("omitted model call count MUST be non-negative")
        if any(_TOKEN.fullmatch(item) is None for item in self.expected_call_kinds):
            raise ValueError("expected model call kinds MUST be bounded tokens")
        if any(_TOKEN.fullmatch(item) is None for item in self.observed_call_kinds):
            raise ValueError("observed model call kinds MUST be bounded tokens")
        phase_names = tuple(name for name, _state in self.phase_states)
        if len(phase_names) != len(set(phase_names)):
            raise ValueError("browser phase names MUST be unique")
        if any(name not in _TRAJECTORY_PHASES for name in phase_names):
            raise ValueError("browser observation contains an unknown trajectory phase")
        if phase_names != tuple(name for name in _TRAJECTORY_PHASE_ORDER if name in phase_names):
            raise ValueError("browser trajectory phases MUST preserve causal order")
        if any(_TOKEN.fullmatch(state) is None for _name, state in self.phase_states):
            raise ValueError("browser phase states MUST be bounded tokens")


@dataclass(frozen=True, slots=True)
class HardeningRoundRecord:
    round_number: int
    reviewer_scope: str
    finding_count: int
    fixed_count: int
    validation_passed: bool
    remaining_max_severity: FindingSeverity

    def __post_init__(self) -> None:
        if self.round_number < 1:
            raise ValueError("hardening round number MUST be positive")
        if _TOKEN.fullmatch(self.reviewer_scope) is None:
            raise ValueError("hardening reviewer scope MUST be a bounded token")
        if self.finding_count < 0 or not 0 <= self.fixed_count <= self.finding_count:
            raise ValueError("hardening finding and fix counts are inconsistent")


@dataclass(frozen=True, slots=True)
class ImprovementRun:
    run_id: str
    case_id: str
    question_fingerprint: str
    source_revision: str
    capability_id: str
    required_functions: tuple[str, ...]
    expected_authority: str
    provided_authority: str
    state: ImprovementState = ImprovementState.PREPARED
    corpus_digest: str | None = None
    measurement_reserved: bool = False
    measurement_attempts: int = 0
    terminal_state: str | None = None
    answer_generation_state: str | None = None
    assessment_state: str | None = None
    assessment_reasons: tuple[str, ...] = ()
    score: int | None = None
    verdict: str | None = None
    qualification: bool = False
    failure_class: FailureClass | None = None
    run_record_gate: PresentationGate = PresentationGate()
    prompt_assembly_gate: PresentationGate = PresentationGate()
    preparing_answer_gate: PresentationGate = PresentationGate()
    hardening_rounds: int = 0
    remaining_max_severity: FindingSeverity | None = None
    hardening_history: tuple[HardeningRoundRecord, ...] = ()

    def __post_init__(self) -> None:
        if _TOKEN.fullmatch(self.run_id) is None or _TOKEN.fullmatch(self.case_id) is None:
            raise ValueError("run and case ids MUST be bounded machine tokens")
        if _DIGEST.fullmatch(self.question_fingerprint) is None:
            raise ValueError("question fingerprint MUST be a SHA-256 digest")
        if _REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("source revision MUST be a lowercase Git SHA")
        for value in (
            self.capability_id,
            self.expected_authority,
            self.provided_authority,
            *self.required_functions,
        ):
            if _TOKEN.fullmatch(value) is None:
                raise ValueError("capability and authority fields MUST be bounded tokens")
        if not self.required_functions:
            raise ValueError("conversation improvement requires at least one function")
        if self.expected_authority != self.provided_authority:
            raise ValueError("expected and provided authority MUST match")
        if self.corpus_digest is not None and _DIGEST.fullmatch(self.corpus_digest) is None:
            raise ValueError("corpus digest MUST be a SHA-256 digest")
        if self.measurement_attempts not in {0, 1}:
            raise ValueError("a conversation-improvement question allows at most one measurement")
        if self.measurement_reserved and self.measurement_attempts:
            raise ValueError("a completed measurement cannot remain reserved")
        if self.measurement_reserved != (self.state is ImprovementState.BROWSER_ARMED):
            raise ValueError("browser reservation MUST match the armed state")
        if self.qualification:
            raise ValueError("a one-question improvement run has no qualification authority")
        if self.hardening_rounds < 0:
            raise ValueError("hardening rounds MUST be non-negative")
        if self.hardening_rounds != len(self.hardening_history):
            raise ValueError("hardening round count MUST match its evidence history")
        if any(
            item.round_number != index for index, item in enumerate(self.hardening_history, start=1)
        ):
            raise ValueError("hardening evidence MUST be ordered and contiguous")
        if self.state is ImprovementState.PREPARED and self.corpus_digest is not None:
            raise ValueError("a prepared run MUST NOT have a corpus dry-run receipt")
        if self.state is not ImprovementState.PREPARED and self.corpus_digest is None:
            raise ValueError("a post-prepare run requires its corpus dry-run receipt")
        measured_states = {
            ImprovementState.MEASURED,
            ImprovementState.HELD,
            ImprovementState.HARDENING_REQUIRED,
            ImprovementState.HARDENING,
            ImprovementState.COMPLETED,
        }
        if (self.state in measured_states) != (self.measurement_attempts == 1):
            raise ValueError("measured run state and attempt count are inconsistent")
        if self.state in {ImprovementState.HARDENING_REQUIRED, ImprovementState.HARDENING} and (
            self.failure_class is not FailureClass.CODE_DEFECT
        ):
            raise ValueError("hardening states require a code defect")
        if (
            self.state is ImprovementState.COMPLETED
            and self.failure_class is FailureClass.CODE_DEFECT
        ):
            if (
                self.hardening_rounds < _MIN_HARDENING_ROUNDS
                or self.remaining_max_severity is None
                or _SEVERITY_RANK[self.remaining_max_severity] > 1
                or not all(item.validation_passed for item in self.hardening_history)
            ):
                raise ValueError("completed code hardening evidence is incomplete")

    @property
    def retry_allowed(self) -> bool:
        return self.measurement_attempts == 0 and not self.measurement_reserved

    def reserve_browser_measurement(self) -> ImprovementRun:
        if self.state is not ImprovementState.DRY_RUN_VALIDATED or not self.retry_allowed:
            raise ValueError("browser measurement requires an unattempted validated dry run")
        return replace(
            self,
            state=ImprovementState.BROWSER_ARMED,
            measurement_reserved=True,
        )

    def validate_dry_run(
        self,
        *,
        question_count: int,
        child_count: int,
        corpus_digest: str,
    ) -> ImprovementRun:
        if self.state is not ImprovementState.PREPARED:
            raise ValueError("dry-run validation requires a prepared run")
        if question_count != 1 or child_count != 1:
            raise ValueError("conversation improvement requires exactly one question and child")
        if _DIGEST.fullmatch(corpus_digest) is None:
            raise ValueError("dry-run corpus digest MUST be SHA-256")
        return replace(
            self,
            state=ImprovementState.DRY_RUN_VALIDATED,
            corpus_digest=corpus_digest,
        )

    def record_measurement(self, outcome: MeasurementOutcome) -> ImprovementRun:
        if self.state not in {
            ImprovementState.DRY_RUN_VALIDATED,
            ImprovementState.BROWSER_ARMED,
        }:
            raise ValueError("measurement requires a validated or browser-armed dry run")
        if self.measurement_attempts != 0:
            raise ValueError("a live question MUST NOT be measured more than once")
        completed = outcome.assessment_state == "completed"
        return replace(
            self,
            state=ImprovementState.MEASURED if completed else ImprovementState.HELD,
            measurement_reserved=False,
            measurement_attempts=1,
            terminal_state=outcome.terminal_state,
            answer_generation_state=outcome.answer_generation_state,
            assessment_state=outcome.assessment_state,
            assessment_reasons=outcome.assessment_reasons,
            score=outcome.score,
            verdict=outcome.verdict,
        )

    def record_presentation(
        self,
        *,
        run_record: PresentationGate,
        prompt_assembly: PresentationGate,
        preparing_answer: PresentationGate,
    ) -> ImprovementRun:
        if self.measurement_attempts != 1:
            raise ValueError("presentation evidence requires the measured turn")
        return replace(
            self,
            run_record_gate=run_record,
            prompt_assembly_gate=prompt_assembly,
            preparing_answer_gate=preparing_answer,
        )

    def record_browser_observation(self, observation: BrowserRunObservation) -> ImprovementRun:
        if observation.case_id != self.case_id:
            raise ValueError("browser observation case id does not match the run")
        if observation.run_id != self.run_id:
            raise ValueError("browser observation run id does not match the run")
        if observation.question_fingerprint != self.question_fingerprint:
            raise ValueError("browser observation fingerprint does not match the run")
        run_record, prompt_assembly, preparing_answer = reduce_browser_observation(observation)
        return self.record_presentation(
            run_record=run_record,
            prompt_assembly=prompt_assembly,
            preparing_answer=preparing_answer,
        )

    def classify(self, failure_class: FailureClass | None) -> ImprovementRun:
        if self.measurement_attempts != 1:
            raise ValueError("classification requires one terminal measurement attempt")
        gates = (
            self.run_record_gate,
            self.prompt_assembly_gate,
            self.preparing_answer_gate,
        )
        passed = (
            self.assessment_state == "completed"
            and self.verdict == "pass"
            and all(gate.state is GateState.PASSED for gate in gates)
        )
        if passed:
            if failure_class is not None:
                raise ValueError("a passing run MUST NOT carry a failure class")
            return replace(self, state=ImprovementState.COMPLETED)
        if failure_class is None:
            raise ValueError("a non-passing run requires one typed failure class")
        if failure_class is FailureClass.CODE_DEFECT and self.assessment_state != "completed":
            raise ValueError("an incomplete assessment cannot be classified as a code defect")
        if failure_class is FailureClass.CODE_DEFECT and any(
            reason.startswith(_NON_CODE_REASON_PREFIXES) for reason in self.assessment_reasons
        ):
            raise ValueError("external or evaluation failure cannot be a code defect")
        if failure_class is FailureClass.CODE_DEFECT and any(
            gate.state in {GateState.NOT_OBSERVED, GateState.HELD} for gate in gates
        ):
            raise ValueError("unobserved or held presentation evidence cannot be a code defect")
        return replace(
            self,
            state=(
                ImprovementState.HARDENING_REQUIRED
                if failure_class is FailureClass.CODE_DEFECT
                else ImprovementState.HELD
            ),
            failure_class=failure_class,
        )

    def record_hardening_round(
        self,
        severity: FindingSeverity,
        *,
        reviewer_scope: str = "independent-review",
        finding_count: int = 0,
        fixed_count: int = 0,
        validation_passed: bool = True,
    ) -> ImprovementRun:
        if self.failure_class is not FailureClass.CODE_DEFECT or self.state not in {
            ImprovementState.HARDENING_REQUIRED,
            ImprovementState.HARDENING,
        }:
            raise ValueError("only a code defect can enter hardening")
        rounds = self.hardening_rounds + 1
        evidence = HardeningRoundRecord(
            round_number=rounds,
            reviewer_scope=reviewer_scope,
            finding_count=finding_count,
            fixed_count=fixed_count,
            validation_passed=validation_passed,
            remaining_max_severity=severity,
        )
        complete = (
            rounds >= _MIN_HARDENING_ROUNDS
            and validation_passed
            and all(item.validation_passed for item in self.hardening_history)
            and _SEVERITY_RANK[severity] <= 1
        )
        return replace(
            self,
            state=ImprovementState.COMPLETED if complete else ImprovementState.HARDENING,
            hardening_rounds=rounds,
            remaining_max_severity=severity,
            hardening_history=(*self.hardening_history, evidence),
        )


def write_private_run(path: Path, run: ImprovementRun) -> None:
    """Atomically persist one content-free run record as an owner-only file."""

    if path.is_symlink():
        raise ValueError("conversation improvement state path MUST NOT be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = _to_mapping(run)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_private_run(path: Path) -> ImprovementRun:
    """Read and validate one owner-only run record without accepting symlinks."""

    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("conversation improvement state file MUST be owner-only")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("conversation improvement state MUST be an object")
    try:
        return _from_mapping(value)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("conversation improvement state is invalid") from error


def validate_question_novelty(
    *,
    case_id: str,
    question: str,
    campaign_rows: Sequence[Mapping[str, object]],
    transcript_rows: Sequence[Mapping[str, object]],
) -> str:
    """Reject every prior case, exact wording, and lexical near duplicate."""

    if case_id in _FORBIDDEN_CASE_IDS:
        raise ValueError("question case id is permanently excluded")
    attempted: set[str] = set()
    for row in campaign_rows:
        raw_case_ids = row.get("attempted_case_ids")
        if isinstance(raw_case_ids, list):
            attempted.update(str(item) for item in raw_case_ids)
    attempted.update(str(row.get("case_id")) for row in transcript_rows if row.get("case_id"))
    if case_id in attempted:
        raise ValueError("question case id was already attempted")
    fingerprint = normalized_question_fingerprint(question)
    raw_digest = hashlib.sha256(question.encode("utf-8")).hexdigest()
    candidate_tokens = _question_tokens(question)
    for row in transcript_rows:
        prior_digest = row.get("question_digest")
        if prior_digest in {raw_digest, f"sha256:{raw_digest}"}:
            raise ValueError("question fingerprint was already attempted")
        prior = row.get("question")
        if not isinstance(prior, str):
            continue
        if normalized_question_fingerprint(prior) == fingerprint:
            raise ValueError("question fingerprint was already attempted")
        if _jaccard(candidate_tokens, _question_tokens(prior)) >= _TOKEN_SIMILARITY_LIMIT:
            raise ValueError("question is lexically similar to a prior attempt")
    return fingerprint


def normalized_question_fingerprint(question: str) -> str:
    normalized = unicodedata.normalize("NFC", " ".join(question.casefold().split()))
    if not 8 <= len(normalized) <= 400:
        raise ValueError("question length MUST be in [8, 400]")
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def reduce_browser_observation(
    observation: BrowserRunObservation,
) -> tuple[PresentationGate, PresentationGate, PresentationGate]:
    """Reduce one browser observation without treating record presence as success."""

    run_reasons: list[str] = []
    if not observation.run_record_present:
        run_reasons.append("run_record_missing")
    observed_phases = {name for name, _state in observation.phase_states}
    if observed_phases != _TRAJECTORY_PHASES:
        run_reasons.append("trajectory_phases_incomplete")
    if any(state in {"running", "not_observed"} for _name, state in observation.phase_states):
        run_reasons.append("trajectory_terminal_state_incomplete")
    if observation.sensitive_output_detected:
        run_reasons.append("sensitive_output_detected")

    prompt_reasons: list[str] = []
    if not observation.model_trace_enabled:
        prompt_reasons.append("model_trace_not_enabled")
    if observation.omitted_model_calls:
        prompt_reasons.append("model_trace_calls_omitted")
    if not set(observation.expected_call_kinds).issubset(observation.observed_call_kinds):
        prompt_reasons.append("model_trace_stage_missing")
    if not observation.prompt_manifests_match:
        prompt_reasons.append("prompt_manifest_mismatch")
    if not observation.prompt_profiles_visible:
        prompt_reasons.append("prompt_profiles_not_visible")
    if not observation.system_layer_order_valid:
        prompt_reasons.append("system_layer_order_invalid")
    if not observation.untrusted_data_separated:
        prompt_reasons.append("untrusted_data_boundary_invalid")

    preparing_reasons: list[str] = []
    if not observation.preparing_answer_seen:
        preparing_reasons.append("preparing_answer_not_observed")
    if observation.early_answer_exposed:
        preparing_reasons.append("answer_exposed_early")
    if observation.preparing_answer_overlapped_terminal:
        preparing_reasons.append("preparing_answer_terminal_overlap")
    if not observation.terminal_transition_completed:
        preparing_reasons.append("preparing_answer_transition_incomplete")

    return (
        _gate(run_reasons),
        _gate(prompt_reasons, held=not observation.model_trace_enabled),
        _gate(preparing_reasons, held=not observation.preparing_answer_seen),
    )


def _gate(reasons: list[str], *, held: bool = False) -> PresentationGate:
    if not reasons:
        return PresentationGate(GateState.PASSED)
    return PresentationGate(GateState.HELD if held else GateState.FAILED, tuple(reasons))


def _question_tokens(question: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFC", question.casefold())
    return frozenset(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _to_mapping(run: ImprovementRun) -> dict[str, Any]:
    return asdict(run)


def _from_mapping(value: dict[str, Any]) -> ImprovementRun:
    data = dict(value)
    for name in ("run_record_gate", "prompt_assembly_gate", "preparing_answer_gate"):
        gate = data[name]
        data[name] = PresentationGate(
            state=GateState(gate["state"]),
            reasons=tuple(gate["reasons"]),
        )
    data["state"] = ImprovementState(data["state"])
    data["required_functions"] = tuple(data["required_functions"])
    data["assessment_reasons"] = tuple(data["assessment_reasons"])
    if data["failure_class"] is not None:
        data["failure_class"] = FailureClass(data["failure_class"])
    if data["remaining_max_severity"] is not None:
        data["remaining_max_severity"] = FindingSeverity(data["remaining_max_severity"])
    data["hardening_history"] = tuple(
        HardeningRoundRecord(
            round_number=item["round_number"],
            reviewer_scope=item["reviewer_scope"],
            finding_count=item["finding_count"],
            fixed_count=item["fixed_count"],
            validation_passed=item["validation_passed"],
            remaining_max_severity=FindingSeverity(item["remaining_max_severity"]),
        )
        for item in data["hardening_history"]
    )
    return ImprovementRun(**data)


__all__ = [
    "FailureClass",
    "BrowserRunObservation",
    "FindingSeverity",
    "GateState",
    "HardeningRoundRecord",
    "ImprovementRun",
    "ImprovementState",
    "MeasurementOutcome",
    "PresentationGate",
    "read_private_run",
    "reduce_browser_observation",
    "normalized_question_fingerprint",
    "validate_question_novelty",
    "write_private_run",
]
