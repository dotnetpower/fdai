from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_plan import (
    LifecycleEffectEnvelope,
    LifecyclePlan,
    canonical_plan_payload,
)

from fdai_lifecycle_agent.agent import (
    AgentDependencies,
    AgentSettings,
    HubTrust,
    LifecycleAgent,
    PollResult,
)
from fdai_lifecycle_agent.dry_run import CurrentState, EntityState, Health
from fdai_lifecycle_agent.hub_client import HubProtocolError, PlanReport, SignedPlan
from fdai_lifecycle_agent.inputs import InputKind, SignedArtifact
from fdai_lifecycle_agent.signatures import Ed25519ArtifactVerifier, Ed25519HubKeyring
from fdai_lifecycle_agent.state import LocalStateStore

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
INSTALLATION_ID = "installation-alpha"
ACTIVE_HUB_KEY = "hub-key-active"
REVOKED_HUB_KEY = "hub-key-revoked"


def development_key(label: str) -> Ed25519PrivateKey:
    """Deterministic development test key derived at runtime; no key material is committed."""

    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(label.encode()).digest())


def image(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _encode(document: dict[str, object], *, pretty: bool) -> bytes:
    """Signed files may be pretty-printed; the Plan digest names their canonical JSON."""

    return json.dumps(document, indent=2).encode() if pretty else canonical_bytes(document)


@dataclass
class FakeHubClient:
    """In-memory ``HubClient`` that records every report and raises queued report errors."""

    plan: SignedPlan | None = None
    report_errors: list[HubProtocolError] = field(default_factory=list)
    reports: list[tuple[str, str, PlanReport]] = field(default_factory=list)
    attempted: list[PlanReport] = field(default_factory=list)
    fetches: int = 0

    def fetch_plan(self, installation_id: str) -> SignedPlan | None:
        self.fetches += 1
        return self.plan

    def submit_report(self, installation_id: str, plan_id: str, report: PlanReport) -> None:
        self.attempted.append(report)
        if self.report_errors:
            raise self.report_errors.pop(0)
        self.reports.append((installation_id, plan_id, report))


@dataclass
class FakeArtifactStore:
    releases: dict[str, SignedArtifact] = field(default_factory=dict)
    configurations: dict[str, SignedArtifact] = field(default_factory=dict)
    unreadable: bool = False

    def load(self, kind: InputKind, digest: str) -> SignedArtifact | None:
        if self.unreadable:
            raise PermissionError("synthetic unreadable input")
        return (self.releases if kind == "release" else self.configurations).get(digest)


class Harness:
    """Builds signed Plans, signed inputs, and agent dependencies for one test."""

    def __init__(self, state_dir: Path) -> None:
        self.hub_keys = {
            ACTIVE_HUB_KEY: development_key("hub"),
            REVOKED_HUB_KEY: development_key("hub-old"),
        }
        self.release_key = development_key("vendor-release")
        self.configuration_key = development_key("customer-configuration")
        self.hub = FakeHubClient()
        self.store = FakeArtifactStore()
        self.state_store = LocalStateStore(state_dir)
        self.release_document: dict[str, object] = {
            "schema_version": "fdai.runtime-release.v3",
            "services": {
                "core-control-plane": {"image_digest": image("core-1.5.0")},
                "operator-service": {"image_digest": image("operator-1.5.0")},
            },
            "sidecars": {"pgvector": {"image_digest": image("pgvector")}},
            "installation_agents": {"lifecycle-agent": {"image_digest": image("agent")}},
            "capabilities": {
                "action:scale-service": {"kind": "ActionType", "maximum_mode": "enforce"}
            },
        }
        self.configuration_document: dict[str, object] = {
            "schema": {
                "replicas": {
                    "default": 1,
                    "x-fdai-axis": "Release channel subscription",
                    "x-fdai-owner": "customer",
                }
            },
            "environment": {},
            "entity_overrides": [{"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}}],
        }
        self.release_digest = self.add_release(self.release_document)
        self.configuration_digest = self.add_configuration(self.configuration_document)
        self.current_state = CurrentState(
            digest=hashlib.sha256(b"installation-owned state snapshot").hexdigest(),
            schema_revision=15,
            entities={
                "core": EntityState("1.4.0", frozenset({image("core-1.4.0")}), Health.HEALTHY),
                # An Entity runs only its own images, never the whole Release image set.
                "operator-api": EntityState(
                    "1.5.0", frozenset({image("operator-1.5.0")}), Health.HEALTHY
                ),
            },
            observed_at=NOW - timedelta(hours=1),
        )

    def add_release(
        self, document: dict[str, object], *, signed: bool = True, pretty: bool = False
    ) -> str:
        payload = _encode(document, pretty=pretty)
        signature = self.release_key.sign(payload) if signed else b""
        digest = canonical_digest(document)
        self.store.releases[digest] = SignedArtifact(payload, signature)
        return digest

    def add_configuration(
        self, document: dict[str, object], *, signed: bool = True, pretty: bool = False
    ) -> str:
        payload = _encode(document, pretty=pretty)
        signature = self.configuration_key.sign(payload) if signed else b""
        digest = canonical_digest(document)
        self.store.configurations[digest] = SignedArtifact(payload, signature)
        return digest

    def state_document(self) -> dict[str, object]:
        """The current state in the Hub's reported-state JSON shape."""

        return {
            "digest": self.current_state.digest,
            "schema_revision": self.current_state.schema_revision,
            "entities": {
                entity_id: {
                    "release_id": state.release_id,
                    "artifact_digests": sorted(state.artifact_digests),
                    "health": state.health,
                }
                for entity_id, state in self.current_state.entities.items()
            },
            "observed_at": self.current_state.observed_at.isoformat().replace("+00:00", "Z"),
        }

    def maximum_envelope(self, **overrides: Any) -> LifecycleEffectEnvelope:
        base = LifecycleEffectEnvelope(
            entity_ids=frozenset({"core", "operator-api"}),
            regions=frozenset({"korea-central"}),
            capability_modes={"action:scale-service": "enforce"},
            destructive_allowed=False,
            max_duration_minutes=60,
        )
        return replace(base, **overrides)

    def plan(self, *, signing_key: str | None = None, **overrides: Any) -> LifecyclePlan:
        base = LifecyclePlan(
            plan_id="plan-0008",
            audience=INSTALLATION_ID,
            hub_key_epoch=3,
            hub_key_id=ACTIVE_HUB_KEY,
            source_state_digest=self.current_state.digest,
            sequence=8,
            fencing_generation=4,
            plan_type="upgrade",
            target_release_id="1.5.0",
            target_release_digest=self.release_digest,
            configuration_revision_digest=self.configuration_digest,
            entity_ids=frozenset({"core", "operator-api"}),
            capability_ids=("action:scale-service",),
            release_regions=frozenset({"korea-central"}),
            rollback_target_plan_id=None,
            declared_duration_minutes=15,
            envelope=self.maximum_envelope(max_duration_minutes=30),
            expires_at=NOW + timedelta(minutes=30),
            signed_payload=b"",
            signature=b"",
        )
        plan = replace(base, **overrides)
        payload = canonical_plan_payload(plan)
        key = self.hub_keys[signing_key or plan.hub_key_id]
        return replace(plan, signed_payload=payload, signature=key.sign(payload))

    @staticmethod
    def public_pem(key: Ed25519PrivateKey) -> bytes:
        return key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    @staticmethod
    def image(label: str) -> str:
        return image(label)

    def serve(self, plan: LifecyclePlan) -> LifecyclePlan:
        self.hub.plan = SignedPlan(plan.signed_payload, plan.signature)
        return plan

    def settings(self, **overrides: Any) -> AgentSettings:
        base = AgentSettings(
            installation_id=INSTALLATION_ID,
            trust=HubTrust(
                hub_key_epochs={ACTIVE_HUB_KEY: 3, REVOKED_HUB_KEY: 2},
                revoked_hub_key_ids=frozenset({REVOKED_HUB_KEY}),
                current_hub_key_epoch=3,
                fencing_generation=4,
            ),
            maximum_envelope=self.maximum_envelope(),
        )
        return replace(base, **overrides)

    def dependencies(self, **overrides: Any) -> AgentDependencies:
        base = AgentDependencies(
            hub=self.hub,
            state_store=self.state_store,
            artifact_store=self.store,
            verify_plan_signature=Ed25519HubKeyring(
                {key_id: key.public_key() for key_id, key in self.hub_keys.items()}
            ),
            verify_release_signature=Ed25519ArtifactVerifier(self.release_key.public_key()),
            verify_configuration_signature=Ed25519ArtifactVerifier(
                self.configuration_key.public_key()
            ),
            read_current_state=lambda: self.current_state,
            clock=lambda: NOW,
        )
        return replace(base, **overrides)

    def poll(self, **dependency_overrides: Any) -> PollResult:
        return LifecycleAgent(
            self.settings(), self.dependencies(**dependency_overrides)
        ).poll_once()


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path / "state")
