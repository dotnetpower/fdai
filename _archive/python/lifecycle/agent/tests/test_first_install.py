from __future__ import annotations

from datetime import UTC, datetime

import pytest
from lifecycle.agent.tests.test_application_release import prepare, release

from fdai_lifecycle_agent.agent import LifecycleAgent
from fdai_lifecycle_agent.dry_run import (
    EntityState,
    Health,
    compute_change_set,
    load_current_state,
    parse_current_state,
    snapshot_document,
)

IMAGE = "sha256:" + "b" * 64


def test_explicit_empty_state_and_staged_inventory_round_trip():
    document = snapshot_document(
        {"application": EntityState(None, frozenset())},
        schema_revision=0,
        observed_at=datetime(2026, 10, 1, tzinfo=UTC),
        available_artifact_digests=frozenset({IMAGE}),
    )
    state = parse_current_state(document)
    assert state.entities["application"].release_id is None
    assert state.entities["application"].artifact_digests == frozenset()
    assert state.available_artifact_digests == frozenset({IMAGE})


@pytest.mark.parametrize("inventory", [True, "latest", ["latest"], [1]])
def test_invalid_staging_inventory_is_explicitly_rejected(inventory):
    document = snapshot_document(
        {}, schema_revision=0, observed_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    document["available_artifact_digests"] = inventory
    with pytest.raises(ValueError, match="available_artifact_digests"):
        parse_current_state(document)


def test_null_inventory_from_hub_serialization_preserves_legacy_semantics():
    document = snapshot_document(
        {}, schema_revision=0, observed_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    document["available_artifact_digests"] = None
    assert parse_current_state(document).available_artifact_digests is None


@pytest.mark.parametrize(
    "health,images", [(Health.HEALTHY, frozenset()), (Health.UNKNOWN, frozenset({IMAGE}))]
)
def test_empty_entity_cannot_claim_installed_images_or_success(health, images):
    with pytest.raises(ValueError, match="uninstalled entity"):
        EntityState(None, images, health)


@pytest.mark.parametrize("broken", [False, True])
def test_signed_first_release_applies_or_restores_absence_and_replay_preserves_state(
    harness, cluster, broken
):
    settings = prepare(harness)
    digest = release(harness, version="0.0.0")
    image = harness.image("frontend-healthy")
    harness.current_state = parse_current_state(
        snapshot_document(
            {"application": EntityState(None, frozenset())},
            schema_revision=0,
            observed_at=harness.current_state.observed_at,
            available_artifact_digests=frozenset({image}),
        )
    )
    configuration = harness.add_configuration(
        {
            "schema": {},
            "environment": {},
            "entity_overrides": [{"versions": ">=0.0.0", "values": {}}],
        }
    )
    plan = harness.serve(
        harness.plan(
            entity_ids=frozenset({"application"}),
            capability_ids=(),
            envelope=settings.maximum_envelope,
            target_release_id="0.0.0",
            target_release_digest=digest,
            configuration_revision_digest=configuration,
            source_state_digest=harness.current_state.digest,
        )
    )
    change_set = compute_change_set(
        plan, {"application": frozenset({image})}, harness.current_state
    )
    assert change_set.changes[0].action == "create"
    apply = harness.apply_mode(cluster)
    dependencies = harness.dependencies(apply=apply)
    if broken:
        cluster.broken_images.add(f"{settings.component_repositories['frontend']}@{image}")
    result = LifecycleAgent(settings, dependencies).poll_once()
    current = load_current_state(harness.state_file)
    if broken:
        assert result.outcome == "rolled-back"
        assert current.entities["application"].release_id is None
        assert current.entities["application"].artifact_digests == frozenset()
        assert cluster.objects == {}
    else:
        assert result.outcome == "applied"
        assert current.entities["application"].release_id == "0.0.0"
        assert current.entities["application"].artifact_digests == frozenset({image})
        assert len(cluster.objects) == 2
    assert current.available_artifact_digests == frozenset({image})
    writes = len(cluster.writes())
    harness.current_state = current
    assert LifecycleAgent(settings, dependencies).poll_once().outcome == "already-reported"
    assert len(cluster.writes()) == writes
