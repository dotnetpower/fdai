"""Malformed durable safeguard dispatch payload boundary tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    PreReleaseOwnershipCheckpoint,
    record_dispatch_observation,
    record_pre_release_checkpoint,
)
from fdai.core.executor.safeguard_dispatch_codec import (
    safeguard_dispatch_record_from_mapping,
    safeguard_dispatch_record_to_mapping,
)
from fdai.core.executor.safeguard_dispatch_start_codec import (
    dispatch_start_checkpoint_from_mapping,
    dispatch_start_checkpoint_to_mapping,
)
from fdai.core.executor.target_dispatch_fence_codec import (
    target_dispatch_fence_from_mapping,
    target_dispatch_fence_to_mapping,
)

from tests.core.executor.test_safeguard_dispatch_checkpoint import (
    _assessment,
    _bundle_record,
    _dispatch_started_record,
    _observation,
)
from tests.core.executor.test_target_dispatch_fence import _prepared


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "2.0.0"),
        ("identity", []),
        ("bundle", []),
        ("state", "invalid"),
        ("revision", True),
        ("prior_record_digest", 1),
        ("dispatch_start_checkpoint", []),
        ("dispatch_observation", []),
        ("pre_release_checkpoint", []),
        ("independent_effect_state", "verified"),
        ("state_changed_at", "invalid"),
        ("state_changed_at", "2026-09-10T13:00:00"),
        ("record_digest", 1),
        ("execution_authority", True),
        ("effect_verified", True),
    ),
)
def test_safeguard_dispatch_record_decoder_rejects_malformed_fields(
    field: str,
    value: object,
) -> None:
    mapping = safeguard_dispatch_record_to_mapping(_bundle_record()[0])
    mapping[field] = value

    with pytest.raises((TypeError, ValueError)):
        safeguard_dispatch_record_from_mapping(mapping)


def test_safeguard_dispatch_serializer_requires_exact_record() -> None:
    with pytest.raises(ValueError, match="requires an exact record"):
        safeguard_dispatch_record_to_mapping(cast(Any, object()))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "2.0.0"),
        ("evidence_identity_digest", 1),
        ("bundle_record_revision", True),
        ("in_flight_reservation_receipt", []),
        ("prepared_fence", []),
        ("in_flight_fence", []),
        ("dispatch_started_at", "invalid"),
        ("dispatch_started_at", "2026-09-10T13:00:00"),
        ("checkpoint_digest", 1),
        ("execution_authority", True),
        ("effect_verified", True),
    ),
)
def test_dispatch_start_decoder_rejects_malformed_fields(
    field: str,
    value: object,
) -> None:
    record = _bundle_record()[0]
    started, _receipt = _dispatch_started_record(record)
    checkpoint = started.dispatch_start_checkpoint
    assert checkpoint is not None
    mapping = dispatch_start_checkpoint_to_mapping(checkpoint)
    mapping[field] = value

    with pytest.raises((TypeError, ValueError)):
        dispatch_start_checkpoint_from_mapping(mapping)


def test_dispatch_start_decoder_rejects_malformed_prior_reservation() -> None:
    record = _bundle_record()[0]
    started, _receipt = _dispatch_started_record(record)
    checkpoint = started.dispatch_start_checkpoint
    assert checkpoint is not None
    mapping = dispatch_start_checkpoint_to_mapping(checkpoint)
    receipt = cast(dict[str, object], mapping["in_flight_reservation_receipt"])
    receipt["prior_record"] = []

    with pytest.raises(ValueError, match="prior record MUST be an object"):
        dispatch_start_checkpoint_from_mapping(mapping)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "2.0.0"),
        ("identity", []),
        ("continuity_strategy", "unsupported"),
        ("state", "invalid"),
        ("revision", True),
        ("prior_record_digest", 1),
        ("audit_append_receipt_digest", 1),
        ("state_changed_at", "invalid"),
        ("state_changed_at", "2026-09-10T13:00:00"),
        ("record_digest", 1),
        ("execution_authority", True),
        ("effect_verified", True),
    ),
)
def test_target_dispatch_fence_decoder_rejects_malformed_fields(
    field: str,
    value: object,
) -> None:
    mapping = target_dispatch_fence_to_mapping(_prepared())
    mapping[field] = value

    with pytest.raises((TypeError, ValueError)):
        target_dispatch_fence_from_mapping(mapping)


def test_target_dispatch_fence_serializer_requires_exact_record() -> None:
    with pytest.raises(ValueError, match="requires an exact record"):
        target_dispatch_fence_to_mapping(cast(Any, object()))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("rejection_reasons", "invalid"),
        ("unproven_reason", "invalid"),
        ("verifier_id", 1),
        ("evaluated_at", 1),
    ),
)
def test_pre_release_checkpoint_decoder_rejects_malformed_optional_fields(
    field: str,
    value: object,
) -> None:
    record, reservation = _bundle_record()
    started, observation = _observation(record)
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    assessment = _assessment(reservation)
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=assessment,
        not_before=observation.observed_at,
        observed_at=assessment.evaluated_at,
    )
    pre_release = record_pre_release_checkpoint(
        observed,
        checkpoint=checkpoint,
        current_lock_assessment=assessment,
        changed_at=checkpoint.observed_at,
    )
    mapping = deepcopy(safeguard_dispatch_record_to_mapping(pre_release))
    checkpoint_mapping = cast(dict[str, object], mapping["pre_release_checkpoint"])
    checkpoint_mapping[field] = value

    with pytest.raises((TypeError, ValueError)):
        safeguard_dispatch_record_from_mapping(mapping)
