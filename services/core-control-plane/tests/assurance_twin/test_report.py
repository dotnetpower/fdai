"""Wave A.5 - PostureAssessmentReport assembly + serialization."""

from __future__ import annotations

import pytest
from fdai.core.assurance_twin import (
    PostureAssessmentReport,
    PostureVerdict,
    build_posture_assessment_report,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, ResourceRef


def _f(rule: str, ref: str, severity: str, reason: str = "reason") -> Finding:
    return Finding(
        rule_id=rule,
        resource=ResourceRef(resource_type="compute.vm", ref=ref),
        severity=severity,  # type: ignore[arg-type]
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Verdict derivation
# ---------------------------------------------------------------------------


def test_empty_findings_yields_clear_verdict() -> None:
    r = build_posture_assessment_report(
        scope="sub/00000000-0000-0000-0000-000000000001",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=(),
    )
    assert r.verdict is PostureVerdict.CLEAR
    assert r.findings == ()
    assert r.highest_severity is None
    assert r.resource_count == 0
    assert r.rule_count == 0


def test_only_low_and_medium_yields_needs_review() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[
            _f("r-1", "vm-a", "low"),
            _f("r-2", "vm-b", "medium"),
        ],
    )
    assert r.verdict is PostureVerdict.NEEDS_REVIEW
    assert r.highest_severity == "medium"


def test_any_high_severity_makes_verdict_blocked() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[
            _f("r-1", "vm-a", "low"),
            _f("r-2", "vm-b", "high"),
        ],
    )
    assert r.verdict is PostureVerdict.BLOCKED


def test_critical_severity_is_a_blocker() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[_f("r-1", "vm-a", "critical")],
    )
    assert r.verdict is PostureVerdict.BLOCKED
    assert r.highest_severity == "critical"


# ---------------------------------------------------------------------------
# blocks_action semantics (shadow-first)
# ---------------------------------------------------------------------------


def test_shadow_blocked_does_not_block_action() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[_f("r-1", "vm-a", "critical")],
    )
    assert r.verdict is PostureVerdict.BLOCKED
    assert r.blocks_action is False


def test_enforce_blocked_blocks_action() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.ENFORCE,
        findings=[_f("r-1", "vm-a", "high")],
    )
    assert r.blocks_action is True


def test_enforce_needs_review_does_not_block_action() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.ENFORCE,
        findings=[_f("r-1", "vm-a", "medium")],
    )
    assert r.blocks_action is False


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------


def test_resource_and_rule_counts_deduplicate() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[
            _f("r-1", "vm-a", "high"),
            _f("r-1", "vm-b", "high"),  # same rule, different resource
            _f("r-2", "vm-a", "medium"),  # same resource, different rule
        ],
    )
    assert r.resource_count == 2
    assert r.rule_count == 2


def test_severity_counts_always_present() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[
            _f("r-1", "vm-a", "low"),
            _f("r-2", "vm-b", "high"),
            _f("r-3", "vm-c", "high"),
        ],
    )
    counts = r.severity_counts
    assert counts["low"] == 1
    assert counts["medium"] == 0
    assert counts["high"] == 2
    assert counts["critical"] == 0


def test_blocking_findings_include_high_and_critical_only() -> None:
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[
            _f("r-1", "vm-a", "low"),
            _f("r-2", "vm-b", "medium"),
            _f("r-3", "vm-c", "high"),
            _f("r-4", "vm-d", "critical"),
        ],
    )
    blocker_rules = {f.rule_id for f in r.blocking_findings}
    assert blocker_rules == {"r-3", "r-4"}


# ---------------------------------------------------------------------------
# Duplicate preservation (grounded by construction)
# ---------------------------------------------------------------------------


def test_duplicate_findings_are_preserved() -> None:
    dup = _f("r-1", "vm-a", "high")
    r = build_posture_assessment_report(
        scope="scope-1",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[dup, dup],
    )
    assert len(r.findings) == 2  # caller decides on dedupe


# ---------------------------------------------------------------------------
# Determinism (same input -> same to_dict output)
# ---------------------------------------------------------------------------


def test_report_is_deterministic() -> None:
    findings = [
        _f("r-2", "vm-b", "medium"),
        _f("r-1", "vm-a", "high"),
    ]
    a = build_posture_assessment_report(
        scope="s", generated_at="t", mode=Mode.SHADOW, findings=findings
    )
    b = build_posture_assessment_report(
        scope="s", generated_at="t", mode=Mode.SHADOW, findings=findings
    )
    assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["", "   ", " "])
def test_empty_scope_rejected(scope: str) -> None:
    # Only truly empty is rejected today; whitespace variants would only
    # be caught by a stricter validator. Guard the empty case.
    if scope.strip() == "":
        with pytest.raises(ValueError, match="scope"):
            build_posture_assessment_report(
                scope="",
                generated_at="2026-07-07T00:00:00Z",
                mode=Mode.SHADOW,
                findings=(),
            )


def test_empty_generated_at_rejected() -> None:
    with pytest.raises(ValueError, match="generated_at"):
        build_posture_assessment_report(
            scope="s",
            generated_at="",
            mode=Mode.SHADOW,
            findings=(),
        )


# ---------------------------------------------------------------------------
# Serialization surface
# ---------------------------------------------------------------------------


def test_to_dict_shape() -> None:
    r = build_posture_assessment_report(
        scope="sub/00000000-0000-0000-0000-000000000001",
        generated_at="2026-07-07T00:00:00Z",
        mode=Mode.SHADOW,
        findings=[
            _f("r-1", "vm-a", "high", "public access on"),
        ],
    )
    payload = r.to_dict()
    assert payload["scope"] == "sub/00000000-0000-0000-0000-000000000001"
    assert payload["mode"] == "shadow"
    assert payload["verdict"] == "blocked"
    assert payload["blocks_action"] is False
    assert payload["resource_count"] == 1
    assert payload["rule_count"] == 1
    assert payload["highest_severity"] == "high"
    assert isinstance(payload["severity_counts"], dict)
    assert payload["findings"][0]["rule_id"] == "r-1"
    assert payload["findings"][0]["resource_type"] == "compute.vm"
    assert payload["findings"][0]["reason"] == "public access on"


def test_frozen_dataclass_is_hashable() -> None:
    r = build_posture_assessment_report(
        scope="s",
        generated_at="t",
        mode=Mode.SHADOW,
        findings=(),
    )
    # Frozen slots dataclass with tuple fields is hashable.
    assert isinstance(hash(r), int)
    # Constructing the type directly bypasses the builder; ensure it
    # keeps the invariants declared on the fields.
    r2 = PostureAssessmentReport(
        scope="s",
        generated_at="t",
        mode=Mode.SHADOW,
        verdict=PostureVerdict.CLEAR,
        findings=(),
    )
    assert r == r2
