"""Routine verifier rotation keeps retained admissions; replayed attempts keep their outcome."""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from fdai.core.operational_evidence.registry_json import RevisionClass, content_pin
from fdai.core.operational_evidence.revision_history import RegistryHistory, RegistryRevision
from fdai.core.operational_evidence.trust_registry import purpose_defects
from fdai.core.operational_evidence.trust_registry_loader import load_trust_registry
from fdai.delivery.operational_evidence_admission import OperationalEvidenceAdmissionProvider
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceStatus,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
)
from tests.core.operational_evidence.harness import VerifierVenue
from tests.core.operational_evidence.support import (
    NOW,
    POLICY,
    SCOPE,
    anchors,
    encode,
    history,
    trust_bytes,
)

_COMMAND = "operator-test-context-command"


def _revision(document: dict[str, Any]) -> RegistryRevision:
    data = encode(document)
    base = history()
    return RegistryRevision(
        trust=load_trust_registry(data, expected_pin=content_pin(data)),
        grants=base.current.grants,
    )


def _rotated(
    *, revoke_old: bool = False, revision: int = 2, anchor: str | None = None
) -> dict[str, Any]:
    document = json.loads(trust_bytes())
    document["revision"] = revision
    for entry in document["purposes"]:
        old = entry["verifiers"][0]
        rotated = {**old, "verifier_version": "1.1.0", "valid_from": NOW.isoformat()}
        if anchor is not None:
            rotated["trust_anchor_id"] = anchor
        if revoke_old:
            entry["verifiers"][0] = {**old, "revoked": True}
        entry["verifiers"].append(rotated)
    return document


def _lookup(command: dict[str, Any]) -> dict[str, str]:
    return {
        "evidence_digest": content_digest(command),
        "scope_digest": "sha256:" + SCOPE,
        "purpose_id": _COMMAND,
        "source_revision": POLICY,
    }


async def _issue_command(venue: VerifierVenue, **overrides: Any) -> tuple[Any, dict[str, Any]]:
    command = venue.propose(**overrides)
    response, _rejection = await venue.issue(
        _COMMAND, content_digest(command), idempotency_key=command["idempotency_key"]
    )
    return response, command


async def test_routine_rotation_keeps_earlier_admissions_and_the_old_workload() -> None:
    first = history().current
    rotation = RegistryHistory((first, _revision(_rotated())))
    assert rotation.step_classes() == (RevisionClass.ROUTINE_ROTATION,)
    venue = VerifierVenue(registry=RegistryHistory((first,)), consumer_registry=rotation)
    issued, command = await _issue_command(venue)
    assert issued.status is OperationalEvidenceIssuanceStatus.ISSUED
    assert await venue.provider.admit(**_lookup(command)) is not None
    venue.history = rotation
    later, later_command = await _issue_command(venue, key="context-after-rotation")
    assert later.status is OperationalEvidenceIssuanceStatus.ISSUED
    bundle = venue.proofs.admissions[-1][0].bundle
    assert bundle.verifier_version == "1.0.0"
    assert await venue.provider.admit(**_lookup(later_command)) is not None
    new = VerifierVenue(registry=rotation, verifier_version="1.1.0")
    rotated, _command = await _issue_command(new)
    assert rotated.status is OperationalEvidenceIssuanceStatus.ISSUED
    assert new.proofs.admissions[-1][0].bundle.verifier_version == "1.1.0"


async def test_revocation_revision_retires_admissions_of_the_revoked_binding() -> None:
    first = history().current
    revoked = RegistryHistory((first, _revision(_rotated(revoke_old=True))))
    assert revoked.step_classes() == (RevisionClass.REVOCATION,)
    venue = VerifierVenue(registry=RegistryHistory((first,)), consumer_registry=revoked)
    issued, command = await _issue_command(venue)
    assert issued.status is OperationalEvidenceIssuanceStatus.ISSUED
    assert await venue.provider.admit(**_lookup(command)) is None
    venue.history = revoked
    blocked, _command = await _issue_command(venue, key="context-after-revocation")
    assert blocked.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE


_NEXT_ANCHOR = "anchor:operational-evidence-verifier-next"
_NEXT_PRINCIPAL = "fdai_operational_evidence_verifier_next"


