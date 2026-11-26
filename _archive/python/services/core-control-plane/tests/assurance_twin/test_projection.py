"""ScratchProjection primitive contract: immutable, deterministic, diff-composable."""

from __future__ import annotations

import pytest
from fdai.core.assurance_twin import (
    InMemoryProjection,
    build_baseline_projection,
)
from fdai.shared.providers.projection import (
    Finding,
    InventoryDiff,
    ResourceRef,
    RuleSet,
    ScratchProjection,
)


def _ref(name: str) -> ResourceRef:
    return ResourceRef(resource_type="object-storage", ref=name)


def test_in_memory_projection_satisfies_protocol():
    proj = build_baseline_projection([(_ref("a"), {"public_access": False})])
    assert isinstance(proj, ScratchProjection)


def test_apply_diff_returns_new_instance():
    original = build_baseline_projection([(_ref("a"), {"public_access": False})])
    updated = original.apply_diff(
        InventoryDiff(kind="update", target=_ref("a"), properties={"public_access": True})
    )
    assert original is not updated
    # Original untouched: still False.
    assert original.properties(_ref("a"))["public_access"] is False
    # Updated reflects the diff.
    assert updated.properties(_ref("a"))["public_access"] is True


def test_create_on_existing_raises():
    proj = build_baseline_projection([(_ref("a"), {"public_access": False})])
    with pytest.raises(ValueError, match="already-present"):
        proj.apply_diff(InventoryDiff(kind="create", target=_ref("a"), properties={}))


def test_update_on_missing_raises():
    proj = build_baseline_projection([])
    with pytest.raises(KeyError):
        proj.apply_diff(InventoryDiff(kind="update", target=_ref("ghost"), properties={"x": 1}))


def test_delete_on_missing_raises():
    proj = build_baseline_projection([])
    with pytest.raises(KeyError):
        proj.apply_diff(InventoryDiff(kind="delete", target=_ref("ghost")))


def test_delete_then_update_raises():
    proj = build_baseline_projection([(_ref("a"), {"x": 1})]).apply_diff(
        InventoryDiff(kind="delete", target=_ref("a"))
    )
    with pytest.raises(KeyError):
        proj.apply_diff(InventoryDiff(kind="update", target=_ref("a"), properties={"x": 2}))


def test_evaluate_uses_bound_evaluator():
    calls: list[RuleSet] = []

    def _fake_evaluator(projection: InMemoryProjection, rules: RuleSet):
        calls.append(rules)
        return [
            Finding(
                rule_id="test.rule",
                resource=_ref("a"),
                severity="high",
                reason="public_access unexpectedly true",
                evidence_refs=("policy:policies/storage/public.rego",),
            )
        ]

    proj = build_baseline_projection(
        [(_ref("a"), {"public_access": True})], evaluator=_fake_evaluator
    )
    findings = proj.evaluate(RuleSet(rule_ids=("test.rule",)))
    assert len(findings) == 1
    assert findings[0].rule_id == "test.rule"
    assert calls[0].rule_ids == ("test.rule",)


def test_evaluate_without_evaluator_returns_empty():
    proj = build_baseline_projection([(_ref("a"), {"x": 1})])
    assert proj.evaluate(RuleSet(rule_ids=("any.rule",))) == ()


def test_diff_sequence_is_deterministic():
    """Two projections applying the same diff sequence produce identical
    resource state.
    """

    left = build_baseline_projection([(_ref("a"), {"x": 1})])
    right = build_baseline_projection([(_ref("a"), {"x": 1})])
    diffs = [
        InventoryDiff(kind="update", target=_ref("a"), properties={"x": 2}),
        InventoryDiff(kind="create", target=_ref("b"), properties={"y": True}),
        InventoryDiff(kind="update", target=_ref("a"), properties={"z": "final"}),
    ]
    for d in diffs:
        left = left.apply_diff(d)
        right = right.apply_diff(d)

    assert left.properties(_ref("a")) == right.properties(_ref("a"))
    assert left.properties(_ref("b")) == right.properties(_ref("b"))


def test_duplicate_baseline_raises():
    with pytest.raises(ValueError, match="duplicate baseline"):
        build_baseline_projection([(_ref("a"), {"x": 1}), (_ref("a"), {"x": 2})])


def test_resource_ref_rejects_empty_fields():
    with pytest.raises(ValueError):
        ResourceRef(resource_type="", ref="a")
    with pytest.raises(ValueError):
        ResourceRef(resource_type="rt", ref="")
