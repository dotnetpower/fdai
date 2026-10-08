from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow, canonical_plan_payload
from fdai_deployment_cli.runtime_release import RecallRecord

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.domain import (
    DailyWindow,
    EntityState,
    Health,
    Installation,
    Issued,
    IssuedPlan,
    NoEligibleRelease,
    NoManagedEntity,
    Planner,
    Unchanged,
    UpToDate,
    Waiting,
)
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import HubSigningKey, signature_verifier


def _with_settings(installation: Installation, **changes: Any) -> Installation:
    return replace(installation, settings=replace(installation.settings, **changes))


def _with_core_release(installation: Installation, release_id: str) -> Installation:
    reported = installation.reported
    core = replace(reported.entities["core"], release_id=release_id)
    return replace(
        installation, reported=replace(reported, entities={**reported.entities, "core": core})
    )


def _all_managed(installation: Installation) -> Installation:
    """Give every entity the core entity's proven ownership and settings."""

    core = next(entity for entity in installation.entities if entity.entity_id == "core")
    return replace(
        installation,
        entities=frozenset(
            replace(entity, ownership=core.ownership, settings=core.settings)
            for entity in installation.entities
        ),
    )


def _recall(release_id: str) -> RecallRecord:
    return RecallRecord(scope="release", target=release_id, sequence=1, notice_digest="c" * 64)


def test_issues_signed_plan_for_newest_eligible_release(
    installation: Installation, planner: Planner, key: HubSigningKey, now: datetime
) -> None:
    outcome = planner(installation, now)

    assert isinstance(outcome, Issued)
    plan = outcome.plan
    assert (plan.plan_id, plan.sequence, plan.target_release_id) == (
        "installation-alpha-00000001",
        1,
        "1.6.0",
    )
    assert plan.audience == "installation-alpha"
    assert plan.entity_ids == frozenset({"core"})
    assert plan.source_state_digest == installation.reported.digest
    assert plan.envelope.destructive_allowed is False
    assert plan.expires_at == datetime.fromisoformat("2026-10-05T03:30:00+00:00")
    assert plan.signed_payload == canonical_plan_payload(plan)
    verify = signature_verifier({key.key_id: key.public_key})
    assert verify(plan.hub_key_id, plan.signed_payload, plan.signature)
    assert outcome.checks[0].release_id == "1.6.0"
    assert outcome.checks[0].blocks == ()


