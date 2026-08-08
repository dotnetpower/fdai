"""WorkflowTriggerIndex tests."""

from __future__ import annotations

from fdai.core.workflow.trigger_index import WorkflowTriggerIndex
from fdai.shared.contracts.models import (
    Mode,
    PromotionGate,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
    WorkflowTriggerKind,
)


def _wf(name: str, *, signal: str | None = None, schedule: str | None = None) -> Workflow:
    if signal is not None:
        trigger = WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type=signal)
    else:
        trigger = WorkflowTrigger(kind=WorkflowTriggerKind.SCHEDULE, schedule=schedule)
    return Workflow(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        trigger=trigger,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        steps=[WorkflowStep(id="s", action_type_ref="remediate.tag-add")],
    )


def test_for_signal_returns_matching_workflows_name_ordered() -> None:
    index = WorkflowTriggerIndex.build(
        [
            _wf("zeta", signal="object.drift"),
            _wf("alpha", signal="object.drift"),
            _wf("other", signal="cost.anomaly"),
        ]
    )
    fired = index.for_signal("object.drift")
    assert [w.name for w in fired] == ["alpha", "zeta"]
    assert [w.name for w in index.for_signal("cost.anomaly")] == ["other"]


def test_for_signal_unknown_is_empty() -> None:
    index = WorkflowTriggerIndex.build([_wf("a", signal="object.drift")])
    assert index.for_signal("nope") == ()


def test_scheduled_lists_schedule_triggers_only() -> None:
    index = WorkflowTriggerIndex.build(
        [
            _wf("nightly", schedule="0 3 * * *"),
            _wf("hourly", schedule="0 * * * *"),
            _wf("on-drift", signal="object.drift"),
        ]
    )
    assert [w.name for w in index.scheduled()] == ["hourly", "nightly"]
    # A schedule workflow does not appear under any signal.
    assert index.for_signal("object.drift") == (index.for_signal("object.drift")[0],)
    assert index.signal_types() == frozenset({"object.drift"})


def test_signal_types_enumerates_covered_signals() -> None:
    index = WorkflowTriggerIndex.build(
        [
            _wf("a", signal="object.drift"),
            _wf("b", signal="cost.anomaly"),
        ]
    )
    assert index.signal_types() == frozenset({"object.drift", "cost.anomaly"})


def test_empty_catalog_builds_cleanly() -> None:
    index = WorkflowTriggerIndex.build([])
    assert index.scheduled() == ()
    assert index.for_signal("anything") == ()
    assert index.signal_types() == frozenset()
