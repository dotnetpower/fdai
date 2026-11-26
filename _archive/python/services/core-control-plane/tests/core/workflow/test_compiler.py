"""Workflow compiler tests.

Covers:
- A Workflow lowers to a Runbook whose id is the Workflow name and whose
  steps map `action_type_ref` -> `action_type`, preserving `on_failure`.
- The saga compensation map contains only steps that declare
  `compensated_by`.
- `is_shadow` reflects the Workflow default mode.
"""

from __future__ import annotations

from fdai.core.workflow import compile_workflow
from fdai.shared.contracts.models import (
    Mode,
    PromotionGate,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
    WorkflowTriggerKind,
)


def _workflow(*, default_mode: Mode = Mode.SHADOW) -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="sample-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="object.drift"),
        default_mode=default_mode,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        steps=[
            WorkflowStep(id="first", action_type_ref="remediate.tag-add", on_failure="second"),
            WorkflowStep(
                id="second",
                action_type_ref="ops.scale-out",
                compensated_by="ops.scale-in",
            ),
        ],
    )


def test_compile_maps_steps_to_runbook() -> None:
    compiled = compile_workflow(_workflow())
    rb = compiled.runbook
    assert rb.id == "sample-flow"
    assert [s.id for s in rb.steps] == ["first", "second"]
    assert [s.action_type for s in rb.steps] == ["remediate.tag-add", "ops.scale-out"]


def test_compile_preserves_on_failure() -> None:
    compiled = compile_workflow(_workflow())
    first = compiled.runbook.steps[0]
    assert first.on_failure == "second"


def test_compensation_map_contains_only_declaring_steps() -> None:
    compiled = compile_workflow(_workflow())
    assert dict(compiled.compensations) == {"second": "ops.scale-in"}


def test_compensation_map_is_read_only() -> None:
    compiled = compile_workflow(_workflow())
    # MappingProxyType is not assignable - defends the frozen result.
    import pytest

    with pytest.raises(TypeError):
        compiled.compensations["third"] = "ops.flush-cache"  # type: ignore[index]


def test_is_shadow_reflects_default_mode() -> None:
    assert compile_workflow(_workflow()).is_shadow is True
    enforced = compile_workflow(_workflow(default_mode=Mode.ENFORCE))
    assert enforced.is_shadow is False