def test_closed_window_waits_for_newest_release_without_falling_back(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    closed = _with_settings(
        installation, windows=(DailyWindow(time(2), timedelta(hours=1), "Asia/Seoul"),)
    )

    outcome = planner(closed, now)

    assert isinstance(outcome, Waiting)
    assert outcome.release_id == "1.6.0"
    assert [block.reason_code for block in outcome.checks[0].blocks] == [
        "maintenance_window_unavailable"
    ]


def test_active_suppression_waits(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    window = SuppressionWindow("installation", now - timedelta(minutes=5), now + timedelta(hours=1))

    outcome = planner(replace(installation, suppressions=(window,)), now)

    assert isinstance(outcome, Waiting)
    assert outcome.checks[0].blocks[0].reason_code == "suppression_window_active"


def test_recalled_release_is_skipped_for_next_eligible(
    installation: Installation, catalog: ReleaseCatalog, key: HubSigningKey, now: datetime
) -> None:
    recalled = replace(catalog, recalls=(_recall("1.6.0"),))

    outcome = plan_next(installation, now, catalog=recalled, key=key)

    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_id == "1.5.0"
    assert [check.release_id for check in outcome.checks] == ["1.6.0", "1.5.0"]
    assert "release_recalled" in {block.reason_code for block in outcome.checks[0].blocks}


def test_out_of_range_release_is_skipped(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    outcome = planner(_with_settings(installation, version_range=">=1.4.0 <1.6.0"), now)

    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_id == "1.5.0"


def test_no_eligible_release_when_every_candidate_is_blocked(
    installation: Installation, catalog: ReleaseCatalog, key: HubSigningKey, now: datetime
) -> None:
    recalled = replace(catalog, recalls=(_recall("1.6.0"), _recall("1.5.0")))

    outcome = plan_next(installation, now, catalog=recalled, key=key)

    assert isinstance(outcome, NoEligibleRelease)
    assert [check.release_id for check in outcome.checks] == ["1.6.0", "1.5.0"]


def test_up_to_date_when_nothing_newer(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    assert planner(_with_core_release(installation, "1.6.0"), now) == UpToDate()


def test_unmanaged_entities_do_not_hold_back_the_plan(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    reported = installation.reported
    lagging = EntityState(release_id="1.0.0", artifact_digests=frozenset(), health=Health.HEALTHY)
    behind = replace(
        installation, reported=replace(reported, entities={**reported.entities, "console": lagging})
    )

    outcome = planner(_with_core_release(behind, "1.6.0"), now)

    assert outcome == UpToDate()


def test_partial_upgrade_plans_from_the_oldest_managed_entity(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    managed = _all_managed(installation)
    console_ahead = replace(managed.reported.entities["console"], release_id="1.6.0")
    mixed = replace(
        managed,
        reported=replace(
            managed.reported, entities={**managed.reported.entities, "console": console_ahead}
        ),
    )

    assert mixed.current_release == "1.4.0"
    outcome = planner(mixed, now)
    assert isinstance(outcome, Issued)
    assert outcome.plan.entity_ids == frozenset({"core", "console"})


def test_open_plan_is_kept_when_nothing_changed(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    first = planner(installation, now)
    assert isinstance(first, Issued)
    open_plan = IssuedPlan.from_signed(first.plan)

    again = planner(replace(installation, last_sequence=1, open_plan=open_plan), now)

    assert again == Unchanged(open_plan, first.checks)


def test_open_plan_is_replaced_when_reported_state_changed(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    first = planner(installation, now)
    assert isinstance(first, Issued)
    moved = replace(installation.reported, digest="e" * 64)

    again = planner(
        replace(
            installation,
            reported=moved,
            last_sequence=1,
            open_plan=IssuedPlan.from_signed(first.plan),
        ),
        now,
    )

    assert isinstance(again, Issued)
    assert again.plan.plan_id == "installation-alpha-00000002"


@pytest.mark.parametrize("change", ["rotated_key", "newly_managed_entity"])
def test_open_plan_is_replaced_when_signing_key_or_scope_changed(
    installation: Installation,
    catalog: ReleaseCatalog,
    key: HubSigningKey,
    now: datetime,
    change: str,
) -> None:
    first = plan_next(installation, now, catalog=catalog, key=key)
    assert isinstance(first, Issued)
    current = replace(installation, last_sequence=1, open_plan=IssuedPlan.from_signed(first.plan))
    if change == "rotated_key":
        key = HubSigningKey(Ed25519PrivateKey.generate(), epoch=2)
    else:
        current = _all_managed(current)

    again = plan_next(current, now, catalog=catalog, key=key)

    assert isinstance(again, Issued)
    assert again.plan.plan_id == "installation-alpha-00000002"


def test_installation_requires_state_for_every_managed_entity(installation: Installation) -> None:
    entities = {"console": installation.reported.entities["console"]}

    with pytest.raises(ValueError, match="lacks managed entities"):
        replace(installation, reported=replace(installation.reported, entities=entities))


def test_installation_without_managed_entities_gets_no_plan(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    unmanaged = frozenset(replace(entity, settings=None) for entity in installation.entities)

    assert planner(replace(installation, entities=unmanaged), now) == NoManagedEntity()


def test_naive_planning_time_is_rejected(installation: Installation, planner: Planner) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        planner(installation, datetime(2026, 10, 5, 3))
