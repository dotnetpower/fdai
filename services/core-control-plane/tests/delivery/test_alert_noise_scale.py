"""Round 8: synthetic 500-person, 20-team, 10000-event private evidence admission.

Independent receipts here are test fixtures, never operational or promotion evidence.
"""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.assessment import assess_alert_noise
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.delivery.alert_noise_evidence import ALERT_SCOPE_EVIDENCE_PURPOSE
from fdai_service_contracts.alert_noise import (
    AlertDelivery,
    AlertEvidence,
    AlertGroup,
    Audience,
    NoisePolicy,
    digest_record,
)

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.delivery.test_alert_noise_evidence import (
    SCOPE_KEY,
    _install_record,
    _rebind,
    _source,
)
from tests.delivery.test_alert_noise_evidence import ledger as ledger


def organization(evidence: AlertEvidence, now: datetime) -> tuple[AlertEvidence, AlertEvidence]:
    members = tuple(f"principal:{number:064x}" for number in range(500))
    revision = evidence.stamp.revision
    audiences = [
        Audience(
            ref="audience:role",
            kind="role",
            member_refs=members,
            potential_members=500,
            coverage="complete",
            revision=revision,
            primary_verified=True,
            backup_verified=True,
        )
    ]
    for team in range(20):
        for kind, people in (
            ("group", members[team * 25 : (team + 1) * 25]),
            ("direct", (members[team * 25],)),
        ):
            audiences.append(
                Audience(
                    ref=f"audience:{kind}:{team}",
                    kind=kind,
                    member_refs=people,
                    potential_members=len(people),
                    coverage="complete",
                    revision=revision,
                    primary_verified=True,
                    backup_verified=True,
                )
            )
    groups = tuple(
        AlertGroup(
            ref=f"group:{team}",
            revision=revision,
            audience_refs=(f"audience:group:{team}", f"audience:direct:{team}", "audience:role"),
            rule_refs=(f"rule:{team}",),
            reverse_complete=True,
        )
        for team in range(20)
    )
    rules = tuple(
        evidence.rules[0].model_copy(
            update={
                "ref": f"rule:{team}",
                "resource_ref": f"resource:{team}",
                "service_ref": f"service:{team}",
                "group_refs": (f"group:{team}",),
            }
        )
        for team in range(20)
    )
    deliveries = tuple(
        AlertDelivery(
            ref=f"event:{number}",
            episode_ref=f"episode:{number}",
            rule_ref=f"rule:{0 if number < 8000 else 1 + number % 19}",
            rule_revision=revision,
            condition="fired",
            state="source",
            event_at=now - timedelta(seconds=number + 1),
            receipt_ref=f"receipt:{number}",
        )
        for number in range(10000)
    )
    complete = AlertEvidence.model_validate(
        evidence.model_copy(
            update={
                "stamp": evidence.stamp.model_copy(
                    update={"synthetic": False, "valid_until": now + timedelta(hours=1)}
                ),
                "rules": rules,
                "groups": groups,
                "audiences": tuple(audiences),
                "deliveries": deliveries,
            }
        )
    )
    base = complete.model_copy(
        update={
            "stamp": complete.stamp.model_copy(
                update={"coverage": "partial", "reasons": ("reverse_missing",)}
            ),
            "groups": tuple(row.model_copy(update={"reverse_complete": False}) for row in groups),
        }
    )
    return base, complete


async def test_full_organization_evidence_admits_without_truncation(
    evidence: AlertEvidence, now: datetime, ledger
) -> None:
    base, complete = organization(evidence, now)
    assert len(complete.model_dump_json()) > 2_000_000
    enriched = _rebind(base, complete)
    await _install_record(
        ledger,
        key=SCOPE_KEY,
        payload={"base_digest": digest_record(base), "evidence": enriched.model_dump(mode="json")},
        purpose=ALERT_SCOPE_EVIDENCE_PURPOSE,
    )
    source, _inner = _source(ledger, base)
    observed = await source.collect(now=now)
    assert observed == enriched and len(observed.deliveries) == 10000
    assert len({ref for audience in observed.audiences for ref in audience.member_refs}) == 500
    report = assess_alert_noise(observed, policy=NoisePolicy(), now=now)
    assert report.source_episodes == 10000
    assert len({finding.rule_ref for finding in report.findings}) == 20
    assert all(ref not in report.model_dump_json() for ref in observed.audiences[0].member_refs)
    damaged = await ledger.store.read_state(SCOPE_KEY)
    damaged["payload"]["evidence"]["deliveries"][-1]["condition"] = "resolved"
    await ledger.store.write_state(SCOPE_KEY, damaged)
    with pytest.raises(AlertExecutionHeld):
        await source.collect(now=now)
