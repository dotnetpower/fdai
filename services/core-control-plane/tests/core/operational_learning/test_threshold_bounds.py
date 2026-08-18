"""Every governed adaptive threshold stays inside its ontology-declared hard bound.

FDAI-CONST-004 keeps hard bounds in the versioned ontology and active values in policy.
The risk this file removes is drift: a runtime threshold, a pydantic model, and a JSON
contract each restating the same limit, with nothing failing when one of them moves.
"""

from __future__ import annotations

import math
from dataclasses import fields
from decimal import Decimal
from typing import Any

import pytest
from fdai.core.assurance_twin.model_promotion import GraphModelPromotionPolicy
from fdai.core.operational_learning import shadow_dwell
from fdai.core.operational_learning.shadow_dwell import MAX_POLICY_ESCAPES, ShadowDwellThresholds
from fdai.shared.contracts.models import PromotionGate
from fdai.shared.ontology.threshold_bounds import (
    ACTION_TYPE_SCHEMA,
    ADAPTIVE_THRESHOLD_BINDINGS,
    UNBOUND_ADAPTIVE_THRESHOLDS,
    BoundValueType,
    HardBound,
    UnknownBoundError,
    check_within_bounds,
    load_promotion_gate_bounds,
)
from pydantic import ValidationError

BOUNDS = load_promotion_gate_bounds()

#: Every dataclass that owns a numeric adaptive threshold today.
THRESHOLD_OWNERS = (ShadowDwellThresholds, GraphModelPromotionPolicy)


def _numeric_threshold_names() -> set[str]:
    """Return ``Owner.field`` for every numeric threshold field, plus module constants."""

    names = {"shadow_dwell.MAX_POLICY_ESCAPES"}
    for owner in THRESHOLD_OWNERS:
        for field in fields(owner):
            if field.type in {"int", "float"}:
                names.add(f"{owner.__name__}.{field.name}")
    return names


def test_every_adaptive_threshold_field_declares_an_ontology_bound() -> None:
    discovered = _numeric_threshold_names()
    recorded = set(ADAPTIVE_THRESHOLD_BINDINGS) | UNBOUND_ADAPTIVE_THRESHOLDS

    # Non-vacuity: string annotations must actually resolve, or the subset check is empty.
    assert "ShadowDwellThresholds.min_accuracy" in discovered
    assert "GraphModelPromotionPolicy.min_fidelity" in discovered
    assert discovered <= recorded
    assert not (set(ADAPTIVE_THRESHOLD_BINDINGS) & UNBOUND_ADAPTIVE_THRESHOLDS)
    for semantic_id in ADAPTIVE_THRESHOLD_BINDINGS.values():
        assert semantic_id in BOUNDS


def _sweep(bound: HardBound) -> list[tuple[object, bool]]:
    """Return ``(value, expected_inside)`` pairs around one declared bound."""

    integral = bound.value_type is BoundValueType.INTEGER
    step = Decimal(1) if integral else Decimal("0.01")
    cases: list[tuple[object, bool]] = []

    def cast(value: Decimal) -> object:
        return int(value) if integral else float(value)

    if bound.minimum is not None:
        cases.append((cast(bound.minimum - step), False))
        cases.append((cast(bound.minimum), True))
        cases.append((cast(bound.minimum + step), True))
    if bound.maximum is not None:
        cases.append((cast(bound.maximum - step), True))
        cases.append((cast(bound.maximum), True))
        cases.append((cast(bound.maximum + step), False))
    return cases


@pytest.mark.parametrize("semantic_id", sorted(set(ADAPTIVE_THRESHOLD_BINDINGS.values())))
def test_every_adaptive_threshold_stays_inside_its_ontology_bound(semantic_id: str) -> None:
    bound = BOUNDS[semantic_id]
    sweep = _sweep(bound)

    assert sweep, f"{semantic_id} declares no bound to sweep"
    for value, expected_inside in sweep:
        violation = check_within_bounds(semantic_id, value, BOUNDS)
        assert (violation is None) is expected_inside, (semantic_id, value, violation)


@pytest.mark.parametrize("semantic_id", sorted(set(ADAPTIVE_THRESHOLD_BINDINGS.values())))
@pytest.mark.parametrize(
    ("value", "reason_code"),
    [
        (True, "value_type_invalid"),
        ("1", "value_type_invalid"),
        (None, "value_type_invalid"),
        (float("nan"), "value_not_finite"),
        (float("inf"), "value_not_finite"),
    ],
)
def test_non_numeric_and_non_finite_values_are_rejected(
    semantic_id: str,
    value: Any,
    reason_code: str,
) -> None:
    violation = check_within_bounds(semantic_id, value, BOUNDS)

    assert violation is not None
    assert violation.semantic_id == semantic_id
    if BOUNDS[semantic_id].value_type is BoundValueType.INTEGER and isinstance(value, float):
        assert violation.reason_code == "value_type_invalid"
    else:
        assert violation.reason_code == reason_code


def test_an_unregistered_semantic_id_is_an_error_not_a_pass() -> None:
    with pytest.raises(UnknownBoundError):
        check_within_bounds("promotion_gate.not_declared", 1, BOUNDS)


