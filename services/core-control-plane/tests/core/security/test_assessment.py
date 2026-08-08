"""Tests for the security assessment report generator."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fdai.core.security.assessment import (
    SecurityVerdict,
    build_security_assessment,
)
from fdai.core.security.observations import (
    ApplicabilityStatus,
    ControlStatus,
    RemediationPriority,
    SecurityControlObservation,
    SecuritySourceCoverage,
    SourceStatus,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, ResourceRef

_AT = datetime(2026, 7, 10, tzinfo=UTC)


def _finding(rule_id: str, severity: str, ref: str = "appgw-1") -> Finding:
    return Finding(
        rule_id=rule_id,
        resource=ResourceRef(resource_type="application-gateway", ref=ref),
        severity=severity,  # type: ignore[arg-type]
        reason=f"{rule_id} tripped",
        evidence_refs=(f"log/{rule_id}",),
    )


def test_off_list_severity_fails_toward_safety_not_crash() -> None:
    # Severity is a Literal, not a runtime enum; a fork / deserialized finding
    # can carry an unexpected value. The fold must not crash - it ranks an
    # unknown severity as most-severe (blocking), mirroring the readiness guard.
    report = build_security_assessment(
        [_finding("weird", "catastrophic")], scope="s", assessed_at=_AT, mode=Mode.ENFORCE
    )
    assert report.verdict is SecurityVerdict.ATTENTION  # unknown -> blocking, not CLEAR
    assert report.blocks_action is True
    assert report.highest_severity == "catastrophic"


def test_empty_findings_is_clear() -> None:
    report = build_security_assessment([], scope="sub-1", assessed_at=_AT)
    assert report.verdict is SecurityVerdict.CLEAR
    assert report.highest_severity is None
    assert report.blocks_action is False
    assert report.summary == "No security findings in scope."


def test_critical_finding_yields_critical_verdict() -> None:
    report = build_security_assessment(
        [_finding("waf-502", "critical"), _finding("tls-weak", "medium")],
        scope="sub-1",
        assessed_at=_AT,
    )
    assert report.verdict is SecurityVerdict.CRITICAL
    assert report.highest_severity == "critical"
    # Most-severe entry sorts first.
    assert report.entries[0].rule_id == "waf-502"
    assert report.counts_by_severity["critical"] == 1
    assert "CRITICAL" in report.summary


def test_high_without_critical_is_attention() -> None:
    report = build_security_assessment([_finding("r", "high")], scope="s", assessed_at=_AT)
    assert report.verdict is SecurityVerdict.ATTENTION


def test_low_and_medium_only_is_clear() -> None:
    report = build_security_assessment(
        [_finding("a", "low"), _finding("b", "medium")], scope="s", assessed_at=_AT
    )
    assert report.verdict is SecurityVerdict.CLEAR


def test_shadow_never_blocks_but_enforce_does() -> None:
    findings = [_finding("waf-502", "critical")]
    shadow = build_security_assessment(findings, scope="s", assessed_at=_AT, mode=Mode.SHADOW)
    enforce = build_security_assessment(findings, scope="s", assessed_at=_AT, mode=Mode.ENFORCE)
    assert shadow.blocks_action is False
    assert enforce.blocks_action is True


def test_enforce_clear_does_not_block() -> None:
    report = build_security_assessment(
        [_finding("a", "low")], scope="s", assessed_at=_AT, mode=Mode.ENFORCE
    )
    assert report.verdict is SecurityVerdict.CLEAR
    assert report.blocks_action is False


def test_entries_preserve_grounding() -> None:
    report = build_security_assessment([_finding("waf-502", "high")], scope="s", assessed_at=_AT)
    entry = report.entries[0]
    assert entry.rule_id == "waf-502"
    assert entry.resource_type == "application-gateway"
    assert entry.evidence_refs == ("log/waf-502",)


def test_stable_sort_by_severity_then_rule_id() -> None:
    report = build_security_assessment(
        [_finding("z", "high"), _finding("a", "high"), _finding("m", "critical")],
        scope="s",
        assessed_at=_AT,
    )
    assert [e.rule_id for e in report.entries] == ["m", "a", "z"]


def test_assessment_preserves_breadth_and_grounding_metrics() -> None:
    report = build_security_assessment(
        [
            _finding("network-policy", "high", ref="cluster-1"),
            _finding("local-accounts", "medium", ref="cluster-1"),
            Finding(
                rule_id="audit-log",
                resource=ResourceRef(resource_type="sql-database", ref="database-1"),
                severity="high",
                reason="audit logging disabled",
            ),
        ],
        scope="subscription",
        assessed_at=_AT,
    )

    assert report.finding_count == 3
    assert report.rule_count == 3
    assert report.affected_resource_count == 2
    assert report.affected_resource_type_count == 2
    assert report.evidence_reference_count == 2
    assert report.findings_without_evidence == 1


def _control(
    control_id: str,
    status: ControlStatus,
    *,
    severity: str = "medium",
    evidence: tuple[str, ...] = ("inventory:snapshot",),
    priority: RemediationPriority = RemediationPriority.NONE,
    remediation: str = "",
    due_days: int | None = None,
    applicability: ApplicabilityStatus = ApplicabilityStatus.APPLICABLE,
    cves: tuple[str, ...] = (),
    compliance: tuple[str, ...] = (),
) -> SecurityControlObservation:
    return SecurityControlObservation(
        control_id=control_id,
        title=control_id.replace("-", " ").title(),
        category="identity" if "identity" in control_id else "network",
        resource_type="kubernetes-cluster",
        resource_ref="cluster-1",
        status=status,
        severity=severity,  # type: ignore[arg-type]
        current_value="disabled",
        expected_value="enabled",
        rationale="The control limits unauthorized access.",
        source="inventory",
        collected_at=_AT,
        evidence_refs=evidence,
        remediation=remediation,
        validation="Re-read the configuration after the change.",
        priority=priority,
        due_days=due_days,
        applicability=applicability,
        cve_ids=cves,
        compliance_controls=compliance,
        source_urls=("https://example.com/security-guidance",),
        managed_service_note="Provider patch state is evaluated separately.",
        patch_status="affected" if cves else "not_assessed",
    )


def test_deep_assessment_derives_coverage_recommendations_and_applicability() -> None:
    controls = (
        _control("private-api", ControlStatus.PASS, compliance=("CIS-1.1",)),
        _control(
            "identity-integration",
            ControlStatus.FAIL,
            severity="high",
            priority=RemediationPriority.CRITICAL,
            remediation="Enable federated identity integration.",
            due_days=1,
            cves=("CVE-2099-0001",),
            compliance=("CIS-2.1", "MCSB-IM-1"),
        ),
        _control(
            "network-policy",
            ControlStatus.WARNING,
            priority=RemediationPriority.HIGH,
            remediation="Apply a namespace network policy.",
            due_days=7,
            cves=("CVE-2099-0002",),
        ),
        _control("patch-evidence", ControlStatus.UNKNOWN, evidence=()),
        _control(
            "cilium-version",
            ControlStatus.NOT_APPLICABLE,
            applicability=ApplicabilityStatus.NOT_APPLICABLE,
            cves=("CVE-2099-0003",),
        ),
    )
    sources = (
        SecuritySourceCoverage(
            source="inventory",
            status=SourceStatus.AVAILABLE,
            record_count=5,
            as_of=_AT,
            fresh=True,
        ),
        SecuritySourceCoverage(
            source="vulnerability-feed",
            status=SourceStatus.PARTIAL,
            record_count=2,
            as_of=_AT,
            fresh=False,
            error="One advisory source timed out.",
        ),
        SecuritySourceCoverage(
            source="policy-compliance",
            status=SourceStatus.UNAVAILABLE,
            record_count=0,
            error="Provider not configured.",
        ),
    )

    report = build_security_assessment(
        [],
        scope="subscription",
        assessed_at=_AT,
        controls=controls,
        source_coverage=sources,
    )

    assert report.verdict is SecurityVerdict.ATTENTION
    assert report.control_count == 5
    assert report.control_status_counts == {
        "pass": 1,
        "fail": 1,
        "warning": 1,
        "not_applicable": 1,
        "unknown": 1,
    }
    assert "1 not applicable" in report.summary
    assert report.control_pass_rate_percent == 33.3
    assert report.evidence_coverage_percent == 80.0
    assert report.source_coverage_percent == 50.0
    assert report.completion_status == "partial"
    assert report.available_source_count == 1
    assert report.partial_source_count == 1
    assert report.unavailable_source_count == 1
    assert report.stale_source_count == 1
    assert report.cve_count == 3
    assert report.applicable_cve_count == 2
    assert report.compliance_control_count == 3
    assert report.recommendation_count == 2
    assert report.critical_recommendation_count == 1
    assert report.high_recommendation_count == 1
    assert report.recommendations[0].control_id == "identity-integration"
    assert report.recommendations[0].due_at == datetime(2026, 7, 11, tzinfo=UTC)
    assert [control.control_id for control in report.positive_controls] == ["private-api"]
    assert [control.control_id for control in report.unknown_controls] == ["patch-evidence"]
    assert report.category_counts == {"identity": 1, "network": 4}
    assert report.resource_type_counts == {"kubernetes-cluster": 5}
    payload = report.to_dict()
    assert payload["completion_status"] == "partial"
    assert len(payload["controls"]) == 5  # type: ignore[arg-type]
    assert json.loads(json.dumps(payload))["recommendations"][0]["priority"] == "critical"


def test_observation_rejects_negative_remediation_sla() -> None:
    import pytest

    with pytest.raises(ValueError, match="due_days"):
        _control("bad-sla", ControlStatus.FAIL, due_days=-1)


def test_observation_rejects_naive_timestamp_and_invalid_applicability() -> None:
    import pytest

    base = _control("timestamp", ControlStatus.PASS)
    with pytest.raises(ValueError, match="timezone-aware"):
        SecurityControlObservation(
            **{
                field: getattr(base, field)
                for field in base.__dataclass_fields__
                if field != "collected_at"
            },
            collected_at=datetime(2026, 7, 10),
        )
    with pytest.raises(ValueError, match="applicability"):
        SecurityControlObservation(
            **{
                field: getattr(base, field)
                for field in base.__dataclass_fields__
                if field != "applicability"
            },
            applicability="Applicable",  # type: ignore[arg-type]
        )


def test_unknown_control_is_a_gap_not_an_actionable_recommendation() -> None:
    report = build_security_assessment(
        [],
        scope="subscription",
        assessed_at=_AT,
        controls=(
            _control(
                "unmeasured-control",
                ControlStatus.UNKNOWN,
                severity="critical",
                priority=RemediationPriority.CRITICAL,
                remediation="Do not execute without evidence.",
            ),
        ),
    )

    assert report.verdict is SecurityVerdict.CLEAR
    assert report.recommendations == ()
    assert report.unknown_controls[0].control_id == "unmeasured-control"
