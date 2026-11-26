from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_configuration_entities import (
    EntityConfigurationInput,
    InstallationConfigurationInput,
)
from fdai_deployment_cli.lifecycle_configuration_package import (
    ConfigurationHistoryBinding,
    SignedConfigurationPackage,
    build_installation_configuration_package,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import encryption_key_digest

from fdai_lifecycle_agent.agent import LifecycleAgent
from fdai_lifecycle_agent.configuration_revision import FullRevisionBinding, RetainedRevision
from fdai_lifecycle_agent.inputs import SignedArtifact
from fdai_lifecycle_agent.workload import Manifest

if TYPE_CHECKING:
    from conftest import FakeCluster, Harness

OPAQUE = {"core": "1" * 64, "operator-api": "2" * 64}
PRIVATE_MARKER = "https://installation-only.example.com"
SCHEMA: dict[str, object] = {
    key: {"x-fdai-axis": "Release channel subscription", "x-fdai-owner": "customer"}
    for key in ("region", "replicas")
}


class RevisionFixture:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.key = X25519PrivateKey.generate()
        self.schema = copy.deepcopy(SCHEMA)
        harness.release_document["configuration_schema"] = {
            "format": "fdai.release-configuration-schema.v1",
            "release_version": "1.5.0",
            "schema_sha256": canonical_digest(self.schema),
            "keys": self.schema,
        }
        harness.release_digest = harness.add_release(harness.release_document)
        self.package = self.build()
        self.binding = FullRevisionBinding(
            installation_id="installation-alpha",
            active_digest=self.package.digest,
            entity_bindings=OPAQUE,
            sealed_keys=frozenset({"endpoint"}),
            configuration_key=harness.configuration_key.public_key(),
            installation_key=self.key,
        )
        self.publish(self.package)

    def build(
        self, *, history: tuple[SignedConfigurationPackage, ...] = (), **changes: Any
    ) -> SignedConfigurationPackage:
        source = InstallationConfigurationInput(
            revision_id="a" * 40 if not history else "b" * 40,
            release_version="1.5.0",
            release_digest=self.harness.release_digest,
            configuration_schema=self.schema,
            environment_config={"region": "korea-central"},
            sealed_values={"endpoint": PRIVATE_MARKER},
            sealed_keys=frozenset({"endpoint"}),
            entities=tuple(
                EntityConfigurationInput(
                    entity_id=opaque,
                    entity_overrides=[
                        {"versions": ">=1.0.0 <2.0.0", "values": {"replicas": index}}
                    ],
                    sealed_values={},
                )
                for index, opaque in enumerate(OPAQUE.values(), start=1)
            ),
        )
        return build_installation_configuration_package(
            replace(source, **changes),
            entity_ids=frozenset(OPAQUE.values()),
            signing_key=self.harness.configuration_key,
            installation_key=self.key.public_key(),
            history=history,
        )

    def publish(self, package: SignedConfigurationPackage) -> None:
        self.harness.configuration_digest = package.digest
        self.harness.store.configurations[package.digest] = SignedArtifact(
            package.payload, package.signature
        )
        self.harness.serve(self.harness.plan())

    def poll(self, **overrides: Any) -> Any:
        return self.harness.poll(configuration_binding=self.binding, **overrides)


@pytest.fixture
def revision(harness: Harness) -> RevisionFixture:
    return RevisionFixture(harness)


def test_actual_producer_reaches_agent_and_never_reports_identifiers(
    revision: RevisionFixture, caplog: pytest.LogCaptureFixture
) -> None:
    result = revision.poll()
    assert result.outcome == "dry-run-admitted"
    assert revision.poll().outcome == "already-reported"
    public = json.dumps([result.to_json(), revision.harness.hub.states], default=str)
    public += repr(revision.harness.hub.reports) + caplog.text + repr(revision.binding)
    assert PRIVATE_MARKER not in public
    assert PRIVATE_MARKER.encode() not in revision.package.payload


def test_missing_bindings_or_release_schema_hold_without_calculating(
    revision: RevisionFixture,
) -> None:
    harness = revision.harness

    def calculate(*_args: Any) -> Any:
        pytest.fail("rejected input reached calculation")

    assert harness.poll(compute_change_set=calculate).reason_code == "configuration_unavailable"
    assert revision.poll().outcome == "dry-run-admitted"


@pytest.mark.parametrize(
    "fault",
    [
        "recipient",
        "signer",
        "mapping",
        "coverage",
        "active",
        "release-id",
        "release-digest",
        "schema",
        "package",
        "signature",
        "sealed-coverage",
        "history-gap",
    ],
)
def test_substitution_never_reaches_prepare(
    revision: RevisionFixture, cluster: FakeCluster, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = revision.harness

    def forbidden_decryption(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("unverified input reached decryption")

    monkeypatch.setattr(
        "fdai_lifecycle_agent.configuration_revision.decrypt_installation_configuration_identifiers",
        forbidden_decryption,
    )
    if fault == "recipient":
        revision.binding = replace(revision.binding, installation_key=X25519PrivateKey.generate())
    elif fault == "signer":
        revision.binding = replace(
            revision.binding, configuration_key=harness.release_key.public_key()
        )
    elif fault == "mapping":
        revision.binding = replace(
            revision.binding,
            entity_bindings={"core": OPAQUE["core"], "operator-api": OPAQUE["core"]},
        )
    elif fault == "coverage":
        revision.binding = replace(revision.binding, entity_bindings={"core": OPAQUE["core"]})
    elif fault == "active":
        revision.binding = replace(revision.binding, active_digest="f" * 64)
    elif fault == "release-id":
        harness.serve(harness.plan(target_release_id="1.6.0"))
    elif fault == "history-gap":
        package = revision.build(history=(revision.package,))
        revision.publish(package)
        revision.binding = replace(revision.binding, active_digest=package.digest)
    else:
        document = json.loads(revision.package.payload)
        if fault == "signature":
            artifact = SignedArtifact(revision.package.payload, b"x" * 64)
        else:
            if fault == "release-digest":
                document["release_digest"] = "f" * 64
            elif fault == "schema":
                document["configuration"]["schema"]["replicas"]["default"] = 3
            elif fault == "sealed-coverage":
                document["sealed_keys"] = ["different"]
            else:
                document["revision_id"] = "c" * 40
            payload = canonical_bytes(document)
            artifact = SignedArtifact(payload, harness.configuration_key.sign(payload))
        digest = hashlib.sha256(artifact.payload).hexdigest()
        if fault == "package":
            digest = revision.package.digest
        harness.store.configurations[digest] = artifact
        harness.configuration_digest = digest
        harness.serve(harness.plan())
        revision.binding = replace(revision.binding, active_digest=digest)
    apply = harness.apply_mode(cluster)
    result = revision.poll(apply=apply)
    assert result.outcome == "rejected", result
    assert cluster.calls == []
    assert apply.store.load().journal is None
    assert apply.store.load().healthy == ()


def test_per_entity_values_reach_existing_renderer_and_restarts_do_not_reapply(
    revision: RevisionFixture, cluster: FakeCluster, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = revision.harness
    original = cluster.apply

    def apply_with_actual_replicas(manifest: Manifest, *, dry_run: bool = False) -> None:
        original(manifest, dry_run=dry_run)
        if not dry_run and manifest["kind"] == "Deployment":
            live = cluster.objects[("Deployment", manifest["metadata"]["name"])]
            live["status"].update(
                {
                    key: manifest["spec"]["replicas"]
                    for key in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas")
                }
            )

    monkeypatch.setattr(cluster, "apply", apply_with_actual_replicas)
    mode = harness.apply_mode(cluster)
    settings = harness.settings(
        component_repositories={
            "core-control-plane": "example.test/core",
            "operator-service": "example.test/operator",
        }
    )
    dependencies = harness.dependencies(configuration_binding=revision.binding, apply=mode)
    result = LifecycleAgent(settings, dependencies).poll_once()
    assert result.outcome == "applied"
    assert cluster.objects[("Deployment", "core-control-plane")]["spec"]["replicas"] == 1
    assert cluster.objects[("Deployment", "operator-service")]["spec"]["replicas"] == 2
    calls = list(cluster.calls)
    assert LifecycleAgent(settings, dependencies).poll_once().outcome == "already-reported"
    assert calls == cluster.calls
    for path in harness.state_store.path.parent.iterdir():
        assert PRIVATE_MARKER.encode() not in path.read_bytes()
    assert {report.reason_code for _, _, report in harness.hub.reports} >= {
        "apply_started",
        "applied",
    }


def test_current_and_historical_bindings_are_distinct(revision: RevisionFixture) -> None:
    harness = revision.harness
    old = revision.package
    old_key = harness.configuration_key
    harness.configuration_key = Ed25519PrivateKey.generate()
    revision.key = X25519PrivateKey.generate()
    trust = ConfigurationHistoryBinding(
        old_key.public_key(), encryption_key_digest(revision.binding.installation_key.public_key())
    )
    # Build a valid successor under rotated keys while authenticating its exact old ancestor.
    source = InstallationConfigurationInput(
        revision_id="b" * 40,
        release_version="1.5.0",
        release_digest=harness.release_digest,
        configuration_schema=revision.schema,
        environment_config={},
        sealed_values={"endpoint": PRIVATE_MARKER},
        sealed_keys=frozenset({"endpoint"}),
        entities=tuple(
            EntityConfigurationInput(
                entity_id=opaque,
                entity_overrides=[{"versions": ">=1.0.0 <2.0.0", "values": {}}],
                sealed_values={},
            )
            for opaque in OPAQUE.values()
        ),
    )
    package = build_installation_configuration_package(
        source,
        entity_ids=frozenset(OPAQUE.values()),
        signing_key=harness.configuration_key,
        installation_key=revision.key.public_key(),
        history=(old,),
        history_bindings=(trust,),
    )
    revision.publish(package)
    revision.binding = replace(
        revision.binding,
        active_digest=package.digest,
        configuration_key=harness.configuration_key.public_key(),
        installation_key=revision.key,
        history=(RetainedRevision(old.digest, trust),),
    )
    assert revision.poll().outcome == "dry-run-admitted"


@pytest.mark.parametrize("fault", ["key", "recipient", "digest", "reorder", "old-head"])
def test_agent_rejects_historical_substitution_without_effect(
    revision: RevisionFixture, cluster: FakeCluster, fault: str
) -> None:
    harness = revision.harness
    first = revision.package
    second = revision.build(history=(first,))
    harness.store.configurations[second.digest] = SignedArtifact(second.payload, second.signature)
    third = revision.build(history=(first, second), revision_id="c" * 40)
    revision.publish(third)
    trust = ConfigurationHistoryBinding(
        harness.configuration_key.public_key(), encryption_key_digest(revision.key.public_key())
    )
    history: tuple[RetainedRevision, ...] = (
        RetainedRevision(first.digest, trust),
        RetainedRevision(second.digest, trust),
    )
    if fault == "key":
        history = (
            replace(
                history[0], trust=replace(trust, configuration_key=harness.release_key.public_key())
            ),
            history[1],
        )
    elif fault == "recipient":
        history = (
            replace(history[0], trust=replace(trust, installation_key_digest="f" * 64)),
            history[1],
        )
    elif fault == "digest":
        history = (replace(history[0], digest="f" * 64), history[1])
    elif fault == "reorder":
        history = tuple(reversed(history))
    else:
        revision.publish(first)
    revision.binding = replace(revision.binding, active_digest=third.digest, history=history)
    result = revision.poll(apply=harness.apply_mode(cluster))
    assert result.outcome == "rejected"
    assert cluster.calls == []


def test_accepted_ancestor_entity_scope_is_not_reinterpreted_as_current(
    revision: RevisionFixture,
) -> None:
    source = InstallationConfigurationInput(
        revision_id="0" * 40,
        release_version="1.5.0",
        release_digest=revision.harness.release_digest,
        configuration_schema=revision.schema,
        environment_config={},
        sealed_values={"endpoint": PRIVATE_MARKER},
        sealed_keys=frozenset({"endpoint"}),
        entities=(
            EntityConfigurationInput(
                entity_id=OPAQUE["core"],
                entity_overrides=[{"versions": ">=1.0.0 <2.0.0", "values": {}}],
                sealed_values={},
            ),
        ),
    )
    first = build_installation_configuration_package(
        source,
        entity_ids=frozenset({OPAQUE["core"]}),
        signing_key=revision.harness.configuration_key,
        installation_key=revision.key.public_key(),
    )
    revision.harness.store.configurations[first.digest] = SignedArtifact(
        first.payload, first.signature
    )
    current = revision.build(history=(first,))
    revision.publish(current)
    trust = ConfigurationHistoryBinding(
        revision.harness.configuration_key.public_key(),
        encryption_key_digest(revision.key.public_key()),
    )
    revision.binding = replace(
        revision.binding,
        active_digest=current.digest,
        history=(RetainedRevision(first.digest, trust),),
    )
    assert revision.poll().outcome == "dry-run-admitted"


def test_history_byte_bound_stops_loading_before_the_remaining_ancestors(
    revision: RevisionFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = revision.harness
    trust = ConfigurationHistoryBinding(
        harness.configuration_key.public_key(), encryption_key_digest(revision.key.public_key())
    )
    history: list[RetainedRevision] = []
    for index in range(19):
        payload = bytes([index]) * (1024 * 1024)
        digest = hashlib.sha256(payload).hexdigest()
        harness.store.configurations[digest] = SignedArtifact(payload, b"x" * 64)
        history.append(RetainedRevision(digest, trust))
    revision.binding = replace(revision.binding, history=tuple(history))
    loaded: list[str] = []
    original = harness.store.load

    def load(kind: Any, digest: str) -> Any:
        loaded.append(digest)
        return original(kind, digest)

    monkeypatch.setattr(harness.store, "load", load)
    assert revision.poll().outcome == "rejected"
    assert history[16].digest in loaded
    assert history[17].digest not in loaded


@pytest.mark.parametrize("fault", ["region", "namespace", "replicas", "no-schema", "public-state"])
def test_full_revision_cannot_widen_local_render_authority(
    revision: RevisionFixture, cluster: FakeCluster, fault: str
) -> None:
    harness = revision.harness
    if fault == "no-schema":
        harness.release_document.pop("configuration_schema")
        harness.release_digest = harness.add_release(harness.release_document)
        harness.serve(harness.plan())
    elif fault == "public-state":
        harness.state_store.path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        harness.state_store.path.parent.chmod(0o755)
    else:
        key, value = {
            "region": ("region", "another-region"),
            "namespace": ("namespace", "another"),
            "replicas": ("replicas", 4),
        }[fault]
        revision.schema[key] = {
            "x-fdai-axis": "Release channel subscription",
            "x-fdai-owner": "customer",
        }
        harness.release_document["configuration_schema"] = {
            "format": "fdai.release-configuration-schema.v1",
            "release_version": "1.5.0",
            "schema_sha256": canonical_digest(revision.schema),
            "keys": revision.schema,
        }
        harness.release_digest = harness.add_release(harness.release_document)
        package = revision.build(
            entities=tuple(
                EntityConfigurationInput(
                    entity_id=opaque,
                    entity_overrides=[
                        {
                            "versions": ">=1.0.0 <2.0.0",
                            "values": {key: value} if index else {},
                        }
                    ],
                    sealed_values={},
                )
                for index, opaque in enumerate(OPAQUE.values())
            )
        )
        revision.publish(package)
        revision.binding = replace(revision.binding, active_digest=package.digest)
    mode = harness.apply_mode(cluster)
    result = LifecycleAgent(
        harness.settings(
            component_repositories={
                "core-control-plane": "example.test/core",
                "operator-service": "example.test/operator",
            }
        ),
        harness.dependencies(configuration_binding=revision.binding, apply=mode),
    ).poll_once()
    assert result.outcome == "rejected"
    assert cluster.calls == []
    assert mode.store.load().journal is None


def test_decrypted_reference_reaches_only_its_own_existing_operator_renderer(
    revision: RevisionFixture, cluster: FakeCluster, caplog: pytest.LogCaptureFixture
) -> None:
    harness = revision.harness
    for key in ("workload_profile", "operator_database", "schema_database"):
        revision.schema[key] = {
            "x-fdai-axis": "Release channel subscription",
            "x-fdai-owner": "customer",
        }
    harness.release_document["configuration_schema"] = {
        "format": "fdai.release-configuration-schema.v1",
        "release_version": "1.5.0",
        "schema_sha256": canonical_digest(revision.schema),
        "keys": revision.schema,
    }
    harness.release_digest = harness.add_release(harness.release_document)
    sealed = frozenset({"endpoint", "operator_config_map_name"})
    package = revision.build(
        sealed_values={"endpoint": PRIVATE_MARKER, "operator_config_map_name": "private-core-map"},
        sealed_keys=sealed,
        entities=(
            EntityConfigurationInput(
                entity_id=OPAQUE["core"],
                entity_overrides=[{"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 1}}],
                sealed_values={},
            ),
            EntityConfigurationInput(
                entity_id=OPAQUE["operator-api"],
                entity_overrides=[
                    {
                        "versions": ">=1.0.0 <2.0.0",
                        "values": {
                            "replicas": 1,
                            "workload_profile": "operator-service-v1",
                            "operator_database": {"secret_name": "example-operator-database"},
                            "schema_database": {"secret_name": "example-schema-database"},
                        },
                    }
                ],
                sealed_values={"operator_config_map_name": "private-operator-map"},
            ),
        ),
    )
    revision.publish(package)
    revision.binding = replace(revision.binding, active_digest=package.digest, sealed_keys=sealed)
    mode = harness.apply_mode(cluster)
    result = LifecycleAgent(
        harness.settings(
            component_repositories={
                "core-control-plane": "example.test/core",
                "operator-service": "example.test/operator",
            }
        ),
        harness.dependencies(configuration_binding=revision.binding, apply=mode),
    ).poll_once()
    assert result.outcome == "applied", result
    core = cluster.objects[("Deployment", "core-control-plane")]
    operator = cluster.objects[("Deployment", "operator-service")]
    assert "private-operator-map" in json.dumps(operator)
    assert "private-core-map" not in json.dumps(core)
    assert "private-operator-map" not in json.dumps(core)
    public = json.dumps(harness.hub.states) + repr(harness.hub.reports) + caplog.text
    assert "private-operator-map" not in public
    assert PRIVATE_MARKER not in public
    for path in harness.state_store.path.parent.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    assert harness.state_store.path.parent.stat().st_mode & 0o777 == 0o700
