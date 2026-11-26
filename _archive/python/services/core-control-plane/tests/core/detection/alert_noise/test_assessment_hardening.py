"""Round 9: incomplete effective routing cannot be projected as complete assessment."""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.assessment import assess_alert_noise
from fdai_service_contracts.alert_noise import AlertEvidence, NoisePolicy, ProcessingRule


@pytest.mark.parametrize("missing", ["group", "audience", "membership", "processing_add"])
def test_routing_gaps_lower_report_completeness(
    evidence: AlertEvidence, now: datetime, missing: str
) -> None:
    if missing == "group":
        evidence = evidence.model_copy(update={"groups": ()})
    elif missing == "audience":
        evidence = evidence.model_copy(update={"audiences": ()})
    elif missing == "membership":
        evidence = evidence.model_copy(
            update={
                "audiences": tuple(
                    row.model_copy(update={"coverage": "partial", "potential_members": None})
                    for row in evidence.audiences
                )
            }
        )
    else:
        processing = ProcessingRule(
            ref="processing:historical",
            revision=evidence.stamp.revision,
            rule_refs=(evidence.rules[0].ref,),
            action="add",
            group_refs=(evidence.groups[1].ref,),
            enabled=True,
            effective_from=now - timedelta(hours=1),
            effective_to=now + timedelta(hours=1),
            semantics_complete=True,
        )
        evidence = evidence.model_copy(update={"processing_rules": (processing,)})
    report = assess_alert_noise(evidence, policy=NoisePolicy(), now=now)
    assert report.coverage == "partial"
    assert "routing_coverage_incomplete" in report.reasons
    assert any(row.reason == "incomplete" for row in report.findings)
    assert all(row.potential_recipients_upper is None for row in report.findings)
    assert report.execution_authority is False


def test_unowned_protected_route_never_recommends_removal(
    evidence: AlertEvidence, now: datetime
) -> None:
    rule = evidence.rules[0].model_copy(
        update={"ownership_verified": False, "classification": "unknown"}
    )
    report = assess_alert_noise(
        evidence.model_copy(update={"rules": (rule,)}), policy=NoisePolicy(), now=now
    )
    assert {row.reason for row in report.findings} == {"unowned", "protected"}
    assert all(row.protected and row.guidance == "retain-protected" for row in report.findings)


def test_incomplete_reason_budget_is_explicit(evidence: AlertEvidence, now: datetime) -> None:
    evidence = evidence.model_copy(
        update={
            "stamp": evidence.stamp.model_copy(
                update={"coverage": "partial", "reasons": tuple(f"reason:{i}" for i in range(32))}
            ),
            "delivery_coverage": "unavailable",
            "history_coverage": "unavailable",
        }
    )
    report = assess_alert_noise(evidence, policy=NoisePolicy(), now=now + timedelta(days=1))
    assert len(report.reasons) == 32
    assert "evidence_reason_limit_reached" in report.reasons and report.coverage == "partial"
    with pytest.raises(ValueError, match="timezone"):
        assess_alert_noise(evidence, policy=NoisePolicy(), now=now.replace(tzinfo=None))
