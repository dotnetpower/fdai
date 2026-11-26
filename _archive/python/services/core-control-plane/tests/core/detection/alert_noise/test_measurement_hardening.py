"""Round 2: source episodes, lifecycle attempts and human acknowledgements stay distinct."""

from datetime import datetime, timedelta

from fdai.core.detection.alert_noise.assessment import assess_alert_noise, audience_bounds
from fdai.core.detection.alert_noise.measurement import flapping_transitions, notification_counts
from fdai_service_contracts.alert_noise import AlertDelivery, AlertEvidence, NoisePolicy


def rows(evidence: AlertEvidence, now: datetime) -> tuple[AlertDelivery, ...]:
    return tuple(
        AlertDelivery(
            ref=f"event:{index}",
            episode_ref="episode:one",
            rule_ref=evidence.rules[0].ref,
            rule_revision=evidence.rules[0].revision,
            audience_ref="audience:old",
            attempt_ref="attempt:one",
            acknowledger_ref="principal:one" if state == "acknowledged" else None,
            condition="fired",
            state=state,
            event_at=now - timedelta(seconds=10 - index),
            receipt_ref=f"receipt:{index}",
        )
        for index, state in enumerate(
            ("attempted", "accepted", "delivered", "acknowledged", "acknowledged")
        )
    )


def test_one_attempt_lifecycle_and_duplicate_ack_count_once(
    evidence: AlertEvidence, now: datetime
) -> None:
    assert notification_counts(rows(evidence, now), complete=True) == (1, 1, 1)


def test_unknown_attempt_or_human_is_not_counted_as_proven(
    evidence: AlertEvidence, now: datetime
) -> None:
    observed = rows(evidence, now)
    assert notification_counts(observed, complete=False) == (None, None, None)
    no_attempt = tuple(row.model_copy(update={"attempt_ref": None}) for row in observed)
    assert notification_counts(no_attempt, complete=True) == (None, None, 1)
    no_human = tuple(row.model_copy(update={"acknowledger_ref": None}) for row in observed)
    assert notification_counts(no_human, complete=True) == (1, 1, None)


def test_fired_and_resolved_delivery_are_distinct(evidence: AlertEvidence, now: datetime) -> None:
    observed = rows(evidence, now)
    resolved = tuple(
        row.model_copy(
            update={
                "ref": row.ref + ":resolved",
                "condition": "resolved",
                "attempt_ref": "attempt:two",
            }
        )
        for row in observed
    )
    assert notification_counts(observed + resolved, complete=True) == (2, 2, 2)


def test_many_fired_episodes_do_not_prove_flapping(evidence: AlertEvidence, now: datetime) -> None:
    fired = tuple(
        AlertDelivery(
            ref=f"event:{index}",
            episode_ref=f"episode:{index}",
            rule_ref=evidence.rules[0].ref,
            condition="fired",
            state="source",
            event_at=now - timedelta(seconds=100 - index),
            receipt_ref=f"receipt:{index}",
        )
        for index in range(60)
    )
    assert flapping_transitions(fired) == 0
    transitions = tuple(
        row.model_copy(update={"condition": "fired" if i % 2 == 0 else "resolved"})
        for i, row in enumerate(fired)
    )
    assert flapping_transitions(transitions) == 59
    conflict = transitions[1].model_copy(update={"event_at": transitions[0].event_at})
    assert flapping_transitions((transitions[0], conflict)) == 0


def test_partial_audience_upper_bound_and_redaction(evidence: AlertEvidence, now: datetime) -> None:
    audience = evidence.audiences[0].model_copy(
        update={"coverage": "partial", "potential_members": 15}
    )
    assert audience_bounds((audience, evidence.audiences[1])) == (10, 15, 10)
    small = audience.model_copy(update={"member_refs": ("person:one",), "potential_members": 2})
    altered = evidence.model_copy(update={"audiences": (small,)})
    report = assess_alert_noise(altered, policy=NoisePolicy(), now=now)
    assert all(row.potential_recipients_lower is None for row in report.findings)


def test_unavailable_history_remains_unknown(evidence: AlertEvidence, now: datetime) -> None:
    stamp = evidence.stamp.model_copy(
        update={"coverage": "unavailable", "reasons": ("source_missing",)}
    )
    unknown = evidence.model_copy(
        update={
            "stamp": stamp,
            "history_coverage": "unavailable",
            "delivery_coverage": "unavailable",
        }
    )
    report = assess_alert_noise(unknown, policy=NoisePolicy(), now=now)
    assert report.coverage == "unavailable" and report.source_episodes is None
    assert report.notification_attempts is report.acknowledgements is None
