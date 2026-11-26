"""Deterministic execution tests for exact authored Rego policy pairs."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import fdai.rule_catalog.schema.equivalence_validator as validator_module
import pytest
from fdai.rule_catalog.schema.bounded_process import (
    BoundedProcessResult,
    ProcessOutputLimitError,
)
from fdai.rule_catalog.schema.equivalence_validation import EquivalenceValidationResult
from fdai.rule_catalog.schema.equivalence_validator import (
    EquivalenceFailureCategory,
    EquivalenceScenario,
    EquivalenceScenarioCorpus,
    RegoPolicyVersionPin,
    validate_rego_equivalence,
)
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics

requires_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary unavailable")


def _policy(rule_id: str, package: str, denied_value: str = "enabled") -> str:
    return f"""# METADATA
# title: Test policy
# description: Deterministic equivalence fixture.
# custom:
#   rule_id: {rule_id}
#   severity: high
#   category: security
package {package}

import rego.v1

default deny := false

deny if {{
    input.resource.type == "object-storage"
    input.resource.props.public_access == "{denied_value}"
}}
"""


def _pin(path: Path, rule_ref: str) -> RegoPolicyVersionPin:
    semantics = load_rego_semantics(path)
    return RegoPolicyVersionPin(
        rule_ref=rule_ref,
        policy_path=path,
        content_digest=f"sha256:{semantics.content_digest}",
        normalized_predicate_digest=semantics.normalized_semantic_digest,
    )


def _corpus() -> EquivalenceScenarioCorpus:
    return EquivalenceScenarioCorpus(
        id="counterexamples.public-access",
        version="1.0.0",
        cases=(
            EquivalenceScenario(
                id="disabled",
                input={
                    "resource": {
                        "props": {"public_access": "disabled"},
                        "type": "object-storage",
                    }
                },
            ),
            EquivalenceScenario(
                id="enabled",
                input={
                    "resource": {
                        "props": {"public_access": "enabled"},
                        "type": "object-storage",
                    }
                },
            ),
        ),
    )


def test_corpus_digest_is_stable_across_input_key_order() -> None:
    first = _corpus()
    second = EquivalenceScenarioCorpus(
        id=first.id,
        version=first.version,
        cases=(
            EquivalenceScenario(
                id="disabled",
                input={
                    "resource": {
                        "type": "object-storage",
                        "props": {"public_access": "disabled"},
                    }
                },
            ),
            first.cases[1],
        ),
    )

    assert first.content_digest == second.content_digest


def test_corpus_rejects_unstable_case_order() -> None:
    corpus = _corpus()

    with pytest.raises(ValueError, match="unique and ordered"):
        EquivalenceScenarioCorpus(
            id=corpus.id,
            version=corpus.version,
            cases=tuple(reversed(corpus.cases)),
        )


def test_decision_canonicalization_preserves_exact_json_numbers() -> None:
    lower = json.loads("9007199254740992.0", parse_float=validator_module.Decimal)
    higher = json.loads("9007199254740993.0", parse_float=validator_module.Decimal)
    equivalent = json.loads("9007199254740992", parse_int=validator_module.Decimal)

    assert validator_module._canonical_decision_json(lower) != (
        validator_module._canonical_decision_json(higher)
    )
    assert validator_module._canonical_decision_json(lower) == (
        validator_module._canonical_decision_json(equivalent)
    )


def test_validator_digest_covers_every_owned_source_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_files = []
    for name in ("runner", "digest", "receipt", "validator", "semantics"):
        path = tmp_path / f"{name}.py"
        path.write_text(f"{name} source\n", encoding="utf-8")
        source_files.append((name, path))
    monkeypatch.setattr(validator_module, "_VALIDATOR_SOURCE_FILES", tuple(source_files))
    original_digest = validator_module.validator_content_digest()

    source_files[0][1].write_text("changed runner source\n", encoding="utf-8")

    assert validator_module.validator_content_digest() != original_digest


@pytest.mark.parametrize(
    "rule_ref",
    [
        "test.public-access",
        "test.public-access@1.0",
        "test.public-access@owner@1.0.0",
        "Test.public-access@1.0.0",
    ],
)
def test_policy_pin_requires_exact_rule_version_reference(rule_ref: str) -> None:
    digest = f"sha256:{'a' * 64}"

    with pytest.raises(ValueError, match="rule_ref"):
        RegoPolicyVersionPin(
            rule_ref=rule_ref,
            policy_path=Path("policy.rego"),
            content_digest=digest,
            normalized_predicate_digest=digest,
        )


@requires_opa
def test_identical_policy_versions_validate_behavior_and_implementation(tmp_path: Path) -> None:
    policy_path = tmp_path / "left.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")

    evidence = validate_rego_equivalence(
        _pin(policy_path, "test.public-access@1.0.0"),
        _pin(policy_path, "test.public-access@1.1.0"),
        _corpus(),
    )

    assert evidence.result is EquivalenceValidationResult.VALIDATED
    assert evidence.same_behavior is True
    assert evidence.same_normalized_implementation is True
    assert evidence.completed_case_count == 2
    assert evidence.evaluator.name == "opa"
    assert evidence.evaluator.version.count(".") == 2
    assert evidence.mismatches == ()
    assert evidence.failures == ()


@requires_opa
def test_one_case_difference_rejects_behavior_claim(tmp_path: Path) -> None:
    left_path = tmp_path / "left.rego"
    right_path = tmp_path / "right.rego"
    left_path.write_text(_policy("test.left", "test.left"), encoding="utf-8")
    right_path.write_text(
        _policy("test.right", "test.right", denied_value="disabled"), encoding="utf-8"
    )

    evidence = validate_rego_equivalence(
        _pin(left_path, "test.left@1.0.0"),
        _pin(right_path, "test.right@1.0.0"),
        _corpus(),
    )

    assert evidence.result is EquivalenceValidationResult.REJECTED
    assert evidence.same_behavior is False
    assert evidence.same_normalized_implementation is False
    assert tuple(mismatch.case_id for mismatch in evidence.mismatches) == (
        "disabled",
        "enabled",
    )


@requires_opa
def test_policy_pin_drift_is_inconclusive_without_execution(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    left = _pin(policy_path, "test.public-access@1.0.0")
    drifted = left.model_copy(update={"content_digest": f"sha256:{'0' * 64}"})

    evidence = validate_rego_equivalence(
        drifted,
        _pin(policy_path, "test.public-access@1.1.0"),
        _corpus(),
    )

    assert evidence.result is EquivalenceValidationResult.INCONCLUSIVE
    assert evidence.completed_case_count == 0
    assert evidence.failures[0].category is EquivalenceFailureCategory.POLICY_PIN_MISMATCH
    assert evidence.failures[0].rule_ref == "test.public-access@1.0.0"
    assert evidence.evaluator is not None


def test_missing_opa_is_inconclusive_and_grants_no_review_authority(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    placeholder_digest = f"sha256:{'a' * 64}"
    left = RegoPolicyVersionPin(
        rule_ref="test.public-access@1.0.0",
        policy_path=policy_path,
        content_digest=placeholder_digest,
        normalized_predicate_digest=placeholder_digest,
    )
    right = left.model_copy(update={"rule_ref": "test.public-access@1.1.0"})

    evidence = validate_rego_equivalence(
        left,
        right,
        _corpus(),
        opa_binary="opa-command-that-does-not-exist",
    )

    assert evidence.result is EquivalenceValidationResult.INCONCLUSIVE
    assert evidence.evaluator is None
    assert evidence.failures[0].category is EquivalenceFailureCategory.EVALUATOR_UNAVAILABLE
    assert evidence.same_behavior is False
    assert not hasattr(evidence, "state")
    assert not hasattr(evidence, "reviewer")
    assert not hasattr(evidence, "promotion_authority")

    payload = evidence.model_dump(mode="json")
    payload["reviewer"] = "unauthorized-reviewer"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        type(evidence).model_validate(payload)


def test_evaluator_identity_and_execution_use_exact_byte_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "opa-source"
    snapshot = tmp_path / "opa-snapshot"
    source_bytes = b"exact evaluator bytes"
    source.write_bytes(source_bytes)
    monkeypatch.setattr(validator_module.shutil, "which", lambda _: str(source))

    def inspect_snapshot(command: list[str], **_: object) -> BoundedProcessResult:
        assert command == [str(snapshot), "version"]
        source.write_bytes(b"replacement evaluator bytes")
        assert snapshot.read_bytes() == source_bytes
        return BoundedProcessResult(returncode=0, stdout=b"Version: 0.68.0\n")

    monkeypatch.setattr(validator_module, "run_bounded_process", inspect_snapshot)

    resolved, evaluator = validator_module._resolve_evaluator(
        "opa",
        snapshot_path=snapshot,
        timeout_seconds=1.0,
    )

    assert resolved == str(snapshot)
    assert evaluator.content_digest == f"sha256:{hashlib.sha256(source_bytes).hexdigest()}"


@pytest.mark.parametrize(
    ("mode", "expected_category"),
    [
        ("timeout", EquivalenceFailureCategory.EVALUATION_TIMED_OUT),
        ("output-limit", EquivalenceFailureCategory.INVALID_EVALUATOR_OUTPUT),
        ("nonzero", EquivalenceFailureCategory.EVALUATION_FAILED),
        ("malformed", EquivalenceFailureCategory.INVALID_EVALUATOR_OUTPUT),
        ("undefined", EquivalenceFailureCategory.EVALUATION_UNDEFINED),
    ],
)
@requires_opa
def test_opa_execution_defects_are_sanitized_and_inconclusive(
    mode: str,
    expected_category: EquivalenceFailureCategory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    left = _pin(policy_path, "test.public-access@1.0.0")
    right = _pin(policy_path, "test.public-access@1.1.0")
    original_run = validator_module.run_bounded_process

    def fake_run(command: list[str], **kwargs: object) -> BoundedProcessResult:
        if len(command) > 1 and command[1] == "eval":
            if mode == "timeout":
                raise subprocess.TimeoutExpired(command, timeout=1.0)
            if mode == "output-limit":
                raise ProcessOutputLimitError("synthetic bounded-output failure")
            if mode == "nonzero":
                return BoundedProcessResult(returncode=1, stdout=b"")
            output = b"{" if mode == "malformed" else b'{"result":[]}'
            return BoundedProcessResult(returncode=0, stdout=output)
        return original_run(command, **kwargs)

    monkeypatch.setattr(validator_module, "run_bounded_process", fake_run)
    evidence = validate_rego_equivalence(left, right, _corpus())

    assert evidence.result is EquivalenceValidationResult.INCONCLUSIVE
    assert evidence.completed_case_count == 0
    assert evidence.failures == (
        validator_module.EquivalenceExecutionFailure(
            category=expected_category,
            rule_ref="test.public-access@1.0.0",
            case_id="disabled",
        ),
    )
    assert "synthetic bounded-output failure" not in evidence.model_dump_json()


@requires_opa
def test_configured_process_timeout_reaches_evaluation_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    left = _pin(policy_path, "test.public-access@1.0.0")
    right = _pin(policy_path, "test.public-access@1.1.0")
    original_run = validator_module.run_bounded_process
    evaluation_timeout: float | None = None

    def time_out_evaluation(
        command: list[str],
        **kwargs: object,
    ) -> BoundedProcessResult:
        nonlocal evaluation_timeout
        if len(command) > 1 and command[1] == "eval":
            evaluation_timeout = float(kwargs["timeout_seconds"])
            raise subprocess.TimeoutExpired(command, timeout=evaluation_timeout)
        return original_run(command, **kwargs)

    monkeypatch.setattr(validator_module, "run_bounded_process", time_out_evaluation)
    evidence = validate_rego_equivalence(
        left,
        right,
        _corpus(),
        timeout_seconds=0.25,
    )

    assert evaluation_timeout is not None
    assert 0 < evaluation_timeout <= 0.25
    assert evidence.result is EquivalenceValidationResult.INCONCLUSIVE
    assert evidence.failures[0].category is EquivalenceFailureCategory.EVALUATION_TIMED_OUT


@requires_opa
def test_partial_execution_failure_records_exact_case_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    left = _pin(policy_path, "test.public-access@1.0.0")
    right = _pin(policy_path, "test.public-access@1.1.0")
    original_run = validator_module.run_bounded_process
    evaluation_count = 0

    def fail_third_evaluation(
        command: list[str],
        **kwargs: object,
    ) -> BoundedProcessResult:
        nonlocal evaluation_count
        if len(command) > 1 and command[1] == "eval":
            evaluation_count += 1
            if evaluation_count == 3:
                return BoundedProcessResult(returncode=0, stdout=b"{")
        return original_run(command, **kwargs)

    monkeypatch.setattr(validator_module, "run_bounded_process", fail_third_evaluation)
    evidence = validate_rego_equivalence(left, right, _corpus())

    assert evidence.result is EquivalenceValidationResult.INCONCLUSIVE
    assert evidence.completed_case_count == 1
    assert evidence.failures[0].case_id == "enabled"
    assert evidence.failures[0].rule_ref == "test.public-access@1.0.0"


@requires_opa
def test_total_deadline_exhaustion_is_inconclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    left = _pin(policy_path, "test.public-access@1.0.0")
    right = _pin(policy_path, "test.public-access@1.1.0")
    remaining_calls = 0
    original_remaining = validator_module._remaining_timeout

    def exhaust_during_first_case(
        deadline: float,
        *,
        rule_ref: str | None = None,
        case_id: str | None = None,
    ) -> float:
        nonlocal remaining_calls
        remaining_calls += 1
        if remaining_calls == 5:
            raise validator_module._EvaluationError(
                EquivalenceFailureCategory.TOTAL_DEADLINE_EXCEEDED,
                rule_ref=rule_ref,
                case_id=case_id,
            )
        return original_remaining(deadline, rule_ref=rule_ref, case_id=case_id)

    monkeypatch.setattr(validator_module, "_remaining_timeout", exhaust_during_first_case)
    evidence = validate_rego_equivalence(left, right, _corpus())

    assert evidence.result is EquivalenceValidationResult.INCONCLUSIVE
    assert evidence.completed_case_count == 0
    assert evidence.failures[0].category is EquivalenceFailureCategory.TOTAL_DEADLINE_EXCEEDED
    assert evidence.failures[0].case_id == "disabled"


@requires_opa
def test_deadline_exhaustion_after_all_cases_prevents_conclusive_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    left = _pin(policy_path, "test.public-access@1.0.0")
    right = _pin(policy_path, "test.public-access@1.1.0")
    original_remaining = validator_module._remaining_timeout
    evaluation_count = 0
    original_run = validator_module.run_bounded_process

    def count_evaluations(command: list[str], **kwargs: object) -> BoundedProcessResult:
        nonlocal evaluation_count
        if len(command) > 1 and command[1] == "eval":
            evaluation_count += 1
        return original_run(command, **kwargs)

    def expire_before_result(
        deadline: float,
        *,
        rule_ref: str | None = None,
        case_id: str | None = None,
    ) -> float:
        if evaluation_count == 4 and rule_ref is None and case_id is None:
            raise validator_module._EvaluationError(
                EquivalenceFailureCategory.TOTAL_DEADLINE_EXCEEDED
            )
        return original_remaining(deadline, rule_ref=rule_ref, case_id=case_id)

    monkeypatch.setattr(validator_module, "run_bounded_process", count_evaluations)
    monkeypatch.setattr(validator_module, "_remaining_timeout", expire_before_result)
    evidence = validate_rego_equivalence(left, right, _corpus())

    assert evidence.result is EquivalenceValidationResult.INCONCLUSIVE
    assert evidence.completed_case_count == 2
    assert evidence.failures[0].category is EquivalenceFailureCategory.TOTAL_DEADLINE_EXCEEDED


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, float("inf"), 60.1])
def test_validator_rejects_unbounded_timeout(timeout_seconds: float, tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    placeholder_digest = f"sha256:{'a' * 64}"
    left = RegoPolicyVersionPin(
        rule_ref="test.public-access@1.0.0",
        policy_path=policy_path,
        content_digest=placeholder_digest,
        normalized_predicate_digest=placeholder_digest,
    )
    right = left.model_copy(update={"rule_ref": "test.public-access@1.1.0"})

    with pytest.raises(ValueError, match="timeout_seconds"):
        validate_rego_equivalence(
            left,
            right,
            _corpus(),
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.parametrize("total_timeout_seconds", [0.0, -1.0, float("inf"), 300.1])
def test_validator_rejects_unbounded_total_deadline(
    total_timeout_seconds: float,
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / "policy.rego"
    policy_path.write_text(_policy("test.public-access", "test.public_access"), encoding="utf-8")
    placeholder_digest = f"sha256:{'a' * 64}"
    left = RegoPolicyVersionPin(
        rule_ref="test.public-access@1.0.0",
        policy_path=policy_path,
        content_digest=placeholder_digest,
        normalized_predicate_digest=placeholder_digest,
    )
    right = left.model_copy(update={"rule_ref": "test.public-access@1.1.0"})

    with pytest.raises(ValueError, match="total_timeout_seconds"):
        validate_rego_equivalence(
            left,
            right,
            _corpus(),
            total_timeout_seconds=total_timeout_seconds,
        )
