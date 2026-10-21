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
from fdai_lifecycle_hub.entity import EntitySettings
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


def test_managed_entity_override_gap_skips_unmatched_release(
    installation: Installation, planner: Planner, now: datetime
) -> None:
    core = next(entity for entity in installation.entities if entity.entity_id == "core")
    console = next(entity for entity in installation.entities if entity.entity_id == "console")
    narrowed = EntitySettings(
        overrides=({"versions": ">=1.4.0 <1.6.0", "values": {"replicas": 3}},)
    )
    with_console_gap = replace(
        installation,
        entities=frozenset(
            {
                core,
                replace(console, ownership=core.ownership, settings=narrowed),
            }
        ),
    )

    outcome = planner(with_console_gap, now)

    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_id == "1.5.0"
    assert [check.release_id for check in outcome.checks] == ["1.6.0", "1.5.0"]
    assert "override_coverage_missing" in {block.reason_code for block in outcome.checks[0].blocks}


def test_full_constraint_matrix_enforces_waiting_vs_skipping_at_hub_entrypoint(
    installation: Installation,
    catalog: ReleaseCatalog,
    key: HubSigningKey,
    now: datetime,
) -> None:
    # 1. Maintenance window and 2. Suppression window hold in Waiting without falling back.
    closed_window = _with_settings(
        installation, windows=(DailyWindow(time(2), timedelta(hours=1), "Asia/Seoul"),)
    )
    maint_outcome = plan_next(closed_window, now, catalog=catalog, key=key)
    assert isinstance(maint_outcome, Waiting) and maint_outcome.release_id == "1.6.0"
    assert "maintenance_window_unavailable" in {
        b.reason_code for b in maint_outcome.checks[0].blocks
    }

    suppressed = replace(
        installation,
        suppressions=(
            SuppressionWindow("entity:core", now - timedelta(minutes=1), now + timedelta(hours=1)),
        ),
    )
    supp_outcome = plan_next(suppressed, now, catalog=catalog, key=key)
    assert isinstance(supp_outcome, Waiting) and supp_outcome.release_id == "1.6.0"
    assert "suppression_window_active" in {b.reason_code for b in supp_outcome.checks[0].blocks}

    # 3. Version range skips 1.6.0 and issues 1.5.0.
    version_outcome = plan_next(
        _with_settings(installation, version_range=">=1.4.0 <1.6.0"), now, catalog=catalog, key=key
    )
    assert isinstance(version_outcome, Issued) and version_outcome.plan.target_release_id == "1.5.0"
    assert "release_version_outside_range" in {
        b.reason_code for b in version_outcome.checks[0].blocks
    }

    # 4. Schema range blocks incompatible schema revisions.
    schema_outcome = plan_next(
        replace(installation, reported=replace(installation.reported, schema_revision=11)),
        now,
        catalog=catalog,
        key=key,
    )
    assert isinstance(schema_outcome, NoEligibleRelease)
    assert "schema_revision_outside_tolerated_range" in {
        b.reason_code for b in schema_outcome.checks[0].blocks
    }

    # 5. Artifact availability blocks when staging inventory lacks required digests.
    artifact_outcome = plan_next(
        replace(
            installation,
            reported=replace(installation.reported, available_artifact_digests=frozenset()),
        ),
        now,
        catalog=catalog,
        key=key,
    )
    assert isinstance(artifact_outcome, NoEligibleRelease)
    assert "artifact_unavailable" in {b.reason_code for b in artifact_outcome.checks[0].blocks}

    # 6. Per-Entity override coverage blocks candidates not covered by a managed Entity's settings.
    core = next(entity for entity in installation.entities if entity.entity_id == "core")
    only_current = EntitySettings(
        overrides=({"versions": ">=1.4.0 <1.5.0", "values": {"replicas": 2}},)
    )
    override_outcome = plan_next(
        replace(
            installation,
            entities=frozenset(
                {
                    replace(core, settings=only_current) if entity.entity_id == "core" else entity
                    for entity in installation.entities
                }
            ),
        ),
        now,
        catalog=catalog,
        key=key,
    )
    assert isinstance(override_outcome, NoEligibleRelease)
    assert all(
        "override_coverage_missing" in {b.reason_code for b in check.blocks}
        for check in override_outcome.checks
    )

    # 7. Data residency blocks when the installation region is outside allowed_regions.
    residency_outcome = plan_next(
        _with_settings(installation, allowed_regions=frozenset({"westeurope"})),
        now,
        catalog=catalog,
        key=key,
    )
    assert isinstance(residency_outcome, NoEligibleRelease)
    assert "data_residency_mismatch" in {b.reason_code for b in residency_outcome.checks[0].blocks}

    # 8. Capability recall blocks candidates declaring the recalled capability.
    cap_recalled = replace(
        catalog,
        recalls=(
            RecallRecord(
                scope="capability",
                target="action:scale-service",
                sequence=1,
                notice_digest="d" * 64,
            ),
        ),
    )
    recall_outcome = plan_next(installation, now, catalog=cap_recalled, key=key)
    assert isinstance(recall_outcome, NoEligibleRelease)
    assert "capability_recalled" in {b.reason_code for b in recall_outcome.checks[0].blocks}


