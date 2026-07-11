"""Operational Readiness Review coordinator - compose posture + preflight."""

from __future__ import annotations

import pytest

from fdai.core.readiness import (
    HandoffVerdict,
    OwnershipTransfer,
    ReadinessFinding,
    compose_readiness_report,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)
from fdai.shared.providers.projection import Finding, ResourceRef, Severity


def _signal(*, env: str = "non-prod", scope: str = "rg-team-a") -> OwnershipTransfer:
    return OwnershipTransfer(scope=scope, submitter="dev@example.com", target_environment=env)


def _posture(rule_id: str, severity: Severity, ref: str = "rg-team-a/vm-1") -> Finding:
    return Finding(
        rule_id=rule_id,
        resource=ResourceRef(resource_type="vm", ref=ref),
        severity=severity,
        reason="test finding",
    )


def _probe(id_: str, severity: FindingSeverity) -> ProbeFinding:
    return ProbeFinding(
        id=id_,
        category=ProbeCategory.DEPENDENCY_ORDERING,
        severity=severity,
        title="dependency missing",
        evidence=ProbeEvidence(source="nsg:x/rule:deny", detail="no private endpoint"),
        resolution=ProbeResolution(kind=ResolutionKind.MANUAL, guidance="attach a PE"),
    )


def _compose(**kw: object):  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = {
        "signal": _signal(),
        "posture_findings": (),
        "preflight_findings": (),
        "mode": Mode.SHADOW,
        "generated_at": "2026-07-11T00:00:00Z",
    }
    defaults.update(kw)
    return compose_readiness_report(**defaults)  # type: ignore[arg-type]


def test_no_findings_is_clear_and_never_gates() -> None:
    report = _compose(mode=Mode.ENFORCE)
    assert report.verdict is HandoffVerdict.CLEAR
    assert report.blocks_handoff is False
    assert report.findings == ()


def test_warnings_only_is_needs_review() -> None:
    report = _compose(
        posture_findings=(_posture("r.low", "low"), _posture("r.medium", "medium")),
        preflight_findings=(_probe("p.warn", FindingSeverity.WARNING),),
        mode=Mode.ENFORCE,
    )
    assert report.verdict is HandoffVerdict.NEEDS_REVIEW
    assert report.blocking_findings == ()
    assert report.blocks_handoff is False


def test_high_posture_finding_blocks_and_gates_only_in_enforce() -> None:
    findings = (_posture("r.high", "high"),)
    shadow = _compose(posture_findings=findings, mode=Mode.SHADOW)
    assert shadow.verdict is HandoffVerdict.BLOCKED
    assert shadow.blocks_handoff is False  # shadow reports but never gates
    enforce = _compose(posture_findings=findings, mode=Mode.ENFORCE)
    assert enforce.verdict is HandoffVerdict.BLOCKED
    assert enforce.blocks_handoff is True


def test_blocking_probe_finding_blocks() -> None:
    report = _compose(
        preflight_findings=(_probe("p.block", FindingSeverity.BLOCKING),),
        mode=Mode.ENFORCE,
    )
    assert report.verdict is HandoffVerdict.BLOCKED
    assert report.blocks_handoff is True
    assert report.blocking_findings[0].source == "deploy_preflight"


def test_blocking_min_severity_threshold_is_config() -> None:
    # With a critical-only threshold, a high finding no longer gates.
    high_only = _compose(
        posture_findings=(_posture("r.high", "high"),),
        blocking_min_severity="critical",
        mode=Mode.ENFORCE,
    )
    assert high_only.verdict is HandoffVerdict.NEEDS_REVIEW
    assert high_only.blocks_handoff is False
    # A critical finding still gates under the same threshold.
    crit = _compose(
        posture_findings=(_posture("r.crit", "critical"),),
        blocking_min_severity="critical",
        mode=Mode.ENFORCE,
    )
    assert crit.verdict is HandoffVerdict.BLOCKED


def test_prod_environment_gate_forces_critical_blocking() -> None:
    # A lenient threshold that would not gate a critical finding in non-prod...
    findings = (_posture("r.crit", "critical"),)
    # (blocking_min_severity is already "critical" so critical blocks anyway;
    # the prod gate guarantees it independent of a fork lowering the default).
    prod = compose_readiness_report(
        signal=_signal(env="prod"),
        posture_findings=findings,
        preflight_findings=(),
        mode=Mode.ENFORCE,
        generated_at="2026-07-11T00:00:00Z",
    )
    assert prod.verdict is HandoffVerdict.BLOCKED
    assert prod.blocking_findings[0].blocking is True


def test_every_finding_cites_evidence() -> None:
    report = _compose(
        posture_findings=(_posture("r.high", "high"),),
        preflight_findings=(_probe("p.block", FindingSeverity.BLOCKING),),
    )
    for f in report.findings:
        assert f.evidence  # non-empty citation


def test_readiness_finding_requires_evidence() -> None:
    with pytest.raises(ValueError, match="evidence MUST cite"):
        ReadinessFinding(
            evidence="  ",
            severity="high",
            resource="rg-1",
            blocking=True,
            resolution=None,
            source="assurance_twin",
        )


def test_ownership_transfer_validates_fields() -> None:
    with pytest.raises(ValueError, match="scope MUST be non-empty"):
        OwnershipTransfer(scope=" ", submitter="x", target_environment="prod")
    with pytest.raises(ValueError, match="submitter MUST be non-empty"):
        OwnershipTransfer(scope="rg-1", submitter="", target_environment="prod")
    with pytest.raises(ValueError, match="target_environment MUST be non-empty"):
        OwnershipTransfer(scope="rg-1", submitter="x", target_environment="")


def test_to_dict_shape() -> None:
    report = _compose(
        posture_findings=(_posture("r.high", "high"),),
        mode=Mode.ENFORCE,
    )
    d = report.to_dict()
    assert d["verdict"] == "blocked"
    assert d["blocks_handoff"] is True
    assert d["target_environment"] == "non-prod"
    assert d["findings"][0]["evidence"] == "r.high"
    assert d["findings"][0]["source"] == "assurance_twin"


def test_unknown_severity_fails_toward_safety() -> None:
    # Severity is a Literal (not runtime-checked); an unrecognized value from a
    # fork projection must be treated as blocking, never crash the gate
    report = _compose(
        posture_findings=(_posture("r.weird", "urgent"),),  # type: ignore[arg-type]
        mode=Mode.ENFORCE,
    )
    assert report.verdict is HandoffVerdict.BLOCKED
    assert report.blocking_findings[0].evidence == "r.weird"


def test_invalid_blocking_min_severity_rejected() -> None:
    with pytest.raises(ValueError, match="not a known severity"):
        _compose(blocking_min_severity="sev1")  # type: ignore[arg-type]
