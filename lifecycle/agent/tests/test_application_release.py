from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fdai_deployment_cli.lifecycle_release import APPLICATION_RELEASE_SCHEMA

from fdai_lifecycle_agent.agent import AgentSettings, LifecycleAgent
from fdai_lifecycle_agent.cli import LOCAL_POLICY_SCHEMA, load_local_policy
from fdai_lifecycle_agent.configuration_rendering import (
    prepare_workload,
    validate_entity_configuration,
)
from fdai_lifecycle_agent.dry_run import EntityState, Health, load_current_state
from fdai_lifecycle_agent.inputs import SignedArtifact, verify_configuration, verify_release
from fdai_lifecycle_agent.workload import WorkloadError

if TYPE_CHECKING:
    from conftest import FakeCluster, Harness


def release(
    harness: Harness,
    product: str = "example-web",
    components: tuple[str, ...] = ("frontend",),
    version: str = "1.5.0",
    label: str = "healthy",
) -> str:
    return harness.add_release(
        {
            "schema_version": APPLICATION_RELEASE_SCHEMA,
            "product": product,
            "release_version": version,
            "source_commit": "a" * 40,
            "platform_tag": "linux-x86_64",
            "workloads": {
                component: {
                    "image_digest": harness.image(f"{component}-{label}"),
                    "port": 9090,
                    "health_path": "/ready",
                }
                for component in components
            },
        }
    )


def prepare(
    harness: Harness,
    product: str = "example-web",
    components: tuple[str, ...] = ("frontend",),
) -> AgentSettings:
    harness.current_state = replace(
        harness.current_state,
        schema_revision=0,
        entities={
            "application": EntityState("1.4.0", frozenset({harness.image("old")}), Health.HEALTHY)
        },
    )
    envelope = harness.maximum_envelope(entity_ids=frozenset({"application"}), capability_modes={})
    harness.serve(
        harness.plan(
            entity_ids=frozenset({"application"}),
            capability_ids=(),
            envelope=envelope,
            target_release_digest=release(harness, product, components),
        )
    )
    return harness.settings(
        maximum_envelope=envelope,
        entity_components={"application": frozenset(components)},
        component_repositories={
            component: f"registry.example.test/application/{component}" for component in components
        },
        product=product,
    )


@pytest.mark.parametrize(
    ("product", "components"),
    [
        ("example-web", ("frontend",)),
        ("example-api", ("frontend", "backend")),
        ("fdai", ("api", "console")),
    ],
)
def test_distinct_applications_apply_without_product_branches(
    harness: Harness, cluster: FakeCluster, product: str, components: tuple[str, ...]
) -> None:
    settings = prepare(harness, product, components)
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert result.outcome == "applied"
    assert load_current_state(harness.state_file).entities["application"].release_id == "1.5.0"
    assert harness.hub.states[-1] == json.loads(harness.state_file.read_text())
    assert {kind for _, kind, _ in cluster.writes()} == {"Deployment", "Service"}
    assert len(cluster.objects) == 2 * len(components)
    for (kind, _), item in cluster.objects.items():
        assert item["metadata"]["namespace"] == cluster.namespace
        if kind == "Deployment":
            container = item["spec"]["template"]["spec"]["containers"][0]
            assert container["ports"][0]["containerPort"] == 9090
            assert container["readinessProbe"]["httpGet"]["path"] == "/ready"


@pytest.mark.parametrize("product", [None, "different-application"])
def test_independent_local_binding_blocks_a_wrong_or_unbound_product(
    harness: Harness, cluster: FakeCluster, product: str | None
) -> None:
    settings = replace(prepare(harness), product=product)
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert (result.outcome, result.reason_code) == ("rejected", "release_product_mismatch")
    assert cluster.writes() == []


