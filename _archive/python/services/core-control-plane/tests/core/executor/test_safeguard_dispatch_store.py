"""Safeguard dispatch persistence result and receipt boundary tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest
from fdai.core.executor.safeguard_dispatch_checkpoint import record_dispatch_observation
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchPersistenceDecision,
    SafeguardDispatchPersistenceResult,
    SafeguardDispatchTransitionReceipt,
    classify_safeguard_dispatch_evidence,
)

from tests.core.executor.test_safeguard_dispatch_checkpoint import (
    _DIGEST,
    _NOW,
    _bundle_persistence_receipt,
    _dispatch_started_record,
    _evidence_fixture,
    _observation,
)


def test_persistence_results_bind_exact_candidate_and_receipt() -> None:
    record = _evidence_fixture()[0]
    receipt = _bundle_persistence_receipt(record)
    persisted = SafeguardDispatchPersistenceResult(
        candidate_identity=record.identity,
        decision=SafeguardDispatchPersistenceDecision.PERSISTED,
        observed_record=record,
        transition_receipt=receipt,
    )
    duplicate = SafeguardDispatchPersistenceResult(
        candidate_identity=record.identity,
        decision=SafeguardDispatchPersistenceDecision.DUPLICATE_SAME,
        observed_record=record,
        transition_receipt=None,
    )
    conflicting_identity = _evidence_fixture(action_name="other")[0].identity
    conflict = SafeguardDispatchPersistenceResult(
        candidate_identity=conflicting_identity,
        decision=SafeguardDispatchPersistenceDecision.CONFLICT,
        observed_record=record,
        transition_receipt=None,
    )

    assert persisted.transition_receipt is receipt
    assert duplicate.decision is SafeguardDispatchPersistenceDecision.DUPLICATE_SAME
    assert conflict.decision is SafeguardDispatchPersistenceDecision.CONFLICT
    assert (
        classify_safeguard_dispatch_evidence(record, record.identity)
        is SafeguardDispatchPersistenceDecision.DUPLICATE_SAME
    )
    assert (
        classify_safeguard_dispatch_evidence(record, conflicting_identity)
        is SafeguardDispatchPersistenceDecision.CONFLICT
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"candidate_identity": object()}, "exact candidate"),
        ({"decision": "persisted"}, "decision is invalid"),
        ({"observed_record": object()}, "exact observed record"),
        ({"transition_receipt": None}, "requires insert receipt"),
    ),
)
def test_persisted_result_rejects_invalid_evidence(
    changes: dict[str, object],
    message: str,
) -> None:
    record = _evidence_fixture()[0]
    values: dict[str, object] = {
        "candidate_identity": record.identity,
        "decision": SafeguardDispatchPersistenceDecision.PERSISTED,
        "observed_record": record,
        "transition_receipt": _bundle_persistence_receipt(record),
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        SafeguardDispatchPersistenceResult(**cast(Any, values))


def test_observed_result_rejects_receipt_decision_and_key_mismatch() -> None:
    record = _evidence_fixture()[0]
    receipt = _bundle_persistence_receipt(record)
    conflicting_identity = _evidence_fixture(action_name="other")[0].identity
    wrong_target_identity = _evidence_fixture(target_ref="resource/other")[0].identity

    with pytest.raises(ValueError, match="MUST NOT claim persistence"):
        SafeguardDispatchPersistenceResult(
            candidate_identity=record.identity,
            decision=SafeguardDispatchPersistenceDecision.DUPLICATE_SAME,
            observed_record=record,
            transition_receipt=receipt,
        )
    with pytest.raises(ValueError, match="mismatched candidate"):
        SafeguardDispatchPersistenceResult(
            candidate_identity=conflicting_identity,
            decision=SafeguardDispatchPersistenceDecision.DUPLICATE_SAME,
            observed_record=record,
            transition_receipt=None,
        )
    with pytest.raises(ValueError, match="key mismatched"):
        classify_safeguard_dispatch_evidence(record, wrong_target_identity)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"schema_version": "2.0.0"}, "unsupported"),
        ({"execution_authority": True}, "MUST NOT grant authority"),
        ({"effect_verified": True}, "MUST NOT grant authority"),
        ({"record": object()}, "requires exact record"),
        ({"bundle_persistence_receipt": object()}, "has prerequisites"),
        ({"current_lock_assessment": object()}, "has prerequisites"),
        ({"store_receipt_digest": "invalid"}, "store_receipt_digest"),
        ({"recorded_at": _NOW - timedelta(microseconds=1)}, "backdated"),
        ({"receipt_digest": "invalid"}, "receipt_digest"),
    ),
)
def test_initial_transition_receipt_rejects_invalid_evidence(
    changes: dict[str, object],
    message: str,
) -> None:
    record = _evidence_fixture()[0]
    receipt = _bundle_persistence_receipt(record)

    with pytest.raises(ValueError, match=message):
        replace(receipt, **cast(Any, changes))


def test_dispatch_started_transition_binds_initial_persistence_receipt() -> None:
    record = _evidence_fixture()[0]
    started, persistence_receipt = _dispatch_started_record(record)

    receipt = SafeguardDispatchTransitionReceipt.create(
        prior_record=record,
        record=started,
        bundle_persistence_receipt=persistence_receipt,
        store_receipt_digest=_DIGEST,
        recorded_at=started.state_changed_at,
    )

    assert receipt.prior_record is record
    assert receipt.bundle_persistence_receipt is persistence_receipt


def test_transition_receipt_rejects_invalid_predecessor_and_prerequisites() -> None:
    record = _evidence_fixture()[0]
    initial_receipt = _bundle_persistence_receipt(record)
    started, persistence_receipt = _dispatch_started_record(record)
    started_receipt = SafeguardDispatchTransitionReceipt.create(
        prior_record=record,
        record=started,
        bundle_persistence_receipt=persistence_receipt,
        store_receipt_digest=_DIGEST,
        recorded_at=started.state_changed_at,
    )

    with pytest.raises(ValueError, match="initial safeguard dispatch transition is invalid"):
        replace(initial_receipt, record=started)
    with pytest.raises(ValueError, match="predecessor is invalid"):
        replace(started_receipt, prior_record=cast(Any, object()))
    with pytest.raises(ValueError, match="lacks bundle persistence receipt"):
        replace(started_receipt, bundle_persistence_receipt=None)

    started_record, observation = _observation(record)
    observed = record_dispatch_observation(
        started_record,
        observation=observation,
        changed_at=observation.observed_at,
    )
    with pytest.raises(ValueError, match="non-start transition"):
        SafeguardDispatchTransitionReceipt.create(
            prior_record=started_record,
            record=observed,
            bundle_persistence_receipt=persistence_receipt,
            store_receipt_digest=_DIGEST,
            recorded_at=observed.state_changed_at,
        )
    with pytest.raises(ValueError, match="receipt digest mismatched"):
        replace(initial_receipt, receipt_digest="sha256:" + "0" * 64)


def test_transition_receipt_factory_rejects_subclasses() -> None:
    class DerivedReceipt(SafeguardDispatchTransitionReceipt):
        pass

    record = _evidence_fixture()[0]
    with pytest.raises(TypeError, match="does not support subclasses"):
        DerivedReceipt.create(
            prior_record=None,
            record=record,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )
