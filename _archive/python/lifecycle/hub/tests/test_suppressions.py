from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_configuration_entities import (
    EntityConfigurationInput,
    InstallationConfigurationInput,
    InstallationLayerResolution,
)
from fdai_deployment_cli.lifecycle_configuration_package import (
    build_installation_configuration_package,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import encryption_key_digest
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow, required_artifact_digests
from fdai_deployment_cli.lifecycle_release import LifecycleRelease
from fdai_deployment_cli.runtime_release import ConfigurationSchema
from starlette.testclient import TestClient

from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.domain import EntityState, Health, Installation, Issued, Planner, Waiting
from fdai_lifecycle_hub.entity import Entity, EntitySettings, OwnershipEvidence, OwnershipGap
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore


def _window(now: datetime, scope: str = "installation", hours: int = 1) -> SuppressionWindow:
    return SuppressionWindow(scope, now, now + timedelta(hours=hours))


@pytest.mark.parametrize("scope", ["installation", "entity:core", "entity:console", "plan:upgrade"])
def test_known_scopes_are_accepted(installation: Installation, now: datetime, scope: str) -> None:
    assert installation.suppressed(_window(now, scope), now).suppressions == (_window(now, scope),)


@pytest.mark.parametrize(
    "scope",
    ["installation:", "installation:x", "entity:missing", "entity:", "plan:deploy", "region"],
)
def test_unknown_scopes_are_rejected(installation: Installation, now: datetime, scope: str) -> None:
    with pytest.raises(ValueError, match="unknown suppression scope"):
        installation.suppressed(_window(now, scope), now)


def test_a_suppression_must_end_in_the_future(installation: Installation, now: datetime) -> None:
    past = SuppressionWindow("installation", now - timedelta(hours=2), now - timedelta(hours=1))

    with pytest.raises(ValueError, match="end in the future"):
        installation.suppressed(past, now)


def test_adding_drops_expired_windows(installation: Installation, now: datetime) -> None:
    expired = SuppressionWindow("installation", now - timedelta(hours=2), now - timedelta(hours=1))
    stale = replace(installation, suppressions=(expired,))

    assert stale.suppressed(_window(now), now).suppressions == (_window(now),)


def test_lifting_removes_only_that_scope(installation: Installation, now: datetime) -> None:
    both = installation.suppressed(_window(now), now).suppressed(_window(now, "entity:core"), now)

    assert both.lifted("installation", now).suppressions == (_window(now, "entity:core"),)
    with pytest.raises(ValueError, match="no active suppression"):
        installation.lifted("installation", now)


def test_suppression_withdraws_the_plan_until_lifted(
    enrolled_store: HubStore, installation: Installation, planner: Planner, now: datetime
) -> None:
    first = enrolled_store.recompute(installation.installation_id, planner, now=now)
    client = TestClient(create_app(enrolled_store, clock=lambda: now))
    plan_url = f"/v1/installations/{installation.installation_id}/plan"

    enrolled_store.add_suppression(installation.installation_id, _window(now), now=now)
    withdrawn = client.get(plan_url).status_code
    held = enrolled_store.recompute(installation.installation_id, planner, now=now)
    enrolled_store.lift_suppressions(installation.installation_id, "installation", now=now)
    reissued = enrolled_store.recompute(installation.installation_id, planner, now=now)

    assert isinstance(first, Issued)
    assert withdrawn == 204
    assert isinstance(held, Waiting)
    assert held.checks[0].blocks[0].reason_code == "suppression_window_active"
    assert isinstance(reissued, Issued)
    assert reissued.plan.sequence == 2
    assert enrolled_store.load(installation.installation_id).suppressions == ()
    assert enrolled_store.audit_chain_intact()


def test_future_suppression_holds_the_plan_from_its_start_without_a_recompute(
    enrolled_store: HubStore, installation: Installation, planner: Planner, now: datetime
) -> None:
    enrolled_store.recompute(installation.installation_id, planner, now=now)
    starts_at = now + timedelta(minutes=5)
    later = SuppressionWindow("installation", starts_at, starts_at + timedelta(hours=1))

    enrolled_store.add_suppression(installation.installation_id, later, now=now)

    served = partial(enrolled_store.current_plan, installation.installation_id)
    assert served(now=starts_at - timedelta(seconds=1)) is not None
    assert served(now=starts_at) is None


@pytest.mark.parametrize(
    ("scope", "held"),
    [
        ("installation", True),
        ("plan:upgrade", True),
        ("entity:core", True),
        ("plan:rollback", False),
        ("entity:console", False),
    ],
)
def test_only_a_matching_suppression_holds_the_plan(
    enrolled_store: HubStore,
    installation: Installation,
    planner: Planner,
    now: datetime,
    scope: str,
    held: bool,
) -> None:
    first = enrolled_store.recompute(installation.installation_id, planner, now=now)
    client = TestClient(create_app(enrolled_store, clock=lambda: now))

    enrolled_store.add_suppression(installation.installation_id, _window(now, scope), now=now)

    assert isinstance(first, Issued)
    status = client.get(f"/v1/installations/{installation.installation_id}/plan").status_code
    assert status == (204 if held else 200)
    served = enrolled_store.current_plan(installation.installation_id, now=now)
    assert (served is None) is held
    if not held:
        assert served is not None and served.plan_id == first.plan.plan_id


def test_ownership_evidence_and_entity_settings_enforce_proven_ownership_invariants() -> None:
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64

    with pytest.raises(ValueError, match="ownership evidence is empty"):
        OwnershipEvidence()

    with pytest.raises(ValueError, match="sha256: followed by 64 hex characters"):
        OwnershipEvidence(foundation_receipt_digest="invalid-digest")

    with pytest.raises(
        ValueError, match="native creation evidence cannot impersonate Foundation evidence"
    ):
        OwnershipEvidence(
            foundation_receipt_digest=digest_a,
            native_creation_receipt_digest=digest_b,
        )

    assert OwnershipEvidence(foundation_receipt_digest=digest_a).gap is OwnershipGap.UNPROVEN
    assert OwnershipEvidence(terraform_state_digest=digest_b).gap is OwnershipGap.UNPROVEN
    tag_only = OwnershipEvidence(managed_tag=True)
    assert tag_only.gap is OwnershipGap.TAG_ONLY

    settings = EntitySettings(
        overrides=({"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}},)
    )
    assert settings.digest.startswith("sha256:") or len(settings.digest) == 64

    unowned = Entity(entity_id="console", kind="static-site")
    assert unowned.ownership_gap is OwnershipGap.UNPROVEN
    assert unowned.managed is False

    with pytest.raises(ValueError, match="has settings without proven ownership"):
        Entity(entity_id="core", kind="service", ownership=tag_only, settings=settings)

    with pytest.raises(ValueError, match="has settings without proven ownership"):
        Entity(entity_id="core", kind="service", ownership=None, settings=settings)


def test_planning_detects_healthy_artifact_drift_and_handles_uninstalled_managed_entity(
    installation: Installation,
    catalog: ReleaseCatalog,
    key: HubSigningKey,
    now: datetime,
) -> None:
    running_latest = replace(
        installation,
        reported=replace(
            installation.reported,
            entities={
                **installation.reported.entities,
                "core": EntityState(
                    release_id="1.6.0",
                    artifact_digests=frozenset({"sha256:" + "d" * 64}),
                    health=Health.HEALTHY,
                ),
            },
        ),
    )
    drift_outcome = plan_next(running_latest, now, catalog=catalog, key=key)
    assert isinstance(drift_outcome, Issued)
    assert drift_outcome.plan.plan_type == "drift-reconciliation"
    assert drift_outcome.plan.target_release_id == "1.6.0"

    uninstalled = replace(
        installation,
        reported=replace(
            installation.reported,
            available_artifact_digests=required_artifact_digests(catalog.releases["1.6.0"]),
            entities={
                **installation.reported.entities,
                "core": EntityState(
                    release_id=None,
                    artifact_digests=frozenset(),
                    health=Health.UNKNOWN,
                ),
            },
        ),
    )
    fresh_outcome = plan_next(uninstalled, now, catalog=catalog, key=key)
    assert isinstance(fresh_outcome, Issued)
    assert fresh_outcome.plan.plan_type == "upgrade"
    assert fresh_outcome.plan.target_release_id == "1.6.0"


def test_transient_configuration_revision_resolves_skips_invalid_and_requires_catalog_schema(
    installation: Installation, catalog: ReleaseCatalog, key: HubSigningKey, now: datetime
) -> None:
    schema_map = installation.configuration.schema
    schema_150 = ConfigurationSchema(
        release_version="1.5.0",
        digest=canonical_digest(schema_map),
        _keys=canonical_bytes(schema_map),
    )
    release_150 = replace(catalog.releases["1.5.0"], configuration_schema=schema_150)
    schema_catalog = replace(catalog, releases={**catalog.releases, "1.5.0": release_150})
    signing = Ed25519PrivateKey.generate()
    recipient = X25519PrivateKey.generate()
    entity_hash = "1" * 64
    source = InstallationConfigurationInput(
        revision_id="a" * 40,
        release_version="1.5.0",
        release_digest=release_150.digest,
        configuration_schema=schema_map,
        environment_config={},
        sealed_values={},
        sealed_keys=frozenset({"endpoint"}),
        entities=(
            EntityConfigurationInput(
                entity_id=entity_hash,
                entity_overrides=({"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}},),
                sealed_values={"endpoint": "https://example.com/private"},
            ),
        ),
    )
    package = build_installation_configuration_package(
        source,
        entity_ids=frozenset({entity_hash}),
        signing_key=signing,
        installation_key=recipient.public_key(),
    )
    candidate = ConfigurationRevisionCandidate(
        package=package,
        installation_id=installation.installation_id,
        entity_bindings=(("core", entity_hash),),
        configuration_key=signing.public_key(),
        installation_key_digest=encryption_key_digest(recipient.public_key()),
        sealed_keys=source.sealed_keys,
        expected_predecessor=None,
    )

    outcome = plan_next(
        installation, now, catalog=schema_catalog, key=key, configuration_revision=candidate
    )
    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_id == "1.5.0"
    assert outcome.plan.configuration_revision_digest == package.digest
    assert outcome.checks[0].blocks[0].reason_code == "configuration_revision_invalid"

    resolved = candidate.resolve(
        "1.5.0", release_150, installation.managed_entity_ids, installation_id="installation-alpha"
    )

    class _SchemaLessCandidate(ConfigurationRevisionCandidate):
        def resolve(
            self,
            release_id: str,
            release: LifecycleRelease,
            entity_ids: frozenset[str],
            *,
            installation_id: str,
        ) -> InstallationLayerResolution:
            return resolved

    with pytest.raises(ValueError, match="verified configuration requires a catalog schema"):
        plan_next(
            installation,
            now,
            catalog=catalog,
            key=key,
            configuration_revision=_SchemaLessCandidate(
                package=package,
                installation_id=installation.installation_id,
                entity_bindings=(("core", entity_hash),),
                configuration_key=signing.public_key(),
                installation_key_digest=encryption_key_digest(recipient.public_key()),
                sealed_keys=source.sealed_keys,
                expected_predecessor=None,
            ),
        )
