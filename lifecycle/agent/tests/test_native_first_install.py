from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_native import NativeApproval, NativeScope
from lifecycle.agent.tests.test_application_release import prepare, release
from lifecycle.agent.tests.test_native_scope import UidProvider

from fdai_lifecycle_agent.agent import LifecycleAgent
from fdai_lifecycle_agent.dry_run import (
    EntityState,
    load_current_state,
    parse_current_state,
    snapshot_document,
)
from fdai_lifecycle_agent.native_bootstrap import bootstrap_native_scope
from fdai_lifecycle_agent.native_cluster import NativeCluster
from fdai_lifecycle_agent.native_state import NativeStateStore


@pytest.mark.parametrize("first_failure", [False, True])
def test_signed_native_first_install_update_recovery_and_restart_replay(harness, first_failure):
    settings = prepare(harness)
    clock = harness.dependencies().clock
    key = Ed25519PrivateKey.generate()
    approval = NativeApproval(
        schema_version="fdai.lifecycle-native-approval.v1",
        scope=NativeScope(
            installation_id=settings.installation_id,
            entity_id="application",
            product=settings.product,
            namespace=harness.namespace,
            components=("frontend",),
        ),
        profile="full-authority-development",
        approved_by="owner",
        approved_at=clock() - timedelta(minutes=1),
        expires_at=clock() + timedelta(hours=1),
    )
    provider = UidProvider()
    store = NativeStateStore(harness.state_store.path.parent)
    bootstrap_native_scope(provider, store, approval, key, clock=clock, apply=True)
    anchor_uid = store.load().anchor_uid
    settings = replace(settings, native_scope_digest=approval.scope.digest)
    configuration = harness.add_configuration(
        {
            "schema": {},
            "environment": {},
            "entity_overrides": [{"versions": ">=0.0.0", "values": {}}],
        }
    )
    staged = frozenset(
        harness.image(f"frontend-{label}") for label in ("healthy", "updated", "broken")
    )
    harness.current_state = parse_current_state(
        snapshot_document(
            {"application": EntityState(None, frozenset())},
            schema_revision=0,
            observed_at=harness.current_state.observed_at,
            available_artifact_digests=staged,
        )
    )

    def poll(version, label, sequence):
        digest = release(harness, version=version, label=label)
        harness.serve(
            harness.plan(
                plan_id=f"native-plan-{sequence}",
                sequence=sequence,
                entity_ids=frozenset({"application"}),
                capability_ids=(),
                envelope=settings.maximum_envelope,
                target_release_id=version,
                target_release_digest=digest,
                configuration_revision_digest=configuration,
                source_state_digest=harness.current_state.digest,
            )
        )
        wrapped = NativeCluster(
            provider, store, approval, key.public_key().public_bytes_raw(), clock
        )
        apply = harness.apply_mode(wrapped)
        dependencies = harness.dependencies(
            apply=apply, read_current_state=lambda: load_current_state(harness.state_file)
        )
        result = LifecycleAgent(settings, dependencies).poll_once()
        harness.current_state = load_current_state(harness.state_file)
        writes = list(provider.calls)
        assert LifecycleAgent(settings, dependencies).poll_once().outcome == "already-reported"
        assert provider.calls == writes
        assert store.load().anchor_uid == anchor_uid
        return result

    initial_image = (
        f"{settings.component_repositories['frontend']}@{harness.image('frontend-healthy')}"
    )
    if first_failure:
        provider.broken_images.add(initial_image)
    result = poll("0.0.0", "healthy", 8)
    if first_failure:
        assert result.outcome == "rolled-back"
        assert harness.current_state.entities["application"].release_id is None
        assert store.load().resources == {}
        assert set(provider.objects) == {("Service", approval.scope.anchor_name)}
        provider.broken_images.clear()
        assert poll("0.0.0", "healthy", 9).outcome == "applied"
    else:
        assert result.outcome == "applied"
    retained = dict(store.load().resources)
    assert poll("1.0.0", "updated", 10).outcome == "applied"
    provider.broken_images.add(
        f"{settings.component_repositories['frontend']}@{harness.image('frontend-broken')}"
    )
    assert poll("1.1.0", "broken", 11).outcome == "rolled-back"
    assert harness.current_state.entities["application"].release_id == "1.0.0"
    assert store.load().resources == retained
    live = provider.get("Deployment", "frontend")
    assert live["spec"]["template"]["spec"]["containers"][0]["image"].endswith(
        harness.image("frontend-updated")
    )
