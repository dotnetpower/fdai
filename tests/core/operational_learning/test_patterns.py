from __future__ import annotations

from dataclasses import replace

from tests.core.case_history.test_operational_case import _case_input, _receipt

from fdai.core.case_history import (
    OperationalOutcomeClass,
    OperationalReceiptType,
    compile_operational_case,
)
from fdai.core.operational_learning import (
    OperatingPatternCompiler,
    pattern_case_from_operational_case,
)


def _pattern_case(
    identifier: str,
    outcome_class: OperationalOutcomeClass,
):  # type: ignore[no-untyped-def]
    case_input = _case_input(outcome_class=outcome_class)
    if outcome_class is OperationalOutcomeClass.SUCCESS:
        receipts = tuple(
            _receipt(
                OperationalReceiptType.AUDIT,
                "1",
                (("event_type", "action.completed"), ("decision", "auto"), ("mode", "enforce")),
            )
            if receipt.receipt_type is OperationalReceiptType.AUDIT
            else receipt
            for receipt in case_input.receipts
        )
        case_input = replace(case_input, receipts=receipts)
    projection = compile_operational_case(case_input).projection(
        case_id=f"case-{identifier}",
        case_revision=1,
        manifest_digest=identifier * 64,
    )
    return pattern_case_from_operational_case(case_input, projection)


def test_only_verified_enforce_outcome_is_reusable() -> None:
    case = _pattern_case("a", OperationalOutcomeClass.SUCCESS)

    assert case is not None
    assert case.reusable is True
    assert case.negative is False


def test_mismatch_is_negative_evidence() -> None:
    case = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)

    assert case is not None
    assert case.reusable is False
    assert case.negative is True


def test_compiler_requires_one_fingerprint_and_action_with_balanced_evidence() -> None:
    success = _pattern_case("a", OperationalOutcomeClass.SUCCESS)
    rollback = _pattern_case("b", OperationalOutcomeClass.ROLLBACK)
    assert success is not None and rollback is not None

    candidate = OperatingPatternCompiler().compile((success, rollback))

    assert candidate is not None
    assert candidate.failure_fingerprint == success.failure_fingerprint
    assert dict(candidate.outcome_counts) == {"rollback": 1, "success": 1}
    assert candidate.immutable_case_refs == (
        success.immutable_case_ref,
        rollback.immutable_case_ref,
    )
    assert (
        OperatingPatternCompiler().compile(
            (success, replace(rollback, action_type="ops.scale-out"))
        )
        is None
    )
    assert (
        OperatingPatternCompiler().compile(
            (success, replace(rollback, failure_fingerprint="f" * 64))
        )
        is None
    )
