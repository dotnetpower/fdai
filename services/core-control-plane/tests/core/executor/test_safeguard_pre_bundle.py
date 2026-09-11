"""Safety contract for the pre-bundle commitment fixed before target locking.

The commitment is the only record that proves what a dispatch had already
fixed before the logical-target lock existed. Every rejection below is a real
safety boundary: a forged digest, a substituted action, a naive timestamp, or
a truncated durable payload MUST NOT round-trip into a usable commitment.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from fdai.core.executor.safeguard_pre_bundle import (
    SafeguardPreBundleCommitment,
    safeguard_pre_bundle_commitment_from_mapping,
    safeguard_pre_bundle_commitment_to_mapping,
)
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    ExecutionPath,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)

_NOW = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_OTHER_TARGET = "resource:example/rg/vm2"


def _action(*, target: str = "resource:example/rg/vm1") -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID("00000000-0000-0000-0000-000000000010"),
        idempotency_key="example-idem",
        event_id=UUID("00000000-0000-0000-0000-000000000011"),
        action_type="ops.restart-service",
        target_resource_ref=target,
        operation=Operation.RESTART,
        params={"cooldown_seconds": 30},
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.PROVIDER_API_ERROR_STREAK, count=3)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rb-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.SHADOW,
        citing_rules=["ops.restart-service"],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


def _commitment(
    *,
    action: Action | None = None,
    execution_path: ExecutionPath = ExecutionPath.DIRECT_API,
    source_revision: str = _SOURCE_REVISION,
    committed_at: datetime = _NOW,
) -> SafeguardPreBundleCommitment:
    return SafeguardPreBundleCommitment.create(
        action=action or _action(),
        execution_path=execution_path,
        source_revision=source_revision,
        committed_at=committed_at,
    )


def _resealed(**overrides: Any) -> SafeguardPreBundleCommitment:
    """Rebuild a commitment with a recomputed digest so only ``overrides`` differ."""

    base = _commitment()
    candidate = replace(base, **overrides)
    return candidate


class TestCreate:
    def test_create_binds_action_path_and_revision_without_authority(self) -> None:
        commitment = _commitment()

        assert commitment.schema_version == "1.0.0"
        assert commitment.action_digest.startswith("sha256:")
        assert commitment.execution_path is ExecutionPath.DIRECT_API
        assert commitment.source_revision == _SOURCE_REVISION
        assert commitment.committed_at == _NOW
        assert commitment.execution_authority is False
        assert commitment.effect_verification_authority is False

    def test_create_normalizes_a_non_utc_offset_to_utc(self) -> None:
        offset = timezone(timedelta(hours=9))

        commitment = _commitment(committed_at=_NOW.astimezone(offset))

        assert commitment.committed_at.utcoffset() == timedelta(0)
        assert commitment.committed_at == _NOW

    def test_create_rejects_a_naive_commit_time(self) -> None:
        with pytest.raises(ValueError, match="MUST include a timezone"):
            _commitment(committed_at=datetime(2026, 9, 11, 1, 0))

    def test_create_rejects_a_non_datetime_commit_time(self) -> None:
        with pytest.raises(ValueError, match="MUST include a timezone"):
            SafeguardPreBundleCommitment.create(
                action=_action(),
                execution_path=ExecutionPath.DIRECT_API,
                source_revision=_SOURCE_REVISION,
                committed_at="2026-09-11T01:00:00Z",  # type: ignore[arg-type]
            )

    def test_create_rejects_a_non_canonical_source_revision(self) -> None:
        with pytest.raises(ValueError, match="source revision MUST be canonical"):
            _commitment(source_revision="main")

    def test_create_rejects_a_subclass(self) -> None:
        class _Forged(SafeguardPreBundleCommitment):
            pass

        with pytest.raises(TypeError, match="does not support subclasses"):
            _Forged.create(
                action=_action(),
                execution_path=ExecutionPath.DIRECT_API,
                source_revision=_SOURCE_REVISION,
                committed_at=_NOW,
            )


class TestValidation:
    def test_unsupported_schema_version_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported safeguard pre-bundle"):
            _resealed(schema_version="2.0.0")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field",
        ["execution_authority", "effect_verification_authority"],
    )
    def test_a_commitment_can_never_carry_authority(self, field: str) -> None:
        with pytest.raises(ValueError, match="MUST NOT grant authority"):
            _resealed(**{field: True})

    def test_a_non_sha256_action_digest_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="action digest MUST be SHA-256"):
            _resealed(action_digest="md5:" + "0" * 32)

    def test_a_non_enum_execution_path_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="execution path is invalid"):
            _resealed(execution_path="direct_api")  # type: ignore[arg-type]

    def test_an_uppercase_execution_fingerprint_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="fingerprint MUST be lowercase SHA-256"):
            _resealed(execution_fingerprint="A" * 64)

    def test_a_naive_committed_at_is_rejected_on_construction(self) -> None:
        with pytest.raises(ValueError, match="committed_at MUST include a timezone"):
            _resealed(committed_at=datetime(2026, 9, 11, 1, 0))

    def test_a_non_utc_committed_at_is_rejected_on_construction(self) -> None:
        with pytest.raises(ValueError, match="committed_at MUST be normalized to UTC"):
            _resealed(committed_at=_NOW.astimezone(timezone(timedelta(hours=9))))

    def test_a_malformed_commitment_digest_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="commitment digest MUST be SHA-256"):
            _resealed(commitment_digest="sha256:not-a-digest")

    def test_a_well_formed_but_wrong_commitment_digest_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="commitment digest mismatched"):
            _resealed(commitment_digest="sha256:" + "b" * 64)


class TestRequireMatches:
    def test_the_exact_dispatch_context_matches(self) -> None:
        commitment = _commitment()

        commitment.require_matches(
            action=_action(),
            execution_path=ExecutionPath.DIRECT_API,
            source_revision=_SOURCE_REVISION,
        )

    def test_a_substituted_action_is_rejected(self) -> None:
        commitment = _commitment()

        with pytest.raises(ValueError, match="changed dispatch context"):
            commitment.require_matches(
                action=_action(target=_OTHER_TARGET),
                execution_path=ExecutionPath.DIRECT_API,
                source_revision=_SOURCE_REVISION,
            )

    def test_a_substituted_execution_path_is_rejected(self) -> None:
        commitment = _commitment()

        with pytest.raises(ValueError, match="changed dispatch context"):
            commitment.require_matches(
                action=_action(),
                execution_path=ExecutionPath.TOOL_CALL,
                source_revision=_SOURCE_REVISION,
            )

    def test_a_substituted_source_revision_is_rejected(self) -> None:
        commitment = _commitment()

        with pytest.raises(ValueError, match="changed dispatch context"):
            commitment.require_matches(
                action=_action(),
                execution_path=ExecutionPath.DIRECT_API,
                source_revision="commit:" + "c" * 40,
            )


class TestDurableMapping:
    def test_a_commitment_round_trips_through_the_durable_mapping(self) -> None:
        commitment = _commitment()

        mapping = safeguard_pre_bundle_commitment_to_mapping(commitment)
        restored = safeguard_pre_bundle_commitment_from_mapping(mapping)

        assert restored == commitment
        assert mapping["execution_authority"] is False
        assert mapping["effect_verification_authority"] is False

    def test_the_serializer_requires_an_exact_commitment(self) -> None:
        class _Forged(SafeguardPreBundleCommitment):
            pass

        base = _commitment()
        forged = _Forged(
            schema_version=base.schema_version,
            action_digest=base.action_digest,
            execution_path=base.execution_path,
            execution_fingerprint=base.execution_fingerprint,
            source_revision=base.source_revision,
            committed_at=base.committed_at,
            commitment_digest=base.commitment_digest,
        )

        with pytest.raises(ValueError, match="requires an exact commitment"):
            safeguard_pre_bundle_commitment_to_mapping(forged)

    def test_an_incomplete_durable_payload_is_rejected(self) -> None:
        mapping = safeguard_pre_bundle_commitment_to_mapping(_commitment())
        mapping.pop("source_revision")

        with pytest.raises(ValueError, match="fields are incomplete"):
            safeguard_pre_bundle_commitment_from_mapping(mapping)

    def test_an_unknown_durable_field_is_rejected(self) -> None:
        mapping = safeguard_pre_bundle_commitment_to_mapping(_commitment())
        mapping["execution_authority_override"] = True

        with pytest.raises(ValueError, match="fields are incomplete"):
            safeguard_pre_bundle_commitment_from_mapping(mapping)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("committed_at", "not-a-timestamp"),
            ("execution_path", "teleport"),
        ],
    )
    def test_a_malformed_durable_field_is_rejected(self, field: str, value: str) -> None:
        mapping = safeguard_pre_bundle_commitment_to_mapping(_commitment())
        mapping[field] = value

        with pytest.raises(ValueError, match="fields are malformed"):
            safeguard_pre_bundle_commitment_from_mapping(mapping)

    def test_a_tampered_durable_digest_cannot_be_restored(self) -> None:
        mapping = safeguard_pre_bundle_commitment_to_mapping(_commitment())
        mapping["action_digest"] = "sha256:" + "d" * 64

        with pytest.raises(ValueError, match="commitment digest mismatched"):
            safeguard_pre_bundle_commitment_from_mapping(mapping)
