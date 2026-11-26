"""Deterministic alert quality, denominator and privacy regressions."""

from datetime import datetime, timedelta

from fdai.core.detection.alert_noise.assessment import assess_alert_noise, audience_bounds
from fdai_service_contracts.alert_noise import AlertDelivery, AlertEvidence, NoisePolicy


def test_source_and_delivery_are_separate(evidence: AlertEvidence, now: datetime) -> None:
    delivery = AlertDelivery(
        ref="event:example",
        episode_ref="episode:example",
        rule_ref="rule:example",
        rule_revision=evidence.rules[0].revision,
        condition="fired",
        state="source",
        event_at=now - timedelta(minutes=1),
        receipt_ref="receipt:example",
    )
    evidence = evidence.model_copy(
        update={"deliveries": (delivery,), "delivery_coverage": "unavailable"}
    )
    result = assess_alert_noise(evidence, policy=NoisePolicy(), now=now)
    assert result.source_episodes == 1
    assert result.confirmed_deliveries is None
    assert result.notification_attempts is None
    assert result.acknowledgements is None
    assert result.execution_authority is False
    assert "person:" not in result.model_dump_json()


def test_verified_overlap_is_not_double_counted(evidence: AlertEvidence) -> None:
    lower, upper, duplicate_paths = audience_bounds(evidence.audiences)
    assert (lower, upper, duplicate_paths) == (10, 10, 10)
    partial = evidence.audiences[1].model_copy(
        update={"coverage": "partial", "potential_members": None}
    )
    assert audience_bounds((evidence.audiences[0], partial)) == (10, None, 10)


def test_stale_evidence_reports_reason(evidence: AlertEvidence, now: datetime) -> None:
    report = assess_alert_noise(evidence, policy=NoisePolicy(), now=now + timedelta(days=1))
    assert report.coverage == "partial"
    assert "stale_evidence" in report.reasons


def test_protected_storm_never_recommends_muting(evidence: AlertEvidence, now: datetime) -> None:
    rule = evidence.rules[0].model_copy(update={"severity": 0})
    deliveries = tuple(
        AlertDelivery(
            ref=f"event:{index}",
            episode_ref=f"episode:{index}",
            rule_ref=rule.ref,
            rule_revision=rule.revision,
            condition="fired",
            state="source",
            event_at=now - timedelta(minutes=1),
            receipt_ref=f"receipt:{index}",
        )
        for index in range(60)
    )
    evidence = evidence.model_copy(update={"rules": (rule,), "deliveries": deliveries})
    report = assess_alert_noise(evidence, policy=NoisePolicy(), now=now)
    assert report.findings
    assert all(item.guidance == "retain-protected" for item in report.findings)


def test_500_people_20_teams_10000_events(evidence: AlertEvidence, now: datetime) -> None:
    audience = evidence.audiences[0].model_copy(
        update={
            "member_refs": tuple(f"person:{index}" for index in range(500)),
            "potential_members": 500,
        }
    )
    rules = tuple(
        evidence.rules[0].model_copy(
            update={
                "ref": f"rule:{index}",
                "service_ref": f"service:{index}",
            }
        )
        for index in range(20)
    )
    deliveries = tuple(
        AlertDelivery(
            ref=f"event:{index}",
            episode_ref=f"episode:{index}",
            rule_ref=rules[index % 20].ref,
            rule_revision=rules[0].revision,
            condition="fired",
            state="delivered",
            audience_ref=audience.ref,
            attempt_ref=f"attempt:{index}",
            event_at=now - timedelta(seconds=1),
            receipt_ref=f"receipt:{index}",
        )
        for index in range(10000)
    )
    evidence = AlertEvidence.model_validate(
        evidence.model_copy(
            update={
                "rules": rules,
                "deliveries": deliveries,
                "audiences": (audience,),
            }
        ).model_dump()
    )
    report = assess_alert_noise(evidence, policy=NoisePolicy(), now=now)
    assert report.source_episodes == 10000
    assert report.confirmed_deliveries == 10000
    assert len({item.service_ref for item in report.findings}) == 20
