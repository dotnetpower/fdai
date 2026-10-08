"""#1950: enrollment, approval, and the unmanaged-to-managed transition."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from fdai_lifecycle_hub import models
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.domain import Installation, Issued, NoManagedEntity, Planner
from fdai_lifecycle_hub.enrollment import EnrollmentRequest, EnrollmentStatus
from fdai_lifecycle_hub.entity import EntitySettings, OwnershipEvidence
from fdai_lifecycle_hub.errors import (
    EnrollmentProofError,
    EntityManagedError,
    EntityNotReportedError,
    EntitySettingsRejectedError,
    InstallationKeyMismatchError,
    NotEnrolledError,
    NotPendingError,
    OwnershipUnprovenError,
    UnknownEntityError,
    UnknownInstallationError,
)
from fdai_lifecycle_hub.schemas import sign_enrollment
from fdai_lifecycle_hub.signing import verify_key_proof
from fdai_lifecycle_hub.store import HubStore

type Sign = Callable[[Installation, datetime], EnrollmentRequest]

INSTALLATION_ID = "installation-alpha"
PLAN_URL = f"/v1/installations/{INSTALLATION_ID}/plan"
TAG_ONLY = OwnershipEvidence(managed_tag=True)


@pytest.fixture
def pending(hub_store: HubStore, enrollment: EnrollmentRequest, now: datetime) -> HubStore:
    hub_store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    return hub_store


@pytest.fixture
def key_id(enrollment: EnrollmentRequest) -> str:
    return enrollment.installation_key_id


@pytest.fixture
def enrolled(pending: HubStore, key_id: str, now: datetime) -> HubStore:
    pending.approve(INSTALLATION_ID, approver="alice", installation_key_id=key_id, now=now)
    return pending


def _core(installation: Installation) -> tuple[OwnershipEvidence, EntitySettings]:
    core = next(entity for entity in installation.entities if entity.entity_id == "core")
    assert core.ownership is not None and core.settings is not None
    return core.ownership, core.settings


def _audit(store: HubStore) -> list[tuple[str, str, dict[str, Any]]]:
    with Session(store.engine) as session:
        records = session.scalars(select(models.AuditRecord).order_by(models.AuditRecord.sequence))
        return [(record.action, record.subject, record.payload) for record in records]


# Scenario: pending registration


def test_valid_request_is_recorded_as_pending_and_gets_no_plan(
    pending: HubStore, key_id: str, planner: Planner, now: datetime
) -> None:
    client = TestClient(create_app(pending, clock=lambda: now))

    assert pending.enrollment_status(INSTALLATION_ID) is EnrollmentStatus.PENDING
    assert client.get(PLAN_URL).status_code == 204
    with pytest.raises(NotEnrolledError):
        pending.recompute(INSTALLATION_ID, planner, now=now)
    assert _audit(pending) == [
        ("enrollment.requested", INSTALLATION_ID, {"installation_key_id": key_id})
    ]


@pytest.mark.parametrize("decided", [False, True])
def test_unenrolled_installation_accepts_no_changes(
    pending: HubStore, installation: Installation, now: datetime, decided: bool
) -> None:
    if decided:
        pending.reject(INSTALLATION_ID, approver="alice", reason="unknown_key", now=now)
    ownership, settings = _core(installation)
    window = SuppressionWindow("installation", now, now + timedelta(hours=1))
    changes: list[Callable[[], object]] = [
        lambda: pending.record_ownership(INSTALLATION_ID, "core", ownership, now=now),
        lambda: pending.manage(INSTALLATION_ID, "core", settings, operator="bob", now=now),
        lambda: pending.record_state(
            INSTALLATION_ID, replace(installation.reported, observed_at=now), now=now
        ),
        lambda: pending.add_suppression(INSTALLATION_ID, window, now=now),
        lambda: pending.lift_suppressions(INSTALLATION_ID, "installation", now=now),
    ]

    for change in changes:
        with pytest.raises(NotEnrolledError):
            change()


CORRUPTIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "unknown timezone": lambda t: t["settings"]["windows"][0].update(timezone="No/Zone"),
    "schema revision overflow": lambda t: t["reported"].update(schema_revision=2**40),
    "release id too long": lambda t: t["reported"]["entities"]["core"].update(
        release_id="1.4.0-" + "a" * 64
    ),
}


@pytest.mark.parametrize("corrupt", CORRUPTIONS.values(), ids=CORRUPTIONS)
def test_out_of_range_enrollment_is_invalid(
    enrollment_template: dict[str, Any],
    installation_key: Ed25519PrivateKey,
    now: datetime,
    corrupt: Callable[[dict[str, Any]], None],
) -> None:
    """The API answers 422 for any ValueError, so none of these reaches the database."""

    template = deepcopy(enrollment_template)
    corrupt(template)

    with pytest.raises(ValueError):
        sign_enrollment(template, installation_key, now)


def test_declared_entities_must_match_the_reported_entities(
    sign: Sign, installation: Installation, now: datetime
) -> None:
    core_only = {"core": installation.reported.entities["core"]}
    lacking = replace(installation, reported=replace(installation.reported, entities=core_only))

    with pytest.raises(ValueError, match="exactly the reported entities"):
        sign(lacking, now)


# Scenario: approval


def test_approval_enrolls_with_every_entity_unmanaged_and_audits_the_approver(
    enrolled: HubStore, key_id: str, planner: Planner, now: datetime
) -> None:
    loaded = enrolled.load(INSTALLATION_ID)

    assert enrolled.enrollment_status(INSTALLATION_ID) is EnrollmentStatus.ENROLLED
    assert {entity.entity_id for entity in loaded.entities} == {"core", "console"}
    assert not any(entity.managed or entity.ownership for entity in loaded.entities)
    assert _audit(enrolled)[-1] == (
        "enrollment.approved",
        INSTALLATION_ID,
        {
            "approver": "alice",
            "installation_key_id": key_id,
            "unmanaged_entities": ["console", "core"],
        },
    )
    assert enrolled.recompute(INSTALLATION_ID, planner, now=now) == NoManagedEntity()


def test_approval_must_name_the_requesting_key(pending: HubStore, now: datetime) -> None:
    with pytest.raises(InstallationKeyMismatchError):
        pending.approve(
            INSTALLATION_ID, approver="alice", installation_key_id="installation-other", now=now
        )
    assert pending.enrollment_status(INSTALLATION_ID) is EnrollmentStatus.PENDING


def test_only_a_pending_enrollment_is_decided(
    enrolled: HubStore, key_id: str, now: datetime
) -> None:
    with pytest.raises(NotPendingError):
        enrolled.approve(INSTALLATION_ID, approver="alice", installation_key_id=key_id, now=now)
    with pytest.raises(NotPendingError):
        enrolled.reject(INSTALLATION_ID, approver="alice", reason="unknown_key", now=now)


def test_rejected_installation_gets_no_plan(
    pending: HubStore, key_id: str, planner: Planner, now: datetime
) -> None:
    pending.reject(INSTALLATION_ID, approver="alice", reason="unknown_key", now=now)

    assert pending.enrollment_status(INSTALLATION_ID) is EnrollmentStatus.REJECTED
    assert pending.current_plan(INSTALLATION_ID, now=now) is None
    with pytest.raises(NotEnrolledError):
        pending.recompute(INSTALLATION_ID, planner, now=now)
    with pytest.raises(NotPendingError):
        pending.approve(INSTALLATION_ID, approver="alice", installation_key_id=key_id, now=now)
    assert _audit(pending)[-1] == (
        "enrollment.rejected",
        INSTALLATION_ID,
        {"approver": "alice", "reason": "unknown_key"},
    )


@pytest.mark.parametrize(("approver", "reason"), [("", "unknown_key"), ("alice", "Not A Code")])
def test_decisions_reject_invalid_actor_or_reason(
    pending: HubStore, now: datetime, approver: str, reason: str
) -> None:
    with pytest.raises(ValueError, match="should match pattern"):
        pending.reject(INSTALLATION_ID, approver=approver, reason=reason, now=now)
    assert pending.enrollment_status(INSTALLATION_ID) is EnrollmentStatus.PENDING


# Scenario: becoming managed


def test_proven_entity_with_settings_becomes_managed_and_alone_is_planned(
    enrolled: HubStore, installation: Installation, planner: Planner, now: datetime
) -> None:
    ownership, settings = _core(installation)

    enrolled.record_ownership(INSTALLATION_ID, "core", ownership, now=now)
    covering = enrolled.manage(INSTALLATION_ID, "core", settings, operator="bob", now=now)
    outcome = enrolled.recompute(INSTALLATION_ID, planner, now=now)

    assert covering == ">=1.0.0 <2.0.0"
    assert enrolled.load(INSTALLATION_ID).managed_entity_ids == {"core"}
    assert isinstance(outcome, Issued)
    assert outcome.plan.entity_ids == {"core"}
    assert _audit(enrolled)[-2] == (
        "entity.managed",
        "core",
        {"operator": "bob", "settings_digest": settings.digest, "covering_range": covering},
    )


def test_settings_without_ownership_evidence_are_refused(
    enrolled: HubStore, installation: Installation, now: datetime
) -> None:
    _, settings = _core(installation)

    with pytest.raises(OwnershipUnprovenError, match="ownership_unproven"):
        enrolled.manage(INSTALLATION_ID, "core", settings, operator="bob", now=now)


def test_settings_must_cover_the_running_release(
    enrolled: HubStore, installation: Installation, now: datetime
) -> None:
    ownership, _ = _core(installation)
    enrolled.record_ownership(INSTALLATION_ID, "core", ownership, now=now)
    later_only = EntitySettings(overrides=({"versions": ">=2.0.0", "values": {"replicas": 2}},))

    with pytest.raises(EntitySettingsRejectedError, match="missing_matching_override_block"):
        enrolled.manage(INSTALLATION_ID, "core", later_only, operator="bob", now=now)
    assert enrolled.load(INSTALLATION_ID).managed_entity_ids == frozenset()


def test_managed_entity_keeps_its_ownership_evidence(
    enrolled: HubStore, installation: Installation, now: datetime
) -> None:
    ownership, settings = _core(installation)
    enrolled.record_ownership(INSTALLATION_ID, "core", ownership, now=now)
    enrolled.manage(INSTALLATION_ID, "core", settings, operator="bob", now=now)

    with pytest.raises(EntityManagedError):
        enrolled.record_ownership(INSTALLATION_ID, "core", TAG_ONLY, now=now)


def test_managing_again_replaces_the_settings(
    enrolled: HubStore, installation: Installation, now: datetime
) -> None:
    ownership, settings = _core(installation)
    enrolled.record_ownership(INSTALLATION_ID, "core", ownership, now=now)
    enrolled.manage(INSTALLATION_ID, "core", settings, operator="bob", now=now)
    revised = EntitySettings(overrides=({"versions": ">=1.4.0 <2.0.0", "values": {"replicas": 3}},))

    covering = enrolled.manage(INSTALLATION_ID, "core", revised, operator="bob", now=now)

    core = next(e for e in enrolled.load(INSTALLATION_ID).entities if e.entity_id == "core")
    assert (core.settings, covering) == (revised, ">=1.4.0 <2.0.0")
    assert _audit(enrolled)[-1][2]["settings_digest"] == revised.digest


def test_entity_missing_from_the_reported_state_is_not_managed(
    enrolled: HubStore, installation: Installation, now: datetime
) -> None:
    ownership, settings = _core(installation)
    core_only = {"core": installation.reported.entities["core"]}
    later = replace(installation.reported, entities=core_only, observed_at=now)
    enrolled.record_state(INSTALLATION_ID, later, now=now)
    enrolled.record_ownership(INSTALLATION_ID, "console", ownership, now=now)

    with pytest.raises(EntityNotReportedError):
        enrolled.manage(INSTALLATION_ID, "console", settings, operator="bob", now=now)


def test_unknown_entity_is_rejected(
    enrolled: HubStore, installation: Installation, now: datetime
) -> None:
    ownership, _ = _core(installation)

    with pytest.raises(UnknownEntityError):
        enrolled.record_ownership(INSTALLATION_ID, "missing", ownership, now=now)


# Scenario: invalid proof or tag-only ownership


def test_invalid_proof_is_rejected_with_its_reason_and_creates_nothing(
    hub_store: HubStore, enrollment: EnrollmentRequest, now: datetime
) -> None:
    request = enrollment
    forged = replace(request, proof=Ed25519PrivateKey.generate().sign(request.signed_payload))

    with pytest.raises(EnrollmentProofError, match="enrollment_proof_invalid"):
        hub_store.request_enrollment(forged, verify=verify_key_proof, now=now)
    with pytest.raises(UnknownInstallationError):
        hub_store.enrollment_status(INSTALLATION_ID)
    assert _audit(hub_store) == [
        (
            "enrollment.proof_failed",
            INSTALLATION_ID,
            {
                "installation_key_id": request.installation_key_id,
                "reason": "enrollment_proof_invalid",
            },
        )
    ]


def test_proof_is_checked_by_the_injected_verifier(
    store: HubStore, enrollment: EnrollmentRequest, now: datetime
) -> None:
    calls: list[bytes] = []

    def refuse(*, public_key: bytes, payload: bytes, signature: bytes) -> bool:
        calls.append(payload)
        return False

    with pytest.raises(EnrollmentProofError, match="enrollment_proof_invalid"):
        store.request_enrollment(enrollment, verify=refuse, now=now)
    assert calls == [enrollment.signed_payload]


@pytest.mark.parametrize("age", [timedelta(minutes=6), -timedelta(minutes=6)])
def test_proof_outside_the_freshness_window_is_stale(
    hub_store: HubStore, sign: Sign, installation: Installation, now: datetime, age: timedelta
) -> None:
    request = sign(installation, now - age)

    with pytest.raises(EnrollmentProofError, match="enrollment_proof_stale"):
        hub_store.request_enrollment(request, verify=verify_key_proof, now=now)
    with pytest.raises(UnknownInstallationError):
        hub_store.enrollment_status(INSTALLATION_ID)
    assert _audit(hub_store)[-1][2]["reason"] == "enrollment_proof_stale"


def test_tag_only_ownership_keeps_the_entity_unmanaged_and_records_why(
    enrolled: HubStore, installation: Installation, now: datetime
) -> None:
    _, settings = _core(installation)

    enrolled.record_ownership(INSTALLATION_ID, "core", TAG_ONLY, now=now)

    assert _audit(enrolled)[-1] == (
        "entity.ownership_recorded",
        "core",
        {"reason": "ownership_tag_only"},
    )
    with pytest.raises(OwnershipUnprovenError, match="ownership_tag_only"):
        enrolled.manage(INSTALLATION_ID, "core", settings, operator="bob", now=now)
    assert enrolled.load(INSTALLATION_ID).managed_entity_ids == frozenset()