def test_an_exclusive_bound_fails_closed_instead_of_reading_as_unbounded() -> None:
    class _ExclusiveRegistry:
        def get(self, name: str, version: str | None = None) -> dict[str, Any]:  # noqa: ARG002
            return {
                "properties": {
                    "promotion_gate": {
                        "properties": {
                            "min_samples": {"type": "integer", "exclusiveMinimum": 0},
                        }
                    }
                }
            }

        def names(self) -> list[str]:  # pragma: no cover - unused by the loader
            return ["ontology/action-type"]

    with pytest.raises(ValueError, match="exclusive bound"):
        load_promotion_gate_bounds(_ExclusiveRegistry())


def test_bounds_are_loaded_from_the_shipped_contract() -> None:
    assert BOUNDS["promotion_gate.min_accuracy"].source_ref.startswith(
        f"{ACTION_TYPE_SCHEMA[0]}@{ACTION_TYPE_SCHEMA[1]}"
    )
    with pytest.raises(TypeError):
        BOUNDS["promotion_gate.min_samples"] = BOUNDS["promotion_gate.min_samples"]  # type: ignore[index]


def test_the_promotion_gate_model_enforces_exactly_the_declared_bounds() -> None:
    """The pydantic model and the JSON contract must not drift apart."""

    valid = PromotionGate(
        min_shadow_days=int(BOUNDS["promotion_gate.min_shadow_days"].minimum or 1),
        min_samples=int(BOUNDS["promotion_gate.min_samples"].minimum or 1),
        min_accuracy=float(BOUNDS["promotion_gate.min_accuracy"].maximum or 1.0),
        max_policy_escapes=int(BOUNDS["promotion_gate.max_policy_escapes"].minimum or 0),
    )
    assert valid.max_policy_escapes == 0

    for field_name, semantic_id in (
        ("min_shadow_days", "promotion_gate.min_shadow_days"),
        ("min_samples", "promotion_gate.min_samples"),
        ("max_policy_escapes", "promotion_gate.max_policy_escapes"),
    ):
        below = int(BOUNDS[semantic_id].minimum or 0) - 1
        with pytest.raises(ValidationError):
            PromotionGate(**{**valid.model_dump(), field_name: below})

    ceiling = BOUNDS["promotion_gate.min_accuracy"].maximum
    assert ceiling is not None
    with pytest.raises(ValidationError):
        PromotionGate(**{**valid.model_dump(), "min_accuracy": float(ceiling) + 0.01})


def test_the_runtime_rule_may_be_stricter_but_never_looser_than_the_declaration() -> None:
    accuracy_bound = BOUNDS["promotion_gate.min_accuracy"]
    assert accuracy_bound.minimum == Decimal(0)

    # The ontology admits 0.0; shadow dwell is deliberately stricter and rejects it.
    assert check_within_bounds("promotion_gate.min_accuracy", 0.0, BOUNDS) is None
    with pytest.raises(ValueError, match="min_accuracy"):
        ShadowDwellThresholds(min_accuracy=0.0)

    # It is never looser: whatever it accepts is inside the declared bound.
    accepted = ShadowDwellThresholds()
    for field_name, semantic_id in (
        ("min_shadow_days", "promotion_gate.min_shadow_days"),
        ("min_samples", "promotion_gate.min_samples"),
        ("min_accuracy", "promotion_gate.min_accuracy"),
    ):
        assert check_within_bounds(semantic_id, getattr(accepted, field_name), BOUNDS) is None
    assert check_within_bounds("promotion_gate.max_policy_escapes", MAX_POLICY_ESCAPES, BOUNDS) is (
        None
    )


def test_shadow_dwell_floors_are_read_from_the_declaration() -> None:
    assert shadow_dwell._MIN_SHADOW_DAYS_FLOOR == int(
        BOUNDS["promotion_gate.min_shadow_days"].minimum or 0
    )
    assert shadow_dwell._MIN_SAMPLES_FLOOR == int(BOUNDS["promotion_gate.min_samples"].minimum or 0)
    assert math.isclose(
        shadow_dwell._MIN_ACCURACY_CEILING,
        float(BOUNDS["promotion_gate.min_accuracy"].maximum or 0.0),
    )
    # The rejection message stays truthful only while the declared floor is one day.
    assert shadow_dwell._MIN_SHADOW_DAYS_FLOOR == 1
    assert shadow_dwell._MIN_SAMPLES_FLOOR == 1


def test_every_recorded_threshold_is_now_bound_to_a_declaration() -> None:
    """The unbound set is empty; it stays so a future gap has to be recorded here."""

    assert UNBOUND_ADAPTIVE_THRESHOLDS == frozenset()
    assert _numeric_threshold_names() == set(ADAPTIVE_THRESHOLD_BINDINGS)


@pytest.mark.parametrize("field_name", ["min_fidelity", "max_recurrence_rate"])
def test_the_graph_model_policy_reads_its_ratio_range_from_the_declaration(
    field_name: str,
) -> None:
    """A literal range here would keep accepting a value the ontology later narrows."""

    semantic_id = ADAPTIVE_THRESHOLD_BINDINGS[f"GraphModelPromotionPolicy.{field_name}"]
    bound = BOUNDS[semantic_id]
    assert bound.minimum is not None and bound.maximum is not None

    for accepted in (float(bound.minimum), float(bound.maximum)):
        assert getattr(GraphModelPromotionPolicy(**{field_name: accepted}), field_name) == accepted

    for rejected in (float(bound.minimum) - 0.01, float(bound.maximum) + 0.01, math.nan):
        with pytest.raises(ValueError, match=semantic_id):
            GraphModelPromotionPolicy(**{field_name: rejected})
