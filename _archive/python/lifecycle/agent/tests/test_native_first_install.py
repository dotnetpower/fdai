from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_native import (
    NativeApproval,
    NativeObjectIdentity,
    NativeScope,
)
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
from fdai_lifecycle_agent.state import write_json_atomically
from fdai_lifecycle_agent.workload import (
    CreationRejectedError,
    WorkloadError,
    object_key,
    render,
)


def test_idle_legacy_agent_rechecks_mode_after_bootstrap_under_poll_lock(harness, monkeypatch):
    settings = prepare(harness)
    harness.current_state = parse_current_state(
        snapshot_document(
            {"application": EntityState(None, frozenset())},
            schema_revision=0,
            observed_at=harness.current_state.observed_at,
        )
    )
    harness.hub.plan = None
    provider = UidProvider()
    apply = harness.apply_mode(provider)
    agent = LifecycleAgent(settings, harness.dependencies(apply=apply))
    assert agent.poll_once().outcome == "no-plan"
    clock = harness.dependencies().clock
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
    bootstrap_native_scope(
        provider,
        NativeStateStore(harness.state_store.path.parent),
        approval,
        Ed25519PrivateKey.generate(),
        current_state_path=harness.state_file,
        clock=clock,
        apply=True,
    )
    before = list(provider.calls)

    def unexpected_poll():
        pytest.fail("mode validation must precede Plan fetch and journal recovery")

    monkeypatch.setattr(agent, "_poll", unexpected_poll)
    with pytest.raises(WorkloadError, match="native_scope_poll_mode_changed"):
        agent.poll_once()
    assert provider.calls == before


@pytest.mark.parametrize("first_failure", ["none", "health", "create-rejected"])
def test_signed_native_first_install_update_recovery_and_restart_replay(
    harness, first_failure, monkeypatch
):
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
    write_json_atomically(harness.state_file, harness.state_document())
    bootstrap_native_scope(
        provider,
        store,
        approval,
        key,
        current_state_path=harness.state_file,
        clock=clock,
        apply=True,
    )
    anchor_uid = store.load().anchor_uid
    settings = replace(settings, native_scope_digest=approval.scope.digest)

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
    create = provider.create
    if first_failure == "health":
        provider.broken_images.add(initial_image)
    elif first_failure == "create-rejected":

        def reject_service(manifest, *, dry_run=False, before_submit=None):
            if not dry_run and manifest["kind"] == "Service":
                raise CreationRejectedError("kubernetes_request_rejected")
            return create(manifest, dry_run=dry_run, before_submit=before_submit)

        monkeypatch.setattr(provider, "create", reject_service)
    result = poll("0.0.0", "healthy", 8)
    if first_failure != "none":
        assert result.outcome == "rolled-back"
        assert harness.current_state.entities["application"].release_id is None
        assert store.load().resources == {}
        assert store.load().pending is None
        assert set(provider.objects) == {("Service", approval.scope.anchor_name)}
        provider.broken_images.clear()
        monkeypatch.setattr(provider, "create", create)
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


@pytest.mark.parametrize("interrupt_after_adoption", [False, True])
def test_agent_plan_adopts_existing_deployment_and_creates_absent_service(
    harness, interrupt_after_adoption
) -> None:
    settings = prepare(harness)
    clock = harness.dependencies().clock
    configuration = harness.add_configuration(
        {
            "schema": {},
            "environment": {},
            "entity_overrides": [{"versions": ">=0.0.0", "values": {}}],
        }
    )
    release_digest = release(harness, version="0.0.0", label="healthy")
    image_digest = harness.image("frontend-healthy")
    harness.current_state = parse_current_state(
        snapshot_document(
            {"application": EntityState(None, frozenset())},
            schema_revision=0,
            observed_at=harness.current_state.observed_at,
            available_artifact_digests=frozenset({image_digest}),
        )
    )
    write_json_atomically(harness.state_file, harness.state_document())
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
        existing_resources=(
            NativeObjectIdentity(
                kind="Deployment",
                name="frontend",
                uid="uid-existing-frontend",
            ),
        ),
    )
    provider = UidProvider()
    desired = render(
        harness.namespace,
        {
            ("application", "frontend"): (
                f"{settings.component_repositories['frontend']}@{image_digest}"
            )
        },
    )
    deployment = next(item for item in desired if item["kind"] == "Deployment")
    existing = deepcopy(dict(deployment))
    existing["metadata"] = dict(existing["metadata"]) | {
        "uid": "uid-existing-frontend",
        "resourceVersion": "7",
        "managedFields": [{"manager": "Terraform"}],
    }
    provider.objects[object_key(existing)] = existing
    key = Ed25519PrivateKey.generate()
    store = NativeStateStore(harness.state_store.path.parent)
    proof = bootstrap_native_scope(
        provider,
        store,
        approval,
        key,
        current_state_path=harness.state_file,
        clock=clock,
        apply=True,
    )
    assert proof is not None
    settings = replace(settings, native_scope_digest=approval.scope.digest)
    plan = harness.plan(
        plan_id="native-adoption-plan",
        sequence=8,
        entity_ids=frozenset({"application"}),
        capability_ids=(),
        envelope=settings.maximum_envelope,
        target_release_id="0.0.0",
        target_release_digest=release_digest,
        configuration_revision_digest=configuration,
        source_state_digest=harness.current_state.digest,
        ownership_digests={"application": proof.claim.digest},
    )
    harness.serve(plan)
    wrapped = NativeCluster(
        provider,
        store,
        approval,
        key.public_key().public_bytes_raw(),
        clock,
    )
    dependencies = harness.dependencies(
        apply=harness.apply_mode(wrapped),
        read_current_state=lambda: load_current_state(harness.state_file),
    )

    if interrupt_after_adoption:
        provider.lose_adoption_response = True
        with pytest.raises(SystemExit, match="simulated process interruption"):
            LifecycleAgent(settings, dependencies).poll_once()
        assert dependencies.apply is not None
        assert dependencies.apply.store.load().journal.phase == "applying"
        assert LifecycleAgent(settings, dependencies).poll_once().outcome == "rolled-back"
        harness.current_state = load_current_state(harness.state_file)
        harness.serve(
            harness.plan(
                plan_id="native-adoption-retry",
                sequence=9,
                entity_ids=frozenset({"application"}),
                capability_ids=(),
                envelope=settings.maximum_envelope,
                target_release_id="0.0.0",
                target_release_digest=release_digest,
                configuration_revision_digest=configuration,
                source_state_digest=harness.current_state.digest,
                ownership_digests={"application": proof.claim.digest},
            )
        )

    result = LifecycleAgent(settings, dependencies).poll_once()
    assert result.outcome == "applied"
    assert store.load().resources == {
        "Deployment/frontend": "uid-existing-frontend",
        "Service/frontend": provider.objects[("Service", "frontend")]["metadata"]["uid"],
    }
    assert provider.adopted == [("Deployment", "frontend")]
    started = next(
        report for _, _, report in harness.hub.reports if report.outcome == "apply-started"
    )
    assert json.loads(started.summary)["ownership_adoptions"] == 1
