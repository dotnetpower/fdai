from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fdai.core.hil_resume.escalation_catalog_binding import CatalogEscalationTiming
from fdai.core.hil_resume.escalation_supervisor import EscalationPolicy, HumanNonResponseSupervisor
from fdai.core.hil_resume.forecast_urgency import VerifiedForecastUrgency
from fdai.core.hil_resume.rung_eligibility import DirectoryRungEligibility
from fdai.rule_catalog.schema.escalation_ladder import load_escalation_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.human_identity import (
    HumanIdentity,
    IdentityRosterEntry,
    StaticHumanIdentityDirectory,
)
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.hil_resume.test_escalation_supervisor import (
    VerifiedEligible,
    _park,
    _rungs,
    _supervisor,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)
CATALOG_ROOT = Path(__file__).resolve().parents[5] / "rule-catalog/escalation-ladders"


def _timing(audiences=True):
    mapping = {
        "aw-oncall-primary": ("primary-1",),
        "aw-oncall-secondary": ("backup-1",),
        "aw-incident-commander": ("maintainer-1",),
    }
    return CatalogEscalationTiming(
        load_escalation_catalog(CATALOG_ROOT), "prod", mapping.get if audiences else None
    )


def _context(confidence=0.95):
    return {
        "finding_class": "forecast.breach",
        "impact": "resource_group",
        "remaining_lead_time_seconds": 200,
        "forecast_confidence": confidence,
    }


async def test_catalog_timing_is_snapshotted_and_only_shortens_the_human_window():
    store = InMemoryStateStore()
    supervisor = HumanNonResponseSupervisor(
        state_store=store,
        channel=InMemoryHilChannel(),
        catalog_timing=_timing(),
        eligibility=VerifiedEligible(),
        policy=EscalationPolicy(mode=Mode.ENFORCE),
        clock=lambda: NOW,
    )
    context = {
        **_context(),
        "verified_forecast_urgency": VerifiedForecastUrgency(
            episode_id=UUID(int=1),
            source_digest="a" * 64,
            feature_cutoff=NOW,
            predicted_breach_at=NOW + timedelta(seconds=200),
            expires_at=NOW + timedelta(seconds=200),
            confidence=0.95,
        ),
    }
    parked = supervisor.attach(_park(NOW), rungs=_rungs(), now=NOW, context=context)
    assert parked["escalation"]["catalog_status"] == "resolved"
    assert parked["escalation"]["catalog_ttl_seconds"] == [100, 100, 100]
    assert parked["action"] == _park(NOW)["action"]
    await store.write_state("hil_park:approval-1", parked)
    assert await supervisor.mark_delivered("approval-1", at=NOW)
    updated = await store.read_state("hil_park:approval-1")
    assert updated["escalation"]["decision_deadline"] == (NOW + timedelta(seconds=100)).isoformat()


@pytest.mark.parametrize("confidence", [0.1, None, True, float("nan"), 2.0])
def test_unproven_forecast_never_compresses_catalog_windows(confidence):
    result = _timing().resolve(_context(confidence), [rung.subject_ref for rung in _rungs()])
    assert result["catalog_ttl_seconds"] == [300, 300, 600]


def test_missing_audience_resolution_never_guesses_stewardship_positions():
    result = _timing(False).resolve(_context(), [rung.subject_ref for rung in _rungs()])
    assert result["catalog_status"] == "audience_unavailable"
    assert "catalog_ttl_seconds" not in result


def test_raw_forecast_numbers_never_substitute_for_an_authoritative_source_check():
    result = _timing().resolve(_context(), [rung.subject_ref for rung in _rungs()])
    assert result["catalog_ttl_seconds"] == [300, 300, 600]


def test_enforce_supervisor_cannot_default_to_eligible_without_a_verifier():
    with pytest.raises(ValueError, match="eligibility"):
        HumanNonResponseSupervisor(
            state_store=InMemoryStateStore(),
            channel=InMemoryHilChannel(),
            policy=EscalationPolicy(mode=Mode.ENFORCE),
        )


async def test_unavailable_directory_does_not_advance_or_exhaust_a_rung():
    supervisor, store, channel = await _supervisor(NOW)

    class Unavailable:
        async def is_eligible(self, **kwargs):
            raise OSError("test directory unavailable")

    supervisor._eligibility = Unavailable()
    result = await supervisor.tick(at=NOW)
    after = await store.read_state("hil_park:approval-1")
    assert result.delivery_failed == 1
    assert after["escalation"]["current_rung"] == 0
    assert after["status"] == "pending"
    assert not channel.sent


@pytest.mark.parametrize(
    "role,minimum,expected",
    [
        ("Owner", "Owner", True),
        ("Approver", "Approver", True),
        ("Approver", "Owner", False),
        ("Reader", "Approver", False),
        ("BreakGlass", "Approver", False),
    ],
)
async def test_current_role_verifier_preserves_ordinary_approval_floor(role, minimum, expected):
    identity = HumanIdentity("entra", "subject-1", "example@example.com", "Example")
    row = IdentityRosterEntry("entra", "subject-1", "Example", "person", (role,))
    reader = DirectoryRungEligibility(StaticHumanIdentityDirectory((identity,), (row,)), {})
    assert await reader.is_eligible(subject_ref="subject-1", minimum_role=minimum) is expected
    inactive = replace(identity, active=False)
    reader = DirectoryRungEligibility(StaticHumanIdentityDirectory((inactive,), (row,)), {})
    assert not await reader.is_eligible(subject_ref="subject-1", minimum_role=minimum)


async def test_shadow_integrity_failure_observes_without_resolving_a_live_approval():
    store, channel = InMemoryStateStore(), InMemoryHilChannel()
    supervisor = HumanNonResponseSupervisor(state_store=store, channel=channel, clock=lambda: NOW)
    parked = supervisor.attach(_park(NOW), rungs=_rungs(), now=NOW)
    parked["action"]["action_type"] = "changed-action"
    await store.write_state("hil_park:approval-1", parked)
    result = await supervisor.tick(at=NOW)
    current = await store.read_state("hil_park:approval-1")
    assert result.observed == 1
    assert current["status"] == "pending"
    assert current.get("decision") is None
    assert not channel.sent


async def test_expiry_during_current_role_check_prevents_delivery():
    store, channel = InMemoryStateStore(), InMemoryHilChannel()
    observed = NOW

    class SlowEligibility:
        async def is_eligible(self, **kwargs):
            nonlocal observed
            observed = NOW + timedelta(hours=1)
            return True

    supervisor = HumanNonResponseSupervisor(
        state_store=store,
        channel=channel,
        eligibility=SlowEligibility(),
        policy=EscalationPolicy(mode=Mode.ENFORCE),
        clock=lambda: observed,
    )
    await store.write_state(
        "hil_park:approval-1", supervisor.attach(_park(NOW), rungs=_rungs(), now=NOW)
    )
    result = await supervisor.tick(at=NOW)
    assert result.exhausted == 1
    assert not channel.sent
