"""Bounded deterministic evidence for exact authored Rego policy pairs."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

import fdai.rule_catalog.schema.bounded_process as bounded_process_module
import fdai.rule_catalog.schema.catalog_digest as catalog_digest_module
import fdai.rule_catalog.schema.equivalence_validation as equivalence_validation_module
import fdai.rule_catalog.schema.rego_semantics as rego_semantics_module
from fdai.rule_catalog.schema.bounded_process import (
    ProcessOutputLimitError,
    run_bounded_process,
)
from fdai.rule_catalog.schema.catalog_digest import canonical_catalog_digest
from fdai.rule_catalog.schema.equivalence_validation import (
    CounterexampleSetPin,
    EquivalenceValidationResult,
    ValidatorPin,
)
from fdai.rule_catalog.schema.rego_semantics import (
    RegoSemantics,
    RegoSemanticsError,
    load_rego_semantics,
)

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9._-]{0,127}$"
_REFERENCE_PATTERN = r"^[A-Za-z][A-Za-z0-9._:@/-]{0,255}$"
_RULE_REF_PATTERN = r"^[a-z][a-z0-9._/-]{0,127}@\d+\.\d+\.\d+$"
_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
_MAX_CASES = 256
_MAX_CASE_INPUT_BYTES = 1_000_000
_MAX_CORPUS_BYTES = 8_000_000
_MAX_OPA_OUTPUT_BYTES = 1_000_000
_MAX_POLICY_BYTES = 1_000_000
_MAX_EXECUTABLE_BYTES = 128_000_000
_MAX_TIMEOUT_SECONDS = 60.0
_MAX_TOTAL_TIMEOUT_SECONDS = 300.0

VALIDATOR_NAME = "heimdall-equivalence-validator"
VALIDATOR_VERSION = "1.0.0"


def _module_source_path(module_file: str | None) -> Path:
    if module_file is None:
        raise RuntimeError("validator source module has no file")
    return Path(module_file)


_VALIDATOR_SOURCE_FILES = (
    ("bounded_process", _module_source_path(bounded_process_module.__file__)),
    ("catalog_digest", _module_source_path(catalog_digest_module.__file__)),
    ("equivalence_validation", _module_source_path(equivalence_validation_module.__file__)),
    ("equivalence_validator", Path(__file__)),
    ("rego_semantics", _module_source_path(rego_semantics_module.__file__)),
)


class EquivalenceScenario(BaseModel):
    """One stable, bounded OPA input in a frozen comparison corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    input: dict[str, JsonValue]

    @model_validator(mode="after")
    def require_bounded_input(self) -> EquivalenceScenario:
        encoded = _canonical_json(self.input)
        if len(encoded) > _MAX_CASE_INPUT_BYTES:
            raise ValueError("equivalence scenario input MUST be at most 1000000 bytes")
        return self


class EquivalenceScenarioCorpus(BaseModel):
    """Frozen, canonically ordered counterexamples shared by both policies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=_SEMVER_PATTERN)] = "1.0.0"
    id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    version: Annotated[str, Field(pattern=_SEMVER_PATTERN)]
    cases: tuple[EquivalenceScenario, ...] = Field(min_length=1, max_length=_MAX_CASES)

    @model_validator(mode="after")
    def require_canonical_cases(self) -> EquivalenceScenarioCorpus:
        case_ids = tuple(case.id for case in self.cases)
        if case_ids != tuple(sorted(set(case_ids))):
            raise ValueError("equivalence scenario ids MUST be unique and ordered")
        if len(_canonical_json(self.model_dump(mode="json"))) > _MAX_CORPUS_BYTES:
            raise ValueError("equivalence scenario corpus MUST be at most 8000000 bytes")
        return self

    @property
    def reference(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def content_digest(self) -> str:
        return canonical_catalog_digest(self, exclude=frozenset())


class RegoPolicyVersionPin(BaseModel):
    """Exact local Rego artifact and identities required before evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_ref: Annotated[str, Field(pattern=_RULE_REF_PATTERN)]
    policy_path: Path
    content_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    normalized_predicate_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class EquivalenceCaseMismatch(BaseModel):
    """Digest-only evidence for one behavior mismatch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)]
    left_result_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    right_result_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class EquivalenceFailureCategory(StrEnum):
    """Stable, sanitized reason that mechanical evidence is inconclusive."""

    EVALUATOR_IDENTITY_FAILED = "evaluator_identity_failed"
    EVALUATOR_UNAVAILABLE = "evaluator_unavailable"
    EVALUATION_FAILED = "evaluation_failed"
    EVALUATION_TIMED_OUT = "evaluation_timed_out"
    EVALUATION_UNDEFINED = "evaluation_undefined"
    INVALID_EVALUATOR_OUTPUT = "invalid_evaluator_output"
    POLICY_PIN_MISMATCH = "policy_pin_mismatch"
    POLICY_UNAVAILABLE = "policy_unavailable"
    POLICY_VERIFICATION_FAILED = "policy_verification_failed"
    TOTAL_DEADLINE_EXCEEDED = "total_deadline_exceeded"


class EquivalenceExecutionFailure(BaseModel):
    """Sanitized failure context without inputs, decisions, paths, or stderr."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: EquivalenceFailureCategory
    rule_ref: Annotated[str, Field(pattern=_RULE_REF_PATTERN)] | None = None
    case_id: Annotated[str, Field(pattern=_IDENTIFIER_PATTERN)] | None = None


