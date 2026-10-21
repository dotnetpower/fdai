from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fdai_deployment_cli.lifecycle_release import NGINX_ACCEPTANCE_SCHEMA

from fdai_lifecycle_agent.agent import AgentSettings, LifecycleAgent
from fdai_lifecycle_agent.cli import LOCAL_POLICY_SCHEMA, load_local_policy
from fdai_lifecycle_agent.dry_run import EntityState, Health, load_current_state
from fdai_lifecycle_agent.inputs import SignedArtifact

if TYPE_CHECKING:
    from conftest import FakeCluster, Harness


def _release(harness: Harness, version: str = "1.5.0", label: str = "nginx-new") -> str:
    document: dict[str, object] = {
        "schema_version": NGINX_ACCEPTANCE_SCHEMA,
        "release_version": version,
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "workloads": {"nginx": {"image_digest": harness.image(label)}},
    }
    return harness.add_release(document)


def _prepare(harness: Harness, *, enabled: bool = True) -> AgentSettings:
    harness.current_state = replace(
        harness.current_state,
        schema_revision=0,
        entities={
            "nginx": EntityState("1.4.0", frozenset({harness.image("nginx-old")}), Health.HEALTHY)
        },
    )
    envelope = harness.maximum_envelope(entity_ids=frozenset({"nginx"}), capability_modes={})
    harness.serve(
        harness.plan(
            entity_ids=frozenset({"nginx"}),
            capability_ids=(),
            envelope=envelope,
            target_release_digest=_release(harness),
        )
    )
    return harness.settings(
        maximum_envelope=envelope,
        entity_components={"nginx": frozenset({"nginx"})},
        component_repositories={"nginx": "registry.example.test/acceptance/nginx"},
        nginx_acceptance=enabled,
    )


