"""Synthetic frozen evidence for alert-quality checks; never runtime composition."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.alert_noise import (
    AlertEvidence,
    AlertGroup,
    AlertRule,
    Audience,
    Evaluation,
    EvidenceStamp,
)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 14, 12, tzinfo=UTC)


@pytest.fixture
def evidence(now: datetime) -> AlertEvidence:
    revision = "sha256:" + "a" * 64
    members = tuple(f"person:{index}" for index in range(10))
    return AlertEvidence(
        stamp=EvidenceStamp(
            source="test:collector",
            tenant_ref="tenant:example",
            scope_ref="scope:example",
            revision=revision,
            observed_at=now,
            recorded_at=now,
            valid_until=now + timedelta(hours=12),
            coverage="complete",
            synthetic=True,
        ),
        window_start=now - timedelta(days=1),
        window_end=now,
        rules=(
            AlertRule(
                ref="rule:example",
                resource_ref="resource:example",
                service_ref="service:example",
                revision=revision,
                kind="metric",
                severity=3,
                classification="operational",
                group_refs=("group:old",),
                iac_owned=True,
                ownership_verified=True,
                evaluation=Evaluation(
                    metric_ref="metric:cpu",
                    operator="above",
                    threshold=80.0,
                    window_seconds=300,
                    frequency_seconds=60,
                    aggregation="average",
                ),
            ),
        ),
        groups=(
            AlertGroup(
                ref="group:old",
                revision=revision,
                audience_refs=("audience:old",),
                rule_refs=("rule:example",),
                reverse_complete=True,
            ),
            AlertGroup(
                ref="group:new",
                revision=revision,
                audience_refs=("audience:new",),
                rule_refs=(),
                reverse_complete=True,
            ),
        ),
        audiences=tuple(
            Audience(
                ref=f"audience:{name}",
                kind="group",
                member_refs=members,
                potential_members=len(members),
                coverage="complete",
                revision=revision,
                primary_verified=True,
                backup_verified=True,
            )
            for name in ("old", "new")
        ),
        delivery_coverage="complete",
        history_coverage="complete",
        independent_collection=True,
    )
