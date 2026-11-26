"""Durable-payload contract for the post-release closure codec.

The codec is the boundary between a durable row and an in-memory closure
record. A payload with a wrong shape, a wrong type, a naive timestamp, or a
flipped authority flag MUST NOT be reconstructed into something the control
plane would then treat as proof.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fdai.core.executor.post_release_closure import (
    ReconciliationEvidenceKind,
    ReconciliationOutcome,
)
from fdai.core.executor.post_release_closure_codec import (
    post_release_closure_from_mapping,
    post_release_closure_to_mapping,
)
from fdai.core.executor.post_release_closure_plan import (
    build_reconciled_post_release_closure,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import AuthoritativeSinkState

from tests.core.executor.test_post_release_closure import (
    _initial_plan,
    _reconciliation_evidence,
)
from tests.core.executor.test_safeguard_dispatch_checkpoint import _NOW

_WRONG_DIGEST = "sha256:" + "9" * 64


def _mapping() -> dict[str, Any]:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)
    return post_release_closure_to_mapping(plan.record)


def _reconciled_mapping() -> dict[str, Any]:
    initial = _initial_plan(sink_state=AuthoritativeSinkState.ACCEPTED)
    reconciled = build_reconciled_post_release_closure(
        prior_closure=initial.record,
        pre_release_record=initial.pre_release_record,
        reservation_record=initial.reservation_record,
        quarantined_fence=initial.fence_record,
        release_receipt=initial.release_receipt,
        evidence=_reconciliation_evidence(
            initial,
            kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
            outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
        ),
        reconciled_at=_NOW + timedelta(seconds=6),
    )
    return post_release_closure_to_mapping(reconciled.record)


def test_a_reconciled_closure_round_trips_with_its_evidence() -> None:
    mapping = _reconciled_mapping()

    restored = post_release_closure_from_mapping(mapping)

    assert restored.reconciliation_evidence is not None
    assert post_release_closure_to_mapping(restored) == mapping


def test_the_serializer_requires_an_exact_closure_record() -> None:
    with pytest.raises(ValueError, match="serializer requires an exact record"):
        post_release_closure_to_mapping({"record": "closure"})  # type: ignore[arg-type]


def test_a_non_object_identity_is_rejected() -> None:
    mapping = _mapping()
    mapping["identity"] = "identity"

    with pytest.raises(ValueError, match="identity MUST be an object"):
        post_release_closure_from_mapping(mapping)


def test_a_non_object_reconciliation_evidence_is_rejected() -> None:
    mapping = _mapping()
    mapping["reconciliation_evidence"] = "verified"

    with pytest.raises(ValueError, match="evidence MUST be an object or null"):
        post_release_closure_from_mapping(mapping)


def test_a_non_string_digest_is_rejected() -> None:
    mapping = _mapping()
    mapping["record_digest"] = 7

    with pytest.raises(ValueError, match="record_digest MUST be a string"):
        post_release_closure_from_mapping(mapping)


def test_a_non_string_optional_field_is_rejected() -> None:
    mapping = _mapping()
    mapping["prior_record_digest"] = 7

    with pytest.raises(ValueError, match="prior_record_digest MUST be a string or null"):
        post_release_closure_from_mapping(mapping)


def test_a_non_integer_revision_is_rejected() -> None:
    mapping = _mapping()
    mapping["revision"] = "1"

    with pytest.raises(ValueError, match="revision MUST be an integer"):
        post_release_closure_from_mapping(mapping)


def test_a_malformed_timestamp_is_rejected() -> None:
    mapping = _mapping()
    mapping["closed_at"] = 1789000000

    with pytest.raises(ValueError, match="closed_at MUST be a timestamp"):
        post_release_closure_from_mapping(mapping)


def test_a_naive_timestamp_is_rejected() -> None:
    mapping = _mapping()
    mapping["closed_at"] = "2026-09-11T01:00:04"

    with pytest.raises(ValueError, match="closed_at MUST include a timezone"):
        post_release_closure_from_mapping(mapping)


@pytest.mark.parametrize("field", ["execution_authority", "effect_verified"])
def test_a_durable_payload_can_never_restore_authority(field: str) -> None:
    mapping = _mapping()
    mapping[field] = True

    with pytest.raises(ValueError, match=f"{field} MUST be false"):
        post_release_closure_from_mapping(mapping)


def test_an_unsupported_schema_is_rejected() -> None:
    mapping = _mapping()
    mapping["schema_version"] = "2.0.0"

    with pytest.raises(ValueError, match="unsupported post-release closure schema"):
        post_release_closure_from_mapping(mapping)


def test_a_claimed_independent_effect_state_is_rejected() -> None:
    mapping = _mapping()
    mapping["independent_effect_state"] = "verified"

    with pytest.raises(ValueError, match="independent effect state MUST be pending"):
        post_release_closure_from_mapping(mapping)


def test_an_incomplete_durable_payload_is_rejected() -> None:
    mapping = _mapping()
    mapping.pop("closed_at")

    with pytest.raises(ValueError, match="post-release closure record"):
        post_release_closure_from_mapping(mapping)


def test_an_incomplete_reconciliation_payload_is_rejected() -> None:
    mapping = _reconciled_mapping()
    evidence = dict(mapping["reconciliation_evidence"])
    evidence.pop("trust_anchor_id")
    mapping["reconciliation_evidence"] = evidence

    with pytest.raises(ValueError, match="reconciliation evidence"):
        post_release_closure_from_mapping(mapping)