class DeterministicEquivalenceEvidence(BaseModel):
    """Mechanical comparison evidence with no review or promotion authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validator: ValidatorPin
    evaluator: ValidatorPin | None
    compared_rules: tuple[
        Annotated[str, Field(pattern=_RULE_REF_PATTERN)],
        Annotated[str, Field(pattern=_RULE_REF_PATTERN)],
    ]
    normalized_predicate_digests: tuple[
        Annotated[str, Field(pattern=_DIGEST_PATTERN)],
        Annotated[str, Field(pattern=_DIGEST_PATTERN)],
    ]
    counterexamples: CounterexampleSetPin
    result: EquivalenceValidationResult
    same_behavior: Annotated[bool, Field(strict=True)]
    same_normalized_implementation: Annotated[bool, Field(strict=True)]
    completed_case_count: Annotated[int, Field(strict=True, ge=0, le=_MAX_CASES)]
    mismatches: tuple[EquivalenceCaseMismatch, ...] = Field(max_length=_MAX_CASES)
    failures: tuple[EquivalenceExecutionFailure, ...] = Field(max_length=_MAX_CASES)

    @model_validator(mode="after")
    def require_consistent_result(self) -> DeterministicEquivalenceEvidence:
        if self.compared_rules[0] >= self.compared_rules[1]:
            raise ValueError("compared_rules MUST contain two unique Rule refs in order")
        if self.same_normalized_implementation and not self.same_behavior:
            raise ValueError("same_normalized_implementation requires same_behavior")
        if self.result is not EquivalenceValidationResult.INCONCLUSIVE and self.evaluator is None:
            raise ValueError("conclusive evidence requires an exact evaluator pin")
        if self.result is EquivalenceValidationResult.VALIDATED:
            if not self.same_behavior or self.mismatches or self.failures:
                raise ValueError("validated evidence MUST contain complete matching behavior")
            if self.completed_case_count != self.counterexamples.case_count:
                raise ValueError("validated evidence MUST complete every scenario")
        elif self.result is EquivalenceValidationResult.REJECTED:
            if self.same_behavior or not self.mismatches or self.failures:
                raise ValueError("rejected evidence MUST contain mismatches without failures")
        elif not self.failures:
            raise ValueError("inconclusive evidence MUST record failures")
        return self


@dataclass(frozen=True, slots=True)
class _EvaluatedDecision:
    canonical: bytes
    digest: str


class _EvaluationError(ValueError):
    def __init__(
        self,
        category: EquivalenceFailureCategory,
        *,
        rule_ref: str | None = None,
        case_id: str | None = None,
    ) -> None:
        super().__init__(category.value)
        self.failure = EquivalenceExecutionFailure(
            category=category,
            rule_ref=rule_ref,
            case_id=case_id,
        )


def validate_rego_equivalence(
    left: RegoPolicyVersionPin,
    right: RegoPolicyVersionPin,
    corpus: EquivalenceScenarioCorpus,
    *,
    opa_binary: str = "opa",
    timeout_seconds: float = 5.0,
    total_timeout_seconds: float = 60.0,
) -> DeterministicEquivalenceEvidence:
    """Compare exact policies over one corpus, abstaining on any execution defect.

    The function returns mechanical evidence only. It never creates a reviewed receipt,
    changes a binding lifecycle, or grants evaluation, approval, or execution authority.
    """

    if left.rule_ref >= right.rule_ref:
        raise ValueError("policy pins MUST contain two unique Rule refs in order")
    if (
        not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > _MAX_TIMEOUT_SECONDS
    ):
        raise ValueError("timeout_seconds MUST be finite and within 0..60 seconds")
    if (
        not math.isfinite(total_timeout_seconds)
        or total_timeout_seconds <= 0
        or total_timeout_seconds > _MAX_TOTAL_TIMEOUT_SECONDS
    ):
        raise ValueError("total_timeout_seconds MUST be finite and within 0..300 seconds")
    deadline = time.monotonic() + total_timeout_seconds
    counterexamples = CounterexampleSetPin(
        reference=corpus.reference,
        content_digest=corpus.content_digest,
        case_count=len(corpus.cases),
    )
    evaluator: ValidatorPin | None = None
    try:
        with TemporaryDirectory(prefix="fdai-equivalence-") as directory:
            snapshot_root = Path(directory)
            resolved_opa, evaluator = _resolve_evaluator(
                opa_binary,
                snapshot_path=snapshot_root / "opa",
                timeout_seconds=min(timeout_seconds, _remaining_timeout(deadline)),
            )
            validator = ValidatorPin(
                name=VALIDATOR_NAME,
                version=VALIDATOR_VERSION,
                content_digest=validator_content_digest(),
            )
            left_snapshot = _snapshot_policy(left, snapshot_root / "left.rego")
            right_snapshot = _snapshot_policy(right, snapshot_root / "right.rego")
            return _compare_snapshots(
                left_snapshot,
                right_snapshot,
                corpus,
                counterexamples,
                validator,
                evaluator,
                opa_binary=resolved_opa,
                timeout_seconds=timeout_seconds,
                deadline=deadline,
            )
    except (OSError, _EvaluationError) as exc:
        failure = (
            exc.failure
            if isinstance(exc, _EvaluationError)
            else EquivalenceExecutionFailure(category=EquivalenceFailureCategory.EVALUATION_FAILED)
        )
        return _evidence(
            left,
            right,
            counterexamples,
            ValidatorPin(
                name=VALIDATOR_NAME,
                version=VALIDATOR_VERSION,
                content_digest=validator_content_digest(),
            ),
            evaluator,
            result=EquivalenceValidationResult.INCONCLUSIVE,
            completed_case_count=0,
            failures=(failure,),
        )


def _compare_snapshots(
    left: RegoPolicyVersionPin,
    right: RegoPolicyVersionPin,
    corpus: EquivalenceScenarioCorpus,
    counterexamples: CounterexampleSetPin,
    validator: ValidatorPin,
    evaluator: ValidatorPin,
    *,
    opa_binary: str,
    timeout_seconds: float,
    deadline: float,
) -> DeterministicEquivalenceEvidence:
    left_semantics = _verified_semantics(
        left,
        opa_binary=opa_binary,
        timeout_seconds=min(
            timeout_seconds,
            _remaining_timeout(deadline, rule_ref=left.rule_ref),
        ),
    )
    right_semantics = _verified_semantics(
        right,
        opa_binary=opa_binary,
        timeout_seconds=min(
            timeout_seconds,
            _remaining_timeout(deadline, rule_ref=right.rule_ref),
        ),
    )

    mismatches: list[EquivalenceCaseMismatch] = []
    completed_case_count = 0
    for scenario in corpus.cases:
        try:
            left_decision = _evaluate(
                left,
                left_semantics,
                scenario,
                opa_binary=opa_binary,
                timeout_seconds=min(
                    timeout_seconds,
                    _remaining_timeout(
                        deadline,
                        rule_ref=left.rule_ref,
                        case_id=scenario.id,
                    ),
                ),
            )
            right_decision = _evaluate(
                right,
                right_semantics,
                scenario,
                opa_binary=opa_binary,
                timeout_seconds=min(
                    timeout_seconds,
                    _remaining_timeout(
                        deadline,
                        rule_ref=right.rule_ref,
                        case_id=scenario.id,
                    ),
                ),
            )
        except _EvaluationError as exc:
            return _evidence(
                left,
                right,
                counterexamples,
                validator,
                evaluator,
                result=EquivalenceValidationResult.INCONCLUSIVE,
                completed_case_count=completed_case_count,
                mismatches=tuple(mismatches),
                failures=(exc.failure,),
            )
        completed_case_count += 1
        if left_decision.canonical != right_decision.canonical:
            mismatches.append(
                EquivalenceCaseMismatch(
                    case_id=scenario.id,
                    left_result_digest=left_decision.digest,
                    right_result_digest=right_decision.digest,
                )
            )

    try:
        _remaining_timeout(deadline)
    except _EvaluationError as exc:
        return _evidence(
            left,
            right,
            counterexamples,
            validator,
            evaluator,
            result=EquivalenceValidationResult.INCONCLUSIVE,
            completed_case_count=completed_case_count,
            mismatches=tuple(mismatches),
            failures=(exc.failure,),
        )
    result = (
        EquivalenceValidationResult.REJECTED
        if mismatches
        else EquivalenceValidationResult.VALIDATED
    )
    return _evidence(
        left,
        right,
        counterexamples,
        validator,
        evaluator,
        result=result,
        completed_case_count=completed_case_count,
        mismatches=tuple(mismatches),
    )


def _snapshot_policy(
    target: RegoPolicyVersionPin,
    snapshot_path: Path,
) -> RegoPolicyVersionPin:
    try:
        with target.policy_path.open("rb") as policy_file:
            body = policy_file.read(_MAX_POLICY_BYTES + 1)
    except OSError as exc:
        raise _EvaluationError(
            EquivalenceFailureCategory.POLICY_UNAVAILABLE,
            rule_ref=target.rule_ref,
        ) from exc
    if not body or len(body) > _MAX_POLICY_BYTES:
        raise _EvaluationError(
            EquivalenceFailureCategory.POLICY_UNAVAILABLE,
            rule_ref=target.rule_ref,
        )
    actual_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    if actual_digest != target.content_digest:
        raise _EvaluationError(
            EquivalenceFailureCategory.POLICY_PIN_MISMATCH,
            rule_ref=target.rule_ref,
        )
    snapshot_path.write_bytes(body)
    return target.model_copy(update={"policy_path": snapshot_path})


def validator_content_digest() -> str:
    """Pin the exact owned source set used to produce equivalence evidence."""

    manifest = tuple(
        {
            "name": name,
            "content_digest": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        }
        for name, path in _VALIDATOR_SOURCE_FILES
    )
    return f"sha256:{hashlib.sha256(_canonical_json(manifest)).hexdigest()}"


def _resolve_evaluator(
    opa_binary: str,
    *,
    snapshot_path: Path,
    timeout_seconds: float,
) -> tuple[str, ValidatorPin]:
    resolved = shutil.which(opa_binary)
    if resolved is None:
        raise _EvaluationError(EquivalenceFailureCategory.EVALUATOR_UNAVAILABLE)
    executable = Path(resolved).resolve()
    digest = _snapshot_evaluator(executable, snapshot_path)
    try:
        completed = run_bounded_process(
            [str(snapshot_path), "version"],
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=_MAX_OPA_OUTPUT_BYTES,
        )
    except (OSError, ProcessOutputLimitError, subprocess.TimeoutExpired) as exc:
        raise _EvaluationError(EquivalenceFailureCategory.EVALUATOR_IDENTITY_FAILED) from exc
    if completed.returncode != 0 or not completed.stdout:
        raise _EvaluationError(EquivalenceFailureCategory.EVALUATOR_IDENTITY_FAILED)
    version = _opa_version(completed.stdout)
    return str(snapshot_path), ValidatorPin(
        name="opa",
        version=version,
        content_digest=digest,
    )


def _opa_version(output: bytes) -> str:
    try:
        text = output.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _EvaluationError(EquivalenceFailureCategory.EVALUATOR_IDENTITY_FAILED) from exc
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "Version":
            version = value.strip()
            if (
                version
                and version.count(".") == 2
                and all(part.isdigit() for part in version.split("."))
            ):
                return version
    raise _EvaluationError(EquivalenceFailureCategory.EVALUATOR_IDENTITY_FAILED)


def _snapshot_evaluator(source_path: Path, snapshot_path: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    try:
        with source_path.open("rb") as source, snapshot_path.open("xb") as snapshot:
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_EXECUTABLE_BYTES:
                    raise _EvaluationError(EquivalenceFailureCategory.EVALUATOR_IDENTITY_FAILED)
                digest.update(chunk)
                snapshot.write(chunk)
        snapshot_path.chmod(0o700)
    except OSError as exc:
        raise _EvaluationError(EquivalenceFailureCategory.EVALUATOR_IDENTITY_FAILED) from exc
    if total == 0:
        raise _EvaluationError(EquivalenceFailureCategory.EVALUATOR_IDENTITY_FAILED)
    return f"sha256:{digest.hexdigest()}"


def _remaining_timeout(
    deadline: float,
    *,
    rule_ref: str | None = None,
    case_id: str | None = None,
) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _EvaluationError(
            EquivalenceFailureCategory.TOTAL_DEADLINE_EXCEEDED,
            rule_ref=rule_ref,
            case_id=case_id,
        )
    return remaining


def _verified_semantics(
    target: RegoPolicyVersionPin,
    *,
    opa_binary: str,
    timeout_seconds: float,
) -> RegoSemantics:
    side = target.rule_ref
    try:
        semantics = load_rego_semantics(
            target.policy_path,
            opa_binary=opa_binary,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, RegoSemanticsError) as exc:
        raise _EvaluationError(
            EquivalenceFailureCategory.POLICY_VERIFICATION_FAILED,
            rule_ref=side,
        ) from exc
    expected_rule_id = target.rule_ref.rsplit("@", maxsplit=1)[0]
    if semantics.rule_id != expected_rule_id:
        raise _EvaluationError(
            EquivalenceFailureCategory.POLICY_PIN_MISMATCH,
            rule_ref=side,
        )
    if f"sha256:{semantics.content_digest}" != target.content_digest:
        raise _EvaluationError(
            EquivalenceFailureCategory.POLICY_PIN_MISMATCH,
            rule_ref=side,
        )
    if semantics.normalized_semantic_digest != target.normalized_predicate_digest:
        raise _EvaluationError(
            EquivalenceFailureCategory.POLICY_PIN_MISMATCH,
            rule_ref=side,
        )
    return semantics


def _evaluate(
    target: RegoPolicyVersionPin,
    semantics: RegoSemantics,
    scenario: EquivalenceScenario,
    *,
    opa_binary: str,
    timeout_seconds: float,
) -> _EvaluatedDecision:
    try:
        completed = run_bounded_process(
            [
                opa_binary,
                "eval",
                "--format=json",
                "--stdin-input",
                "--data",
                str(target.policy_path),
                semantics.decision_path,
            ],
            input_data=_canonical_json(scenario.input),
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=_MAX_OPA_OUTPUT_BYTES,
        )
    except (OSError, ProcessOutputLimitError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            category = EquivalenceFailureCategory.EVALUATION_TIMED_OUT
        elif isinstance(exc, ProcessOutputLimitError):
            category = EquivalenceFailureCategory.INVALID_EVALUATOR_OUTPUT
        else:
            category = EquivalenceFailureCategory.EVALUATOR_UNAVAILABLE
        raise _EvaluationError(
            category,
            rule_ref=target.rule_ref,
            case_id=scenario.id,
        ) from exc
    if completed.returncode != 0:
        raise _EvaluationError(
            EquivalenceFailureCategory.EVALUATION_FAILED,
            rule_ref=target.rule_ref,
            case_id=scenario.id,
        )
    if not completed.stdout:
        raise _EvaluationError(
            EquivalenceFailureCategory.INVALID_EVALUATOR_OUTPUT,
            rule_ref=target.rule_ref,
            case_id=scenario.id,
        )
    try:
        output = json.loads(
            completed.stdout,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _EvaluationError(
            EquivalenceFailureCategory.INVALID_EVALUATOR_OUTPUT,
            rule_ref=target.rule_ref,
            case_id=scenario.id,
        ) from exc
    try:
        value = _opa_value(output)
        canonical = _canonical_decision_json(value)
    except _UndefinedDecisionError as exc:
        raise _EvaluationError(
            EquivalenceFailureCategory.EVALUATION_UNDEFINED,
            rule_ref=target.rule_ref,
            case_id=scenario.id,
        ) from exc
    except (TypeError, ValueError) as exc:
        raise _EvaluationError(
            EquivalenceFailureCategory.INVALID_EVALUATOR_OUTPUT,
            rule_ref=target.rule_ref,
            case_id=scenario.id,
        ) from exc
    return _EvaluatedDecision(
        canonical=canonical,
        digest=f"sha256:{hashlib.sha256(canonical).hexdigest()}",
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _opa_value(output: object) -> object:
    if not isinstance(output, Mapping):
        raise ValueError("OPA output root must be an object")
    results = output.get("result")
    if isinstance(results, Sequence) and not isinstance(results, (str, bytes)) and not results:
        raise _UndefinedDecisionError("OPA decision was undefined")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)) or len(results) != 1:
        raise ValueError("OPA output must contain one result")
    result = results[0]
    expressions = result.get("expressions") if isinstance(result, Mapping) else None
    if (
        not isinstance(expressions, Sequence)
        or isinstance(expressions, (str, bytes))
        or len(expressions) != 1
    ):
        raise ValueError("OPA output must contain one expression")
    expression = expressions[0]
    if not isinstance(expression, Mapping) or "value" not in expression:
        raise ValueError("OPA expression must contain a value")
    return expression["value"]


class _UndefinedDecisionError(ValueError):
    pass


def _evidence(
    left: RegoPolicyVersionPin,
    right: RegoPolicyVersionPin,
    counterexamples: CounterexampleSetPin,
    validator: ValidatorPin,
    evaluator: ValidatorPin | None,
    *,
    result: EquivalenceValidationResult,
    completed_case_count: int,
    mismatches: tuple[EquivalenceCaseMismatch, ...] = (),
    failures: tuple[EquivalenceExecutionFailure, ...] = (),
) -> DeterministicEquivalenceEvidence:
    same_behavior = result is EquivalenceValidationResult.VALIDATED
    return DeterministicEquivalenceEvidence(
        validator=validator,
        evaluator=evaluator,
        compared_rules=(left.rule_ref, right.rule_ref),
        normalized_predicate_digests=(
            left.normalized_predicate_digest,
            right.normalized_predicate_digest,
        ),
        counterexamples=counterexamples,
        result=result,
        same_behavior=same_behavior,
        same_normalized_implementation=(
            same_behavior and left.normalized_predicate_digest == right.normalized_predicate_digest
        ),
        completed_case_count=completed_case_count,
        mismatches=mismatches,
        failures=failures,
    )


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("equivalence data MUST be canonical JSON") from exc


def _canonical_decision_json(value: object) -> bytes:
    return _canonical_json(_decision_node(value))


def _decision_node(value: object) -> object:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, Decimal):
        sign, digits, exponent = value.as_tuple()
        if not isinstance(exponent, int):
            raise ValueError("OPA decision numbers MUST be finite")
        normalized_digits = list(digits)
        while len(normalized_digits) > 1 and normalized_digits[-1] == 0:
            normalized_digits.pop()
            exponent += 1
        if not any(normalized_digits):
            sign, normalized_digits, exponent = 0, [0], 0
        return ["number", sign, "".join(str(digit) for digit in normalized_digits), exponent]
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return ["array", [_decision_node(item) for item in value]]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("OPA decision object keys MUST be strings")
        return [
            "object",
            [[key, _decision_node(value[key])] for key in sorted(value)],
        ]
    raise ValueError("OPA decision MUST be a JSON value")


__all__ = [
    "DeterministicEquivalenceEvidence",
    "EquivalenceCaseMismatch",
    "EquivalenceExecutionFailure",
    "EquivalenceFailureCategory",
    "EquivalenceScenario",
    "EquivalenceScenarioCorpus",
    "RegoPolicyVersionPin",
    "validate_rego_equivalence",
    "validator_content_digest",
]
