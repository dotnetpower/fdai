"""Focused tests for the canonical N and N-1 record replay the campaign observes.

Schema replay is a claim about record payloads, not about ontology labels. These tests
pin the exact transformation the shared provider contract performs, prove the campaign
never certifies a replay it did not execute on a real persisted record pair, and prove
an unsupported schema version is rejected instead of being replayed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
    OperationalHistoryScenarioStatus,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationPartition,
    ObservationPartitionKind,
    ObservationPartitionState,
    build_observation_partition,
)
from fdai.delivery.operational_history_certification_campaign import (
    CampaignBinding,
    SyntheticScope,
    evaluate_scenario,
)
from fdai.delivery.operational_history_certification_campaign_lifecycle_probes import (
    observe_schema_replay,
)
from fdai.delivery.operational_history_certification_campaign_observations import (
    PRIOR_SCHEMA_VERSION,
    cross_release_stable_body,
    current_schema_record,
    downgrade_to_prior_schema,
    prior_schema_record,
)
from fdai.shared.providers.inventory_observation import (
    INVENTORY_OBSERVATION_SCHEMA_VERSION,
    replay_inventory_observation_schema,
)

SCOPE_REF = "synthetic/oi16-certification/campaign-a"
SOURCE = "0123456789abcdef0123456789abcdef01234567"
RELEASE = "sha256:" + "c" * 64
NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)

# One frozen synthetic current-release record. Every digest asserted below is a pure
# function of this literal, so a silent change to the shared transform breaks a test.
CURRENT_RECORD: Mapping[str, Any] = {
    "schema_version": INVENTORY_OBSERVATION_SCHEMA_VERSION,
    "observation_id": "obs-synthetic-0001",
    "content_digest": "sha256:" + "1" * 64,
    "idempotency_key": "oi16-synthetic-key-0001",
    "subject_kind": "object",
    "observation_kind": "full",
    "mutation_kind": "upsert",
    "subject_ref": "synthetic/oi16-certification/campaign-a/probe-0001",
    "subject_type": "synthetic_operational_probe",
    "properties": {"region": "synthetic", "tier": "probe"},
    "property_mask": ["region", "tier"],
    "scope_ref": SCOPE_REF,
    "operation": "observe",
    "operation_status": "succeeded",
    "tombstone_confirmed": False,
    "watermark": 41,
    "recorded_at": "2026-05-01T11:00:00+00:00",
}


def _binding() -> CampaignBinding:
    return CampaignBinding(
        scope=SyntheticScope(environment="dev", scope_ref=SCOPE_REF),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_start=NOW - timedelta(hours=1),
        window_end=NOW,
    )


def _partition() -> ObservationPartition:
    return build_observation_partition(
        scope_ref=SCOPE_REF,
        interval_start=NOW - timedelta(hours=1),
        interval_end=NOW,
        first_watermark=41,
        last_watermark=41,
        kind=ObservationPartitionKind.BASE,
        state=ObservationPartitionState.VERIFIED,
        correction_of=None,
        retention_policy_digest="sha256:" + "2" * 64,
        created_at=NOW,
    )


class _Records:
    """Serve the exact persisted rows one synthetic partition holds."""

    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records = tuple(records)

    async def archive_records(self, partition_id: str) -> tuple[Mapping[str, object], ...]:
        return self._records


async def _observe(
    persisted: Sequence[Mapping[str, Any]],
    archived: Sequence[Mapping[str, Any]],
) -> OperationalHistoryScenarioStatus:
    observation = await observe_schema_replay(
        binding=_binding(),
        records=_Records(persisted),
        partitions=(_partition(),),
        archived=archived,
    )
    return evaluate_scenario(OperationalHistoryScenario.SCHEMA_REPLAY, observation).status


def _digest(value: Mapping[str, Any]) -> str:
    import hashlib

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


# ----------------------------------------------------------------------------
# The canonical transform
# ----------------------------------------------------------------------------


def test_current_release_replay_is_an_exact_identity() -> None:
    """Replaying an N record MUST NOT change one byte of it."""

    replay = replay_inventory_observation_schema(CURRENT_RECORD)
    assert replay.source_schema_version == INVENTORY_OBSERVATION_SCHEMA_VERSION
    assert replay.target_schema_version == INVENTORY_OBSERVATION_SCHEMA_VERSION
    assert replay.transformed_record == dict(CURRENT_RECORD)
    assert replay.original_digest == _digest(CURRENT_RECORD)
    assert replay.transformed_digest == replay.original_digest


def test_prior_release_replay_upgrades_to_the_exact_current_form() -> None:
    """The N-1 arm MUST produce the documented upgrade, digest included."""

    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    assert prior["schema_version"] == PRIOR_SCHEMA_VERSION
    replay = replay_inventory_observation_schema(prior)
    assert replay.source_schema_version == PRIOR_SCHEMA_VERSION
    assert replay.target_schema_version == INVENTORY_OBSERVATION_SCHEMA_VERSION
    expected = dict(prior)
    expected.update(
        {
            "schema_version": INVENTORY_OBSERVATION_SCHEMA_VERSION,
            "property_mask": ["region", "tier"],
            "scope_ref": None,
            "operation": None,
            "operation_status": None,
            "tombstone_confirmed": False,
        }
    )
    assert replay.transformed_record == expected
    assert replay.original_digest == _digest(prior)
    assert replay.transformed_digest == _digest(expected)
    assert replay.transformed_digest != replay.original_digest


def test_the_upgraded_prior_record_agrees_with_its_own_current_form() -> None:
    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    replay = replay_inventory_observation_schema(prior)
    assert cross_release_stable_body(replay.transformed_record) == cross_release_stable_body(
        CURRENT_RECORD
    )


@pytest.mark.parametrize("version", ["0.8.0", "2.0.0", "1.0", "", "latest"])
def test_an_unsupported_schema_version_is_refused(version: str) -> None:
    record = dict(CURRENT_RECORD)
    record["schema_version"] = version
    with pytest.raises(ValueError, match="schema version is unsupported"):
        replay_inventory_observation_schema(record)


def test_a_record_without_a_schema_version_is_refused() -> None:
    record = {key: value for key, value in CURRENT_RECORD.items() if key != "schema_version"}
    with pytest.raises(ValueError, match="schema version is unsupported"):
        replay_inventory_observation_schema(record)


def test_only_a_current_release_record_can_be_downgraded() -> None:
    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    with pytest.raises(ValueError, match="only a current-release record"):
        downgrade_to_prior_schema(prior)


# ----------------------------------------------------------------------------
# The deployed scenario
# ----------------------------------------------------------------------------


async def test_a_real_persisted_pair_certifies_schema_replay() -> None:
    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    status = await _observe((CURRENT_RECORD,), (prior,))
    assert status is OperationalHistoryScenarioStatus.PASSED


async def test_schema_replay_without_an_archived_prior_record_is_unavailable() -> None:
    """A campaign that archived no N-1 payload has not replayed anything."""

    status = await _observe((CURRENT_RECORD,), ())
    assert status is OperationalHistoryScenarioStatus.UNAVAILABLE


async def test_schema_replay_without_a_persisted_current_record_is_unavailable() -> None:
    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    status = await _observe((), (prior,))
    assert status is OperationalHistoryScenarioStatus.UNAVAILABLE


async def test_an_archived_prior_record_without_its_current_counterpart_is_unavailable() -> None:
    """Two unrelated records MUST NOT be spliced into one replay pair."""

    other = dict(CURRENT_RECORD)
    other["observation_id"] = "obs-synthetic-9999"
    status = await _observe((CURRENT_RECORD,), (downgrade_to_prior_schema(other),))
    assert status is OperationalHistoryScenarioStatus.UNAVAILABLE


async def test_an_unsupported_persisted_schema_never_certifies_schema_replay() -> None:
    """A foreign release inside the synthetic scope fails the scenario."""

    foreign = dict(CURRENT_RECORD)
    foreign["schema_version"] = "2.0.0"
    foreign["observation_id"] = "obs-synthetic-0002"
    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    status = await _observe((CURRENT_RECORD, foreign), (prior,))
    assert status is OperationalHistoryScenarioStatus.FAILED


async def test_an_unsupported_archived_schema_never_certifies_schema_replay() -> None:
    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    foreign = dict(prior)
    foreign["schema_version"] = "0.8.0"
    status = await _observe((CURRENT_RECORD,), (prior, foreign))
    assert status is OperationalHistoryScenarioStatus.FAILED


async def test_only_unsupported_records_leave_schema_replay_unavailable() -> None:
    """Nothing replayable at all is unobserved rather than a silent pass."""

    foreign = dict(CURRENT_RECORD)
    foreign["schema_version"] = "2.0.0"
    status = await _observe((foreign,), (foreign,))
    assert status is OperationalHistoryScenarioStatus.UNAVAILABLE


async def test_a_tampered_prior_record_fails_cross_release_stability() -> None:
    """An N-1 payload that does not upgrade back to its own current form fails."""

    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    prior["subject_ref"] = "synthetic/oi16-certification/campaign-a/probe-tampered"
    status = await _observe((CURRENT_RECORD,), (prior,))
    assert status is OperationalHistoryScenarioStatus.FAILED


def test_record_selection_matches_on_the_exact_release() -> None:
    prior = downgrade_to_prior_schema(CURRENT_RECORD)
    assert current_schema_record((prior, CURRENT_RECORD)) == CURRENT_RECORD
    assert prior_schema_record((CURRENT_RECORD, prior)) == prior
    assert current_schema_record((prior,)) is None
    assert prior_schema_record((CURRENT_RECORD,)) is None
