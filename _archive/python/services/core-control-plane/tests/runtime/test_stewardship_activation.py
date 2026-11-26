"""Owner-queued Console stewardship activation: role, digest, and replay safety."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fdai.runtime.stewardship_activation import (
    PROJECTION_KEY,
    RECEIPT_PREFIX,
    REJECT_DIGEST,
    REJECT_MALFORMED,
    REJECT_ROLE,
    REJECT_UNKNOWN,
    parse_activation_request,
)
from fdai.runtime.stewardship_governance import build_stewardship_governance_worker
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.handover import (
    HandoverDraftArtifact,
    HandoverDraftOutcome,
    HandoverMapping,
    HandoverPerson,
    HandoverSourceSpan,
    StewardResponsibility,
    StewardshipDraft,
)

_CONFIG = Path(__file__).resolve().parents[4] / "config" / "agent-stewardship.yaml"
_ENV = {
    "FDAI_STEWARDSHIP_GOVERNANCE_ENABLED": "true",
    "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
}
_OPERATION = "stewardship.candidate_activation"


def _artifact(upload_id: int) -> HandoverDraftArtifact:
    mapping = HandoverMapping(
        agent_name="Freyr",
        person=HandoverPerson(display_name="Steward Example", oid="oid-example"),
        responsibility=StewardResponsibility.ACCOUNTABLE,
        confidence=0.9,
        citations=(HandoverSourceSpan(doc_id="doc-1", line=1, quote="Freyr steward"),),
    )
    return HandoverDraftArtifact(
        upload_id=UUID(int=upload_id, version=4),
        document_id=UUID(int=2, version=4),
        version_id=UUID(int=3, version=4),
        draft=StewardshipDraft(outcome=HandoverDraftOutcome.DRAFTED, mappings=(mapping,)),
        yaml=_CONFIG.read_text(encoding="utf-8"),
    )


def _proposal_id(number: int) -> str:
    return f"operator-{number:032x}"


async def _queue(
    store: InMemoryStateStore,
    number: int,
    *,
    candidate_id: str,
    digest: str,
    roles: tuple[str, ...] = ("Owner",),
    principal: str = "owner-oid",
) -> str:
    proposal_id = _proposal_id(number)
    record: Mapping[str, Any] = {
        "proposal_id": proposal_id,
        "family": "operations",
        "operation": _OPERATION,
        "principal_id": principal,
        "payload": {
            "payload": {"candidate_id": candidate_id, "candidate_digest": digest},
            "principal_roles": list(roles),
        },
    }
    await store.write_state(f"operator-proposal:operations:{proposal_id}", record)
    return proposal_id


async def _candidate(store: InMemoryStateStore) -> tuple[Any, str, str]:
    worker = build_stewardship_governance_worker(store=store, environment=_ENV)
    assert worker is not None
    artifact = _artifact(21)
    await store.write_state(
        f"handover_draft:{artifact.upload_id}", artifact.model_dump(mode="json")
    )
    assert await worker.run_once() == 1
    (receipt,) = await store.read_states("stewardship_governance:", limit=10)
    candidate_id = str(receipt["pr_ref"]).removeprefix("console-stewardship:")
    stored = await store.read_state(f"stewardship_revision_candidate:{candidate_id}")
    assert stored is not None
    return worker, candidate_id, str(stored["candidate_digest"])


async def _outcome(store: InMemoryStateStore, proposal_id: str) -> Mapping[str, Any]:
    receipt = await store.read_state(f"{RECEIPT_PREFIX}{proposal_id}")
    assert receipt is not None
    return receipt


@pytest.mark.asyncio
async def test_owner_request_activates_once_and_redelivery_changes_nothing() -> None:
    store = InMemoryStateStore()
    worker, candidate_id, digest = await _candidate(store)
    proposal_id = await _queue(store, 1, candidate_id=candidate_id, digest=digest)

    assert await worker.run_once() == 1
    assert (await _outcome(store, proposal_id))["outcome"] == "activated"
    merge = await store.read_state(f"stewardship_merge:console-{candidate_id}")
    assert merge is not None
    assert merge["actor_identity"] == "owner-oid"

    # A second Owner request for the same candidate is recorded but never re-activates.
    second = await _queue(store, 2, candidate_id=candidate_id, digest=digest)
    assert await worker.run_once() == 1
    assert (await _outcome(store, second))["outcome"] == "already_active"
    assert await worker.run_once() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roles", "digest_override", "candidate_override", "reason"),
    [
        (("Approver",), None, None, REJECT_ROLE),
        (("Owner",), "f" * 64, None, REJECT_DIGEST),
        (("Owner",), None, "0" * 16, REJECT_UNKNOWN),
    ],
)
async def test_rejected_requests_never_write_a_merge_record(
    roles: tuple[str, ...],
    digest_override: str | None,
    candidate_override: str | None,
    reason: str,
) -> None:
    store = InMemoryStateStore()
    worker, candidate_id, digest = await _candidate(store)
    proposal_id = await _queue(
        store,
        3,
        candidate_id=candidate_override or candidate_id,
        digest=digest_override or digest,
        roles=roles,
    )

    assert await worker.run_once() == 1
    receipt = await _outcome(store, proposal_id)
    assert (receipt["outcome"], receipt["reason"]) == ("rejected", reason)
    assert await store.read_state(f"stewardship_merge:console-{candidate_id}") is None


@pytest.mark.asyncio
async def test_malformed_stored_request_is_rejected_without_blocking_valid_work() -> None:
    store = InMemoryStateStore()
    worker, candidate_id, digest = await _candidate(store)
    bad = _proposal_id(4)
    await store.write_state(
        f"operator-proposal:operations:{bad}",
        {
            "proposal_id": bad,
            "operation": _OPERATION,
            "principal_id": "owner-oid",
            "payload": {"payload": {"candidate_id": "../x"}, "principal_roles": ["Owner"]},
        },
    )
    good = await _queue(store, 5, candidate_id=candidate_id, digest=digest)

    assert await worker.run_once() == 2
    assert (await _outcome(store, bad))["reason"] == REJECT_MALFORMED
    assert (await _outcome(store, good))["outcome"] == "activated"


@pytest.mark.asyncio
async def test_candidate_projection_lists_open_and_activated_candidates_once() -> None:
    store = InMemoryStateStore()
    worker, candidate_id, digest = await _candidate(store)
    await worker.run_once()
    projection = await store.read_state(PROJECTION_KEY)
    assert projection is not None
    (item,) = projection["items"]
    assert (item["candidate_id"], item["candidate_digest"], item["state"]) == (
        candidate_id,
        digest,
        "open",
    )
    first_generated = projection["generated_at"]

    # An unchanged candidate set does not rewrite the projection.
    await worker.run_once()
    unchanged = await store.read_state(PROJECTION_KEY)
    assert unchanged is not None and unchanged["generated_at"] == first_generated

    await _queue(store, 7, candidate_id=candidate_id, digest=digest)
    await worker.run_once()
    activated = await store.read_state(PROJECTION_KEY)
    assert activated is not None and activated["items"][0]["state"] == "activated"


def test_parser_ignores_other_operations_and_bad_principals() -> None:
    base: dict[str, Any] = {
        "proposal_id": _proposal_id(6),
        "operation": _OPERATION,
        "principal_id": "owner-oid",
        "payload": {
            "payload": {"candidate_id": "0123456789abcdef", "candidate_digest": "a" * 64},
            "principal_roles": ["Owner"],
        },
    }
    assert parse_activation_request(base) is not None
    assert parse_activation_request({**base, "operation": "code_security.scan_request"}) is None
    assert parse_activation_request({**base, "principal_id": "bad principal"}) is None
    assert (
        parse_activation_request(
            {
                **base,
                "payload": {**base["payload"], "principal_roles": [123]},
            }
        )
        is None
    )


def test_runtime_and_delivery_hardening_rounds_h066_to_h081() -> None:
    from datetime import UTC, datetime, timedelta

    from fdai.delivery.identity.handover_review_identity import HandoverIdentityFacts
    from fdai.runtime.handover_knowledge_lifecycle import HandoverKnowledgeLifecycleWorker
    from fdai.runtime.human_assignment_reconciliation import AssignmentReconciliationWorker
    from fdai.runtime.stewardship_activation import StewardshipActivationProcessor
    from fdai.runtime.stewardship_governance import StewardshipGovernanceWorker
    from fdai.runtime.stewardship_identity_health import StewardshipIdentityHealthWorker
    from fdai.runtime.stewardship_merge_effects import StewardshipMergeEffectsWorker

    store = InMemoryStateStore()
    with pytest.raises(ValueError, match="between 1 and 1000"):
        StewardshipActivationProcessor(store=store, batch_limit=True)
    with pytest.raises(ValueError, match="interval MUST be in"):
        HandoverKnowledgeLifecycleWorker(
            store=store,
            bus=None,
            topic="t1",
            interval_seconds=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="interval MUST be positive"):
        StewardshipGovernanceWorker(
            store=store,
            governance=None,
            interval_seconds=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="at least 60 seconds"):
        StewardshipIdentityHealthWorker(
            store=store,
            stewardship=None,  # type: ignore[arg-type]
            directory=None,  # type: ignore[arg-type]
            interval_seconds=True,
        )
    with pytest.raises(ValueError, match="interval MUST be positive"):
        StewardshipMergeEffectsWorker(
            store=store,
            base=None,  # type: ignore[arg-type]
            notifications=None,  # type: ignore[arg-type]
            interval_seconds=True,
        )
    with pytest.raises(ValueError, match="interval MUST be positive"):
        AssignmentReconciliationWorker(
            reconciler=None,
            interval_seconds=float("nan"),  # type: ignore[arg-type]
        )
    now = datetime(2026, 9, 1, tzinfo=UTC)
    facts = HandoverIdentityFacts(
        subject_ref="s1",
        roles=("Reader",),
        group_ids=("g1",),
        observed_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        facts.current(datetime(2026, 9, 1))