@pytest.mark.parametrize("entity_scoped", [False, True])
@pytest.mark.parametrize("entrypoint", ["admission", "preflight"])
def test_verified_application_packages_never_dispatch_to_legacy_profiles(
    harness: Harness, cluster: FakeCluster, entity_scoped: bool, entrypoint: str
) -> None:
    settings = prepare(harness, components=("operator-service",))
    references = {
        "workload_profile": "operator-service-v1",
        "operator_config_map_name": "operator-config-v1",
        "operator_database": {"secret_name": "operator-database-v1"},
        "schema_database": {"secret_name": "schema-reader-v1"},
        "replicas": 1,
    }
    configuration_digest = harness.add_configuration(
        {
            "schema": {
                key: {
                    "default": value,
                    "x-fdai-axis": "installation-path",
                    "x-fdai-owner": "customer",
                }
                for key, value in references.items()
            },
            "environment": {},
            "entity_overrides": [{"versions": ">=1.0.0 <2.0.0", "values": {}}],
        }
    )
    plan = harness.serve(
        harness.plan(
            entity_ids=frozenset({"application"}),
            capability_ids=(),
            envelope=settings.maximum_envelope,
            target_release_digest=release(
                harness, components=("operator-service", "core-control-plane")
            ),
            configuration_revision_digest=configuration_digest,
        )
    )
    dependencies = harness.dependencies()
    verified = verify_release(
        plan, harness.store, dependencies.verify_release_signature, product="example-web"
    )
    configuration = verify_configuration(
        plan, harness.store, dependencies.verify_configuration_signature
    )
    assert verified.schema_version == APPLICATION_RELEASE_SCHEMA
    if entity_scoped:
        configuration = replace(
            configuration,
            values={},
            entity_values={"application": configuration.values},
            render_values={"application": configuration.values},
        )
    apply = harness.apply_mode(cluster)
    with pytest.raises(WorkloadError, match="application_workload_profile_unsupported"):
        if entrypoint == "admission":
            validate_entity_configuration(
                configuration,
                settings.entity_components,
                current_schema=0,
                release=verified,
                plan=plan,
            )
        else:
            prepare_workload(
                plan,
                verified,
                configuration,
                entity_components=settings.entity_components,
                component_repositories={
                    **settings.component_repositories,
                    "core-control-plane": "registry.example.test/application/core",
                },
                workload=apply.workload,
                store=apply.store,
            )
    assert cluster.calls == []
    assert apply.store.load().journal is None


@pytest.mark.parametrize("tamper", ["payload", "signature"])
def test_invalid_signatures_never_reach_the_cluster(
    harness: Harness, cluster: FakeCluster, tamper: str
) -> None:
    settings = prepare(harness)
    [(digest, artifact)] = [
        (key, value)
        for key, value in harness.store.releases.items()
        if APPLICATION_RELEASE_SCHEMA.encode() in value.payload
    ]
    harness.store.releases[digest] = SignedArtifact(
        artifact.payload + (b" " if tamper == "payload" else b""),
        artifact.signature if tamper == "payload" else b"\x00" * 64,
    )
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert result.reason_code == "release_signature_invalid"
    assert cluster.writes() == []


@pytest.mark.parametrize("problem", ["version", "expiry", "stale"])
def test_plan_bindings_remain_authoritative(
    harness: Harness, cluster: FakeCluster, problem: str
) -> None:
    settings = prepare(harness)
    base = harness.plan()
    harness.serve(
        harness.plan(
            entity_ids=frozenset({"application"}),
            capability_ids=(),
            envelope=settings.maximum_envelope,
            target_release_digest=release(harness),
            target_release_id="1.6.0" if problem == "version" else base.target_release_id,
            expires_at=base.expires_at - timedelta(days=1)
            if problem == "expiry"
            else base.expires_at,
            source_state_digest="f" * 64 if problem == "stale" else base.source_state_digest,
        )
    )
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert (
        result.reason_code
        == {
            "version": "release_version_mismatch",
            "expiry": "plan_expired",
            "stale": "plan_source_state_stale",
        }[problem]
    )
    assert cluster.writes() == []


def test_restart_and_replayed_plan_do_not_repeat_effects(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = prepare(harness)
    apply = harness.apply_mode(cluster)
    assert (
        LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome == "applied"
    )
    writes = len(cluster.writes())
    harness.current_state = load_current_state(harness.state_file)
    again = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert again.outcome == "already-reported"
    assert len(cluster.writes()) == writes


def test_failed_update_restores_the_durable_healthy_application(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = prepare(harness)
    apply = harness.apply_mode(cluster)
    assert (
        LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome == "applied"
    )
    healthy = load_current_state(harness.state_file)
    harness.current_state = healthy
    cluster.broken_images.add(
        f"{settings.component_repositories['frontend']}@{harness.image('frontend-broken')}"
    )
    harness.serve(
        harness.plan(
            plan_id="plan-0009",
            sequence=9,
            target_release_id="1.6.0",
            target_release_digest=release(harness, version="1.6.0", label="broken"),
            entity_ids=frozenset({"application"}),
            capability_ids=(),
            envelope=settings.maximum_envelope,
        )
    )
    result = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert result.outcome == "rolled-back"
    restored = load_current_state(harness.state_file)
    assert restored.entities == healthy.entities
    assert restored.schema_revision == 0


@pytest.mark.parametrize("product", ["example-web", None, "", True, "../escape"])
def test_cli_product_binding_is_data_not_an_application_flag(
    tmp_path: Path, product: object
) -> None:
    policy = {
        "schema": LOCAL_POLICY_SCHEMA,
        "entity_ids": ["application"],
        "regions": ["korea-central"],
        "capability_modes": {},
        "destructive_allowed": False,
        "max_duration_minutes": 30,
        "entity_components": {"application": ["frontend"]},
        "product": product,
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    if product is None or product == "example-web":
        assert load_local_policy(path)["product"] == product
    else:
        with pytest.raises(ValueError, match="product"):
            load_local_policy(path)
