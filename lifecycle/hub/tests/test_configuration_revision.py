from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_configuration_entities import (
    EntityConfigurationInput,
    InstallationConfigurationInput,
)
from fdai_deployment_cli.lifecycle_configuration_package import (
    build_installation_configuration_package,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import encryption_key_digest
from fdai_deployment_cli.lifecycle_plan import canonical_plan_payload
from fdai_deployment_cli.runtime_release import RecallRecord

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.domain import (
    DailyWindow,
    Installation,
    Issued,
    NoEligibleRelease,
    NoManagedEntity,
    Waiting,
)
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.store import Change, ReleaseStore

FIRST = "1" * 64
SECOND = "2" * 64
ENTITIES = frozenset({FIRST, SECOND})


@dataclass
class PlanCase:
    installation: Installation
    catalog: ReleaseCatalog
    source: InstallationConfigurationInput
    candidate: ConfigurationRevisionCandidate
    signing: Ed25519PrivateKey
    recipient: X25519PrivateKey

    def build_candidate(
        self, source: InstallationConfigurationInput
    ) -> ConfigurationRevisionCandidate:
        return replace(
            self.candidate,
            package=build_installation_configuration_package(
                source,
                entity_ids=frozenset(entity.entity_id for entity in source.entities),
                signing_key=self.signing,
                installation_key=self.recipient.public_key(),
            ),
        )


@pytest.fixture
def plan_case(
    installation: Installation,
    catalog: ReleaseCatalog,
    key: HubSigningKey,
    now: datetime,
    tmp_path: Path,
) -> PlanCase:
    core = next(entity for entity in installation.entities if entity.managed)
    ids = {"core": FIRST, "console": SECOND}
    target = replace(
        installation,
        settings=replace(installation.settings, channel="DEV"),
        entities=frozenset(
            replace(
                entity,
                entity_id=ids[entity.entity_id],
                ownership=core.ownership,
                settings=core.settings,
            )
            for entity in installation.entities
        ),
        reported=replace(
            installation.reported,
            entities={ids[name]: state for name, state in installation.reported.entities.items()},
        ),
    )
    schema = {
        **target.configuration.schema,
        "credential_ref": {"x-fdai-axis": "deployment-environment", "x-fdai-owner": "customer"},
    }
    manifest = catalog.releases["1.6.0"].to_mapping()
    manifest["configuration_schema"] = {
        "format": "fdai.release-configuration-schema.v1",
        "release_version": "1.6.0",
        "schema_sha256": canonical_digest(schema),
        "keys": schema,
    }
    vendor = ReleaseStore(tmp_path / "release.db", key, clock=lambda: now)
    for action in ("register", "publish"):
        vendor.change(
            action,
            "1.6.0",
            Change(
                revision=vendor.snapshot()["revision"],
                confirmation="1.6.0",
                reason="Synthetic full revision check",
                manifest=canonical_bytes(manifest).decode() if action == "register" else None,
            ),
        )
    export, independent_pin = vendor.export()
    admitted = load_pinned_export(
        export, expected_sha256=independent_pin, public_key=key.public_key, now=now
    )
    signing = Ed25519PrivateKey.generate()
    recipient = X25519PrivateKey.generate()
    source = InstallationConfigurationInput(
        revision_id="a" * 40,
        release_version="1.6.0",
        release_digest=admitted.releases["1.6.0"].digest,
        configuration_schema=schema,
        environment_config={},
        sealed_values={},
        sealed_keys=frozenset({"endpoint"}),
        entities=tuple(
            EntityConfigurationInput(
                entity_id=entity_id,
                entity_overrides=(
                    {
                        "versions": ">=1.0.0 <2.0.0",
                        "values": {"replicas": replicas, "credential_ref": reference},
                    },
                ),
                sealed_values={"endpoint": "https://example.com/private-identifier"},
            )
            for entity_id, replicas, reference in (
                (FIRST, 2, "first-secret"),
                (SECOND, 4, "second-secret"),
            )
        ),
    )
    package = build_installation_configuration_package(
        source, entity_ids=ENTITIES, signing_key=signing, installation_key=recipient.public_key()
    )
    candidate = ConfigurationRevisionCandidate(
        package=package,
        configuration_key=signing.public_key(),
        installation_key_digest=encryption_key_digest(recipient.public_key()),
        sealed_keys=source.sealed_keys,
        expected_predecessor=None,
    )
    return PlanCase(target, admitted, source, candidate, signing, recipient)


def test_real_release_publication_packaging_and_planning(
    plan_case: PlanCase, key: HubSigningKey, now: datetime
) -> None:
    case = plan_case
    outcome = plan_next(
        case.installation,
        now,
        catalog=case.catalog,
        key=key,
        configuration_revision=case.candidate,
    )
    assert isinstance(outcome, Issued)
    assert outcome.plan.entity_ids == outcome.plan.envelope.entity_ids == ENTITIES
    assert outcome.plan.configuration_revision_digest == case.candidate.package.digest
    assert outcome.plan.target_release_digest == case.source.release_digest
    assert outcome.plan.signed_payload == canonical_plan_payload(outcome.plan)
    key.public_key.verify(outcome.plan.signature, outcome.plan.signed_payload)
    resolution = case.candidate.resolve("1.6.0", case.catalog.releases["1.6.0"], ENTITIES)
    assert resolution.entities[FIRST].values["replicas"] == 2
    assert resolution.entities[SECOND].values["replicas"] == 4
    assert resolution.entities[SECOND].values["credential_ref"] == "second-secret"


@pytest.mark.parametrize(
    "problem",
    [
        "signature",
        "key",
        "recipient",
        "classification",
        "head",
        "schema",
        "release-digest",
        "version",
        "missing-entity",
        "extra-entity",
        "legacy-release",
    ],
)
def test_planner_refuses_the_whole_invalid_candidate(
    plan_case: PlanCase, key: HubSigningKey, now: datetime, problem: str
) -> None:
    case = plan_case
    candidate = case.candidate
    catalog = case.catalog
    if problem == "signature":
        candidate = replace(candidate, package=replace(candidate.package, signature=b"\0" * 64))
    elif problem == "key":
        candidate = replace(candidate, configuration_key=Ed25519PrivateKey.generate().public_key())
    elif problem == "recipient":
        candidate = replace(candidate, installation_key_digest="e" * 64)
    elif problem == "classification":
        candidate = replace(candidate, sealed_keys=frozenset())
    elif problem == "head":
        candidate = replace(candidate, expected_predecessor="e" * 64)
    elif problem == "legacy-release":
        release = replace(catalog.releases["1.6.0"], configuration_schema=None)
        catalog = replace(catalog, releases={"1.6.0": release})
    else:
        source = case.source
        if problem == "schema":
            source = replace(
                source,
                configuration_schema={
                    **source.configuration_schema,
                    "region": {
                        "default": "eastus",
                        "x-fdai-axis": "deployment-environment",
                        "x-fdai-owner": "customer",
                    },
                },
            )
        elif problem == "release-digest":
            source = replace(source, release_digest="e" * 64)
        elif problem == "version":
            source = replace(source, release_version="1.5.0")
        elif problem == "missing-entity":
            source = replace(source, entities=source.entities[:1])
        else:
            source = replace(
                source, entities=(*source.entities, replace(source.entities[0], entity_id="3" * 64))
            )
        candidate = case.build_candidate(source)
    outcome = plan_next(
        case.installation, now, catalog=catalog, key=key, configuration_revision=candidate
    )
    assert isinstance(outcome, NoEligibleRelease)
    assert {block.reason_code for check in outcome.checks for block in check.blocks} == {
        "configuration_revision_invalid"
    }


def test_configuration_cannot_manage_entities_or_bypass_timing_or_recall(
    plan_case: PlanCase, key: HubSigningKey, now: datetime
) -> None:
    case = plan_case
    unmanaged = replace(
        case.installation,
        entities=frozenset(replace(entity, settings=None) for entity in case.installation.entities),
    )
    assert isinstance(
        plan_next(
            unmanaged, now, catalog=case.catalog, key=key, configuration_revision=case.candidate
        ),
        NoManagedEntity,
    )
    closed = replace(
        case.installation,
        settings=replace(
            case.installation.settings,
            windows=(DailyWindow(time(2), timedelta(hours=1), "Asia/Seoul"),),
        ),
    )
    assert isinstance(
        plan_next(
            closed, now, catalog=case.catalog, key=key, configuration_revision=case.candidate
        ),
        Waiting,
    )
    catalog = replace(
        case.catalog,
        recalls=(
            RecallRecord(scope="release", target="1.6.0", sequence=1, notice_digest="c" * 64),
        ),
    )
    outcome = plan_next(
        case.installation, now, catalog=catalog, key=key, configuration_revision=case.candidate
    )
    assert isinstance(outcome, NoEligibleRelease)
    assert "release_recalled" in {block.reason_code for block in outcome.checks[0].blocks}
