"""Work progress contract tests: density pin, budget telemetry, context receipts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_service_contracts import (
    ContractValidationError,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
    SemanticConversationModelTier,
)
from fdai_service_contracts.semantic_work_progress import (
    CONVERSATION_MODEL_TIER_RECEIPT_ID,
    SemanticContextReceipt,
    SemanticWorkProgress,
    TurnBudgetTelemetry,
    WorkProgressShape,
    context_receipt_digest,
    conversation_model_tier_receipt,
    derive_work_progress_shape,
    parse_context_receipts,
)
from pydantic import ValidationError

_AS_OF = datetime(2026, 9, 28, 10, 42, 3, 980_000, tzinfo=UTC)


def _budget(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "model_calls": {"used": 3, "reserved": 0, "maximum": 5},
        "tokens": {"used": 4382, "reserved": 0, "maximum": 48000},
        "elapsed_ms": {"used": 3136, "reserved": 0, "maximum": 60000},
        "as_of": "2026-09-28T10:42:03.980+00:00",
        "complete": True,
    }
    value.update(overrides)
    return value


def test_shape_follows_the_longest_dependency_depth() -> None:
    shape = derive_work_progress_shape(
        (
            ("resolve", ()),
            ("health", ()),
            ("changes", ("resolve",)),
            ("compare", ("changes", "health")),
        )
    )

    assert shape == WorkProgressShape(density="procedural", waves=3, planned_reads=4)
    assert derive_work_progress_shape((("only", ()),)) == WorkProgressShape(
        density="compact", waves=1, planned_reads=1
    )


@pytest.mark.parametrize(
    "nodes",
    [
        (),
        (("a", ("missing",)),),
        (("a", ()), ("a", ())),
        (("a", ("a",)),),
        tuple((f"n{index}", (f"n{index - 1}",) if index else ()) for index in range(9)),
    ],
)
def test_shape_is_not_pinned_outside_the_contract(
    nodes: tuple[tuple[str, tuple[str, ...]], ...],
) -> None:
    assert derive_work_progress_shape(nodes) is None


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": 1, "density": "compact", "waves": 2, "planned_reads": 1},
        {"schema_version": 1, "density": "compact", "waves": 1, "planned_reads": 2},
        {"schema_version": True, "density": "procedural", "waves": 1, "planned_reads": 2},
        {"schema_version": 1, "density": "procedural", "waves": 9, "planned_reads": 2},
        {"schema_version": 1, "density": "procedural", "waves": True, "planned_reads": 2},
    ],
)
def test_shape_rejects_values_the_console_rejects(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        WorkProgressShape.model_validate(value)


def test_budget_round_trips_in_the_console_wire_shape() -> None:
    budget = TurnBudgetTelemetry.model_validate(_budget())

    assert budget.model_dump(mode="json", exclude_none=True) == _budget()


@pytest.mark.parametrize(
    ("overrides", "valid"),
    [
        ({"tokens": {"used": 48100, "reserved": 0, "maximum": 48000}}, False),
        (
            {
                "tokens": {"used": 48100, "reserved": 0, "maximum": 48000},
                "exhaustion_reason": "tokens",
            },
            True,
        ),
        ({"elapsed_ms": {"used": 60820, "reserved": 0, "maximum": 60000}}, False),
        (
            {
                "elapsed_ms": {"used": 60820, "reserved": 0, "maximum": 60000},
                "exhaustion_reason": "deadline",
            },
            True,
        ),
        ({"elapsed_ms": {"used": 10, "reserved": 1, "maximum": 60000}}, False),
        (
            {
                "model_calls": {"used": 5, "reserved": 1, "maximum": 5},
                "exhaustion_reason": "model_calls",
            },
            False,
        ),
        ({"complete": 1}, False),
        ({"as_of": "2026-09-28T10:42:03.980"}, False),
        ({"exhaustion_reason": None}, True),
    ],
)
def test_budget_overshoot_is_allowed_only_for_its_exhaustion_reason(
    overrides: dict[str, object], *, valid: bool
) -> None:
    if valid:
        TurnBudgetTelemetry.model_validate(_budget(**overrides))
        return
    with pytest.raises(ValidationError):
        TurnBudgetTelemetry.model_validate(_budget(**overrides))


def test_tier_receipt_binds_a_bare_digest_to_the_applied_value() -> None:
    receipt = conversation_model_tier_receipt(
        SemanticConversationModelTier.T2,
        observed_at=_AS_OF,
    )
    wire = receipt.model_dump(mode="json")

    assert wire == {
        "receipt_id": CONVERSATION_MODEL_TIER_RECEIPT_ID,
        "kind": "operator_preference",
        "preference": "conversation_model_tier",
        "value": "t2",
        "digest": context_receipt_digest("conversation_model_tier", "t2"),
        "observed_at": "2026-09-28T10:42:03.980+00:00",
        "freshness": "fresh",
    }
    assert len(wire["digest"]) == 64
    assert parse_context_receipts([wire]) == (receipt,)
    with pytest.raises(ValidationError):
        SemanticContextReceipt.model_validate({**wire, "value": "t1"})


def test_receipt_lists_are_bounded_and_unique() -> None:
    wire = conversation_model_tier_receipt(
        SemanticConversationModelTier.T1,
        observed_at=_AS_OF,
    ).model_dump(mode="json")

    with pytest.raises(ValueError, match="unique"):
        parse_context_receipts([wire, wire])
    with pytest.raises(ValueError, match="at most"):
        parse_context_receipts([wire] * 5)
    with pytest.raises(ValueError, match="malformed"):
        parse_context_receipts([{**wire, "kind": "evidence"}])
    with pytest.raises(ValueError, match="list"):
        parse_context_receipts(wire)


def test_live_pin_record_matches_its_schema() -> None:
    record = SemanticWorkProgress(
        request_id="request-1",
        session_id="session-1",
        turn_id="turn-1",
        turn_sequence=1,
        progress_sequence=1,
        work_progress_shape=WorkProgressShape(density="procedural", waves=2, planned_reads=3),
    )
    payload = record.model_dump(mode="json")
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    validator.validate("semantic-work-progress", payload, version="1.0.0")
    assert payload["record_kind"] == "work_progress_shape"
    assert payload["execution_authority"] is False
    with pytest.raises(ValidationError):
        SemanticWorkProgress.model_validate({**payload, "execution_authority": True})
    compact = {
        **payload,
        "work_progress_shape": {**payload["work_progress_shape"], "density": "compact"},
    }
    with pytest.raises(ContractValidationError):
        validator.validate("semantic-work-progress", compact, version="1.0.0")