def test_nginx_is_denied_by_default_without_kubernetes_writes(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = _prepare(harness, enabled=False)
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert (result.outcome, result.reason_code) == ("rejected", "release_schema_unsupported")
    assert cluster.writes() == []


def test_explicit_nginx_profile_applies_only_its_namespaced_workload(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = _prepare(harness)
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert result.outcome == "applied"
    assert load_current_state(harness.state_file).entities["nginx"].release_id == "1.5.0"
    assert harness.hub.states[-1] == json.loads(harness.state_file.read_text())
    assert {kind for _, kind, _ in cluster.writes()} == {"Deployment", "Service"}
    assert all(
        item["metadata"]["namespace"] == cluster.namespace for item in cluster.objects.values()
    )


@pytest.mark.parametrize("tamper", ["payload", "signature"])
def test_invalid_nginx_signatures_never_reach_the_cluster(
    harness: Harness, cluster: FakeCluster, tamper: str
) -> None:
    settings = _prepare(harness)
    [(release_id, original)] = [
        (key, artifact)
        for key, artifact in harness.store.releases.items()
        if NGINX_ACCEPTANCE_SCHEMA.encode() in artifact.payload
    ]
    harness.store.releases[release_id] = SignedArtifact(
        original.payload + (b" " if tamper == "payload" else b""),
        original.signature if tamper == "payload" else b"\x00" * 64,
    )
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert result.reason_code == "release_signature_invalid"
    assert cluster.writes() == []


@pytest.mark.parametrize("problem", ["version", "expiry", "stale"])
def test_nginx_plan_bindings_remain_authoritative(
    harness: Harness, cluster: FakeCluster, problem: str
) -> None:
    settings = _prepare(harness)
    [(digest, _)] = [
        (key, artifact)
        for key, artifact in harness.store.releases.items()
        if NGINX_ACCEPTANCE_SCHEMA.encode() in artifact.payload
    ]
    base = harness.plan()
    plan = harness.plan(
        entity_ids=frozenset({"nginx"}),
        capability_ids=(),
        envelope=settings.maximum_envelope,
        target_release_digest=digest,
        target_release_id="1.6.0" if problem == "version" else base.target_release_id,
        expires_at=base.expires_at - timedelta(days=1) if problem == "expiry" else base.expires_at,
        source_state_digest="f" * 64 if problem == "stale" else base.source_state_digest,
    )
    expected = {
        "version": "release_version_mismatch",
        "expiry": "plan_expired",
        "stale": "plan_source_state_stale",
    }[problem]
    harness.serve(plan)
    result = LifecycleAgent(
        settings, harness.dependencies(apply=harness.apply_mode(cluster))
    ).poll_once()
    assert result.reason_code == expected
    assert cluster.writes() == []


def test_nginx_restart_and_replayed_plan_do_not_repeat_effects(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = _prepare(harness)
    apply = harness.apply_mode(cluster)
    assert (
        LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once().outcome == "applied"
    )
    writes = len(cluster.writes())
    harness.current_state = load_current_state(harness.state_file)
    again = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert again.outcome == "already-reported"
    assert len(cluster.writes()) == writes


def test_failed_nginx_update_restores_the_durable_healthy_rendering(
    harness: Harness, cluster: FakeCluster
) -> None:
    settings = _prepare(harness)
    apply = harness.apply_mode(cluster)
    first = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert first.outcome == "applied"
    healthy = load_current_state(harness.state_file)
    harness.current_state = healthy
    cluster.broken_images.add(
        f"{settings.component_repositories['nginx']}@{harness.image('nginx-broken')}"
    )
    harness.serve(
        harness.plan(
            plan_id="plan-0009",
            sequence=9,
            target_release_id="1.6.0",
            target_release_digest=_release(harness, "1.6.0", "nginx-broken"),
            entity_ids=frozenset({"nginx"}),
            capability_ids=(),
            envelope=settings.maximum_envelope,
        )
    )
    result = LifecycleAgent(settings, harness.dependencies(apply=apply)).poll_once()
    assert result.outcome == "rolled-back"
    restored = load_current_state(harness.state_file)
    assert restored.entities == healthy.entities
    assert restored.schema_revision == 0


@pytest.mark.parametrize(
    "invalid",
    ["components", "entities", "capabilities", "destructive", "non_boolean"],
)
def test_nginx_local_opt_in_cannot_widen_the_effect_envelope(
    harness: Harness, invalid: str
) -> None:
    settings = _prepare(harness)
    with pytest.raises(ValueError, match="nginx"):
        match invalid:
            case "components":
                replace(settings, entity_components={"nginx": frozenset({"core-control-plane"})})
            case "entities":
                replace(
                    settings,
                    maximum_envelope=replace(
                        settings.maximum_envelope, entity_ids=frozenset({"nginx", "other"})
                    ),
                    entity_components={
                        "nginx": frozenset({"nginx"}),
                        "other": frozenset({"nginx"}),
                    },
                )
            case "capabilities":
                replace(
                    settings,
                    maximum_envelope=replace(
                        settings.maximum_envelope,
                        capability_modes={"action:scale-service": "enforce"},
                    ),
                )
            case "destructive":
                replace(
                    settings,
                    maximum_envelope=replace(settings.maximum_envelope, destructive_allowed=True),
                )
            case "non_boolean":
                harness.settings(nginx_acceptance="true")


@pytest.mark.parametrize("enabled", [True, False, "true", 1, None])
def test_nginx_opt_in_is_wired_from_the_strict_local_policy_file(
    tmp_path: Path, enabled: object
) -> None:
    document = {
        "schema": LOCAL_POLICY_SCHEMA,
        "entity_ids": ["nginx"],
        "regions": ["korea-central"],
        "capability_modes": {},
        "destructive_allowed": False,
        "max_duration_minutes": 30,
        "entity_components": {"nginx": ["nginx"]},
        "component_images": {"nginx": "registry.example.test/acceptance/nginx"},
        "nginx_acceptance": enabled,
    }
    path = tmp_path / "local-policy.json"
    path.write_text(json.dumps(document))
    if type(enabled) is bool:
        assert load_local_policy(path)["nginx_acceptance"] is enabled
    else:
        with pytest.raises(ValueError, match="nginx_acceptance MUST be a boolean"):
            load_local_policy(path)