def test_running_recalled_release_issues_rolloff_plan_with_priority(
    installation: Installation,
    catalog: ReleaseCatalog,
    key: HubSigningKey,
    now: datetime,
) -> None:
    running_160 = _with_core_release(installation, "1.6.0")
    recalled_catalog = replace(catalog, recalls=(_recall("1.6.0"),))

    # Even with an active plan:upgrade suppression and a prior open upgrade Plan, recall-rolloff
    # takes priority and rolls off 1.6.0 to the newest non-recalled Release (1.5.0).
    prior = plan_next(installation, now, catalog=catalog, key=key)
    assert isinstance(prior, Issued)
    with_open_and_upgrade_suppression = replace(
        running_160,
        last_sequence=1,
        open_plan=IssuedPlan.from_signed(prior.plan),
        suppressions=(
            SuppressionWindow("plan:upgrade", now - timedelta(minutes=1), now + timedelta(hours=1)),
        ),
    )

    rolloff = plan_next(with_open_and_upgrade_suppression, now, catalog=recalled_catalog, key=key)

    assert isinstance(rolloff, Issued)
    assert rolloff.plan.plan_type == "recall-rolloff"
    assert rolloff.plan.target_release_id == "1.5.0"
    assert rolloff.plan.sequence == 2
    assert [check.release_id for check in rolloff.checks] == ["1.6.0", "1.5.0"]
    assert "release_recalled" in {b.reason_code for b in rolloff.checks[0].blocks}

    # A manual installation-wide suppression still holds recall-rolloff in Waiting.
    manually_suppressed = replace(
        running_160,
        suppressions=(
            SuppressionWindow("installation", now - timedelta(minutes=1), now + timedelta(hours=1)),
        ),
    )
    waiting = plan_next(manually_suppressed, now, catalog=recalled_catalog, key=key)
    assert isinstance(waiting, Waiting)
    assert waiting.release_id == "1.5.0"
    assert "suppression_window_active" in {b.reason_code for b in waiting.checks[-1].blocks}


def test_manual_deployment_change_waits_outside_window_and_reconciles_in_next_matching_window(
    installation: Installation,
    catalog: ReleaseCatalog,
    key: HubSigningKey,
    now: datetime,
) -> None:
    running_latest = _with_core_release(installation, "1.6.0")
    assert plan_next(running_latest, now, catalog=catalog, key=key) == UpToDate()

    # A manual Deployment change alters the running Deployment image/spec and reports drift.
    drifted = replace(
        running_latest,
        reported=replace(
            running_latest.reported,
            entities={
                **running_latest.reported.entities,
                "core": EntityState(
                    release_id="1.6.0",
                    artifact_digests=frozenset({"sha256:" + "d" * 64}),
                    health=Health.DEGRADED,
                ),
            },
        ),
    )

    # Outside the maintenance window, the Hub holds the reconciliation Plan in Waiting.
    outside_window = now - timedelta(hours=3)
    waiting = plan_next(drifted, outside_window, catalog=catalog, key=key)
    assert isinstance(waiting, Waiting)
    assert waiting.release_id == "1.6.0"
    assert "maintenance_window_unavailable" in {b.reason_code for b in waiting.checks[-1].blocks}

    # In the next matching window, the Hub issues a drift-reconciliation Plan for 1.6.0.
    reconciled = plan_next(drifted, now, catalog=catalog, key=key)
    assert isinstance(reconciled, Issued)
    assert reconciled.plan.plan_type == "drift-reconciliation"
    assert reconciled.plan.target_release_id == "1.6.0"