def test_self_verification_is_judged_against_the_workload_binding() -> None:
    rotation = RegistryHistory((history().current, _revision(_rotated(anchor=_NEXT_ANCHOR))))
    assert rotation.step_classes() == (RevisionClass.ROUTINE_ROTATION,)
    rebound = anchors(
        overrides={
            "anchor:operational-evidence-verifier": "fdai_operator",
            _NEXT_ANCHOR: _NEXT_PRINCIPAL,
        }
    )

    def defects(version: str | None) -> tuple[str, ...]:
        return purpose_defects(
            rotation.current.trust,
            rebound,
            purpose_id=_COMMAND,
            verifier_id="operational-evidence-verifier",
            at=NOW,
            verifier_version=version,
        )

    assert defects("1.0.0") == ("self_verified",)
    assert defects("1.1.0") == ()
    assert defects(None) == ()


async def test_retained_admission_is_rechecked_against_its_own_binding_readiness() -> None:
    rotation = RegistryHistory((history().current, _revision(_rotated(anchor=_NEXT_ANCHOR))))
    venue = VerifierVenue(
        registry=rotation,
        bound=anchors(overrides={_NEXT_ANCHOR: _NEXT_PRINCIPAL}),
        consumer_anchors=anchors(
            overrides={
                "anchor:operational-evidence-verifier": "fdai_operator",
                _NEXT_ANCHOR: _NEXT_PRINCIPAL,
            }
        ),
    )
    issued, command = await _issue_command(venue)
    assert issued.status is OperationalEvidenceIssuanceStatus.ISSUED
    assert venue.proofs.admissions[-1][0].bundle.verifier_version == "1.0.0"
    assert await venue.provider.admit(**_lookup(command)) is None
    unchanged = OperationalEvidenceAdmissionProvider(
        reader=venue.proofs,
        history=lambda: rotation,
        anchors=venue.anchors,
        verifier_id="operational-evidence-verifier",
        clock=lambda: NOW,
    )
    assert await unchanged.admit(**_lookup(command)) is not None


def _advancing() -> Callable[[], datetime]:
    ticks = itertools.count()
    return lambda: NOW + timedelta(seconds=next(ticks))


async def test_replayed_attempt_keeps_its_outcome_under_an_advancing_clock() -> None:
    venue = VerifierVenue(clock=_advancing())
    command = venue.propose()
    first, _ = await venue.issue(
        _COMMAND, content_digest(command), idempotency_key=command["idempotency_key"]
    )
    request_ids = {issued.attempt_id for issued, _record in venue.proofs.admissions}
    (attempt,) = request_ids
    replay = OperationalEvidenceIssuanceRequest(
        attempt_id=attempt,
        lookup=OperationalEvidenceLookup(**_lookup(command)),
        locator=OperationalEvidenceLocator(
            purpose_id=_COMMAND, coordinates={"idempotency_key": command["idempotency_key"]}
        ),
        producer_id="core-control-plane",
        producer_version="1.0.0",
        requested_at=NOW,
    )
    again = await venue.engine.issue(replay, caller_principal="fdai_core")
    assert again == first and len(venue.proofs.admissions) == 1
    stale = venue.propose(key="context-stale", accepted_at=NOW - timedelta(minutes=20))
    rejected, rejection = await venue.issue(
        _COMMAND, content_digest(stale), idempotency_key="context-stale"
    )
    assert rejection is not None and rejected.status is OperationalEvidenceIssuanceStatus.REJECTED
    replayed = await venue.engine.issue(
        replay.model_copy(
            update={
                "attempt_id": rejection.attempt_id,
                "lookup": OperationalEvidenceLookup(**_lookup(stale)),
                "locator": OperationalEvidenceLocator(
                    purpose_id=_COMMAND, coordinates={"idempotency_key": "context-stale"}
                ),
            }
        ),
        caller_principal="fdai_core",
    )
    assert replayed == rejected and len(venue.proofs.rejections) == 1


async def test_attempt_id_reused_for_another_lookup_is_unavailable() -> None:
    venue = VerifierVenue()
    command = venue.propose()
    await venue.issue(_COMMAND, content_digest(command), idempotency_key=command["idempotency_key"])
    (issued, _record) = venue.proofs.admissions[0]
    other = venue.propose(key="context-other")
    reused = OperationalEvidenceIssuanceRequest(
        attempt_id=issued.attempt_id,
        lookup=OperationalEvidenceLookup(**_lookup(other)),
        locator=OperationalEvidenceLocator(
            purpose_id=_COMMAND, coordinates={"idempotency_key": "context-other"}
        ),
        producer_id="core-control-plane",
        producer_version="1.0.0",
        requested_at=NOW,
    )
    response = await venue.engine.issue(reused, caller_principal="fdai_core")
    assert response.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE
    assert len(venue.proofs.admissions) == 1
