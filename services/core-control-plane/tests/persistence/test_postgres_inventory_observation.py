"""PostgreSQL normalized inventory observation journal tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import MethodType
from typing import Any

import pytest
from fdai.delivery.persistence import postgres_inventory_observation as observation_module
from fdai.delivery.persistence.postgres_inventory_observation import (
    InventoryObservationAppendResult,
    PostgresInventoryObservationJournal,
    _append_records,
)
from fdai.delivery.persistence.postgres_inventory_projection_replay import (
    build_projection_replay_observation,
    projection_freshness_ceiling,
    projection_replay_drops,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_snapshot_replay import (
    build_active_snapshot_observation,
)
from fdai.shared.providers.inventory import RelationshipDropReason
from fdai.shared.providers.inventory_observation import (
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.rowcount = 0

    async def executemany(self, _query: str, _params: object) -> None:
        return None

    async def fetchall(self) -> list[dict[str, object]]:
        return self._rows

    async def fetchone(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, retained: dict[str, object]) -> None:
        self._retained = retained
        self.transactions = 0
        self.executions: list[str] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def transaction(self) -> _Connection:
        self.transactions += 1
        return self

    def cursor(self) -> _Cursor:
        return _Cursor([])

    async def execute(self, query: str, _params: object = None) -> _Cursor:
        self.executions.append(query)
        if "WHERE idempotency_key=ANY" in query:
            return _Cursor([self._retained])
        if "SELECT value FROM state_kv" in query:
            return _Cursor([])
        if "SELECT COUNT(*) AS pending" in query:
            return _Cursor([{"pending": 0}])
        return _Cursor([])


def _observation(properties: dict[str, Any]) -> NormalizedInventoryObservation:
    return NormalizedInventoryObservation.create(
        idempotency_key="event:stable",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.FULL,
        mutation_kind=InventoryMutationKind.UPSERT,
        subject_ref="resource-1",
        subject_type="compute.vm",
        properties=properties,
        property_mask=tuple(properties),
        properties_complete=True,
        links_complete=False,
        tombstone_confirmed=False,
        source_identity="test.inventory",
        source_event_id="event-1",
        source_revision="revision-1",
        effective_at=NOW,
        observed_at=NOW,
        evidence_cutoff=NOW,
        recorded_at=NOW,
    )


def _tombstone() -> NormalizedInventoryObservation:
    return NormalizedInventoryObservation.create(
        idempotency_key="event:tombstone",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.TOMBSTONE,
        mutation_kind=InventoryMutationKind.DELETE,
        subject_ref="resource-1",
        subject_type="compute.vm",
        properties={},
        property_mask=(),
        properties_complete=False,
        links_complete=False,
        tombstone_confirmed=False,
        source_identity="test.inventory",
        source_event_id="event-tombstone",
        source_revision="revision-1",
        effective_at=NOW,
        observed_at=NOW,
        evidence_cutoff=NOW,
        recorded_at=NOW,
    )


async def test_replayed_tombstone_does_not_recreate_pending_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = _tombstone()
    connection = _Connection({})
    journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused")
    )

    async def append_records(
        _connection: object,
        _observations: Sequence[NormalizedInventoryObservation],
    ) -> InventoryObservationAppendResult:
        return InventoryObservationAppendResult(11, 0)

    async def bind(
        _connection: object,
        _observations: Sequence[NormalizedInventoryObservation],
        *,
        allow_oi16_synthetic: bool = False,
    ) -> frozenset[str]:
        del allow_oi16_synthetic
        return frozenset({observation.observation_id})

    monkeypatch.setattr(observation_module, "_append_records", append_records)
    monkeypatch.setattr(observation_module, "bind_observation_lifecycle", bind)

    result = await journal.append_change(
        connection,  # type: ignore[arg-type]
        (observation,),
    )

    assert result == InventoryObservationAppendResult(11, 0)
    assert not any(
        "inventory_observation_pending_tombstone" in query for query in connection.executions
    )


async def test_idempotency_key_rejects_changed_observation_content() -> None:
    retained = _observation({"sku": "old"})
    changed = _observation({"sku": "new"})
    connection = _Connection(
        {
            "watermark": 1,
            "idempotency_key": retained.idempotency_key,
            "subject_kind": retained.subject_kind.value,
            "subject_ref": retained.subject_ref,
            "content_digest": retained.content_digest,
        }
    )

    with pytest.raises(ValueError, match="idempotency key changed content"):
        await _append_records(connection, (changed,))  # type: ignore[arg-type]


async def test_bounded_change_batch_owns_one_transaction_and_delegates() -> None:
    observation = _observation({"sku": "one"})
    connection = _Connection(
        {
            "watermark": 7,
            "idempotency_key": observation.idempotency_key,
            "subject_kind": observation.subject_kind.value,
            "subject_ref": observation.subject_ref,
            "content_digest": observation.content_digest,
        }
    )
    journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused")
    )
    calls: list[Sequence[NormalizedInventoryObservation]] = []

    async def connect(_self: object) -> _Connection:
        return connection

    async def append_change(
        _self: object,
        _connection: object,
        observations: Sequence[NormalizedInventoryObservation],
    ) -> InventoryObservationAppendResult:
        calls.append(observations)
        return InventoryObservationAppendResult(7, 0)

    journal._connect = MethodType(connect, journal)  # type: ignore[method-assign]
    journal.append_change = MethodType(append_change, journal)  # type: ignore[method-assign]

    result = await journal.append_change_batch((observation,))

    assert result == InventoryObservationAppendResult(7, 0)
    assert calls == [(observation,)]
    assert connection.transactions == 1


async def test_bounded_change_batch_refuses_an_unbounded_batch() -> None:
    journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused")
    )

    with pytest.raises(ValueError, match="exceeds its bound"):
        await journal.append_change_batch([_observation({"sku": "one"})] * 1025)


def test_projection_replay_reconstructs_verified_relationship_metadata() -> None:
    generation = "snapshot-replay"
    state_fact = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="provider-v1",
        effective_at=NOW - timedelta(minutes=1),
        recorded_at=NOW,
        evidence_cutoff=NOW - timedelta(minutes=1),
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory-receipt",),
    )
    link_metadata = LinkObservationMetadata(
        state_fact=state_fact,
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity="inventory-verifier",
        verifier_revision="verifier-v1",
        verification_receipt_ref="verification-receipt",
        inventory_generation=generation,
        mapping_id="test.mapping",
        mapping_revision="sha256:" + "1" * 64,
        source_schema_version="provider-v1",
        source_schema_digest="sha256:" + "2" * 64,
    )
    records = (
        _projection_record(generation, "resource-a"),
        _projection_record(generation, "resource-b"),
        NormalizedInventoryObservation.create(
            idempotency_key="projection:relationship",
            subject_kind=InventoryObservationSubjectKind.RELATIONSHIP,
            observation_kind=InventoryObservationKind.FULL,
            mutation_kind=InventoryMutationKind.UPSERT,
            subject_ref="relationship-1",
            subject_type="depends_on",
            properties={LINK_OBSERVATION_METADATA_PROPERTY: link_metadata.to_mapping()},
            property_mask=(LINK_OBSERVATION_METADATA_PROPERTY,),
            properties_complete=True,
            links_complete=True,
            tombstone_confirmed=False,
            source_identity="inventory.reconciliation",
            source_event_id=f"snapshot:{generation}",
            source_revision=generation,
            effective_at=NOW,
            observed_at=NOW,
            evidence_cutoff=NOW,
            recorded_at=NOW,
            from_id="resource-a",
            from_type="compute.vm",
            link_type="depends_on",
            to_id="resource-b",
            to_type="compute.vm",
        ),
    )
    metadata = {
        "projection_complete": True,
        "relationship_drop_classifications": [],
        "relationship_coverage": {
            "total_candidates": 1,
            "materialized": 1,
            "reviewed_unavailable": 0,
            "unclassified": 0,
            "complete": True,
        },
    }
    prior_manifest = {
        "dropped_reasons": [],
        "object_content": [
            {
                "id": "resource-a",
                "properties": {
                    "properties": {STATE_FACT_METADATA_PROPERTY: state_fact.to_mapping()}
                },
            },
            {"id": "resource-b", "properties": {"properties": {}}},
        ],
    }

    observation = build_projection_replay_observation(
        generation=generation,
        recorded_at=NOW,
        metadata=metadata,
        prior_manifest=prior_manifest,
        records=records,
    )

    assert len(observation.resources) == 2
    assert observation.resources[0].last_seen == NOW.isoformat()
    assert observation.resources[1].last_seen is None
    assert observation.links[0].observation_metadata == link_metadata
    assert observation.relationship_drops == ()
    assert (
        projection_freshness_ceiling(
            {
                "object_content": [
                    {
                        "properties": {
                            "properties": {STATE_FACT_METADATA_PROPERTY: state_fact.to_mapping()}
                        }
                    },
                    {"properties": {"properties": {}}},
                ]
            }
        )
        == 300
    )


def test_active_snapshot_bootstrap_rehydrates_the_verified_observation() -> None:
    generation = "snapshot-bootstrap"
    state_fact = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="provider-v1",
        effective_at=NOW - timedelta(minutes=1),
        recorded_at=NOW,
        evidence_cutoff=NOW - timedelta(minutes=1),
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory-receipt",),
    )
    link_metadata = LinkObservationMetadata(
        state_fact=state_fact,
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity="inventory-verifier",
        verifier_revision="verifier-v1",
        verification_receipt_ref="verification-receipt",
        inventory_generation=generation,
        mapping_id="test.mapping",
        mapping_revision="sha256:" + "1" * 64,
        source_schema_version="provider-v1",
        source_schema_digest="sha256:" + "2" * 64,
    )
    observation = build_active_snapshot_observation(
        snapshot={
            "id": generation,
            "completed_at": NOW,
            "metadata": {
                "projection_complete": True,
                "relationship_drop_classifications": [],
                "relationship_coverage": {
                    "total_candidates": 1,
                    "materialized": 1,
                    "reviewed_unavailable": 0,
                    "unclassified": 0,
                    "complete": True,
                },
            },
        },
        resource_rows=(
            {
                "resource_id": "resource-a",
                "resource_type": "compute.vm",
                "props": {
                    "name": "vm-a",
                    STATE_FACT_METADATA_PROPERTY: state_fact.to_mapping(),
                },
                "provider_ref": "provider/resource-a",
                "last_seen": NOW,
            },
            {
                "resource_id": "resource-b",
                "resource_type": "network.interface",
                "props": {"name": "nic-b"},
                "provider_ref": None,
                "last_seen": None,
            },
        ),
        link_rows=(
            {
                "from_id": "resource-b",
                "from_type": "network.interface",
                "link_type": "attached_to",
                "to_id": "resource-a",
                "to_type": "compute.vm",
                "props": {
                    "slot": "primary",
                    LINK_OBSERVATION_METADATA_PROPERTY: link_metadata.to_mapping(),
                    "provider_relationship_evidence": {"redacted": True},
                },
            },
        ),
        prior_manifest={
            "generation": generation,
            "dropped_reasons": [],
            "object_content": [],
        },
    )

    assert observation.generation == generation
    assert observation.recorded_at == NOW
    assert observation.resources[0].last_seen == NOW.isoformat()
    assert observation.links[0].link_props == {"slot": "primary"}
    assert observation.links[0].observation_metadata == link_metadata


def test_active_snapshot_bootstrap_cross_checks_identity_only_legacy_evidence() -> None:
    generation = "snapshot-legacy"
    observation = build_active_snapshot_observation(
        snapshot={
            "id": generation,
            "completed_at": NOW,
            "metadata": {
                "provider_scope_coverage": {
                    "provider_identity_complete": True,
                },
            },
        },
        resource_rows=(
            {
                "resource_id": "resource-a",
                "resource_type": "compute.vm",
                "props": {"state": "ready"},
                "provider_ref": "provider/resource-a",
                "last_seen": NOW,
            },
            {
                "resource_id": "resource-b",
                "resource_type": "network.interface",
                "props": {},
                "provider_ref": "provider/resource-b",
                "last_seen": None,
            },
        ),
        link_rows=(
            {
                "from_id": "resource-b",
                "from_type": "network.interface",
                "link_type": "attached_to",
                "to_id": "resource-a",
                "to_type": "compute.vm",
                "props": {},
            },
        ),
        prior_manifest={
            "schema_version": "1.1.0",
            "generation": generation,
            "ontology_release_digest": "sha256:" + "a" * 64,
            "complete": True,
            "dropped_reasons": [],
            "object_ids": ["resource-a", "resource-b"],
            "link_keys": [["resource-b", "attached_to", "resource-a"]],
        },
    )

    metadata = observation.links[0].observation_metadata
    assert metadata is not None
    assert metadata.verified is True
    assert metadata.verification_method == "deterministic-cross-check"
    assert metadata.inventory_generation == generation
    assert metadata.state_fact.source_identity == "inventory-snapshot"
    assert observation.relationship_drops == ()


@pytest.mark.parametrize(
    ("provider_complete", "manifest_complete", "link_key", "extra_field", "message"),
    [
        (False, True, ["resource-a", "depends_on", "resource-b"], False, "provider identity"),
        (True, False, ["resource-a", "depends_on", "resource-b"], False, "manifest is incomplete"),
        (True, True, ["resource-b", "depends_on", "resource-a"], False, "relationship identities"),
        (True, True, ["resource-a", "depends_on", "resource-b"], True, "manifest shape"),
    ],
)
def test_active_snapshot_bootstrap_rejects_incomplete_legacy_evidence(
    provider_complete: bool,
    manifest_complete: bool,
    link_key: list[str],
    extra_field: bool,
    message: str,
) -> None:
    prior_manifest = {
        "schema_version": "1.1.0",
        "generation": "snapshot-legacy",
        "ontology_release_digest": "sha256:" + "a" * 64,
        "complete": manifest_complete,
        "dropped_reasons": [],
        "object_ids": ["resource-a", "resource-b"],
        "link_keys": [link_key],
    }
    if extra_field:
        prior_manifest["unexpected"] = True
    with pytest.raises(ValueError, match=message):
        build_active_snapshot_observation(
            snapshot={
                "id": "snapshot-legacy",
                "completed_at": NOW,
                "metadata": {
                    "provider_scope_coverage": {
                        "provider_identity_complete": provider_complete,
                    },
                },
            },
            resource_rows=(
                {
                    "resource_id": "resource-a",
                    "resource_type": "compute.vm",
                    "props": {},
                    "provider_ref": None,
                    "last_seen": NOW,
                },
                {
                    "resource_id": "resource-b",
                    "resource_type": "compute.vm",
                    "props": {},
                    "provider_ref": None,
                    "last_seen": NOW,
                },
            ),
            link_rows=(
                {
                    "from_id": "resource-a",
                    "from_type": "compute.vm",
                    "link_type": "depends_on",
                    "to_id": "resource-b",
                    "to_type": "compute.vm",
                    "props": {},
                },
            ),
            prior_manifest=prior_manifest,
        )


async def test_active_projection_replay_accepts_only_the_explicit_legacy_bootstrap_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = "snapshot-bootstrap"
    record = _projection_record(generation, "resource-a")
    snapshot = {
        "id": generation,
        "completed_at": NOW,
        "metadata": {
            "projection_complete": True,
            "relationship_drop_classifications": [],
            "relationship_coverage": {
                "total_candidates": 0,
                "materialized": 0,
                "reviewed_unavailable": 0,
                "unclassified": 0,
                "complete": True,
            },
        },
    }
    manifest = {
        "generation": generation,
        "object_content": [{"id": "resource-a", "properties": {"properties": {}}}],
        "link_content": [],
        "dropped_reasons": [],
    }
    state = {
        "journal_high_watermark": 7,
        "ontology_projection_watermark": 0,
        "ontology_generation": None,
    }

    class _ReplayConnection(_Connection):
        async def execute(self, query: str, params: object = None) -> _Cursor:
            self.executions.append(query)
            if "FROM inventory_active" in query:
                return _Cursor([snapshot])
            if "FROM inventory_observation_journal" in query:
                return _Cursor([{"record": True}])
            if "key='inventory-ontology:manifest'" in query:
                return _Cursor([{"value": manifest}])
            if "SELECT value FROM state_kv" in query:
                return _Cursor([{"value": state}])
            return _Cursor([])

    connection = _ReplayConnection({})
    journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn="postgresql://unused")
    )

    async def connect(_self: object) -> _ReplayConnection:
        return connection

    journal._connect = MethodType(connect, journal)  # type: ignore[method-assign]
    monkeypatch.setattr(observation_module, "_observation", lambda _row: record)

    replay = await journal.load_active_projection_replay(
        journal_high_watermark=7,
        projection_high_watermark=7,
    )

    assert replay.observation.generation == generation
    assert replay.journal_high_watermark == 7
    assert replay.projection_high_watermark == 7

    with pytest.raises(ValueError, match="durably fenced"):
        await journal.load_active_projection_replay()


def _projection_record(generation: str, resource_id: str) -> NormalizedInventoryObservation:
    return NormalizedInventoryObservation.create(
        idempotency_key=f"projection:{resource_id}",
        subject_kind=InventoryObservationSubjectKind.OBJECT,
        observation_kind=InventoryObservationKind.FULL,
        mutation_kind=InventoryMutationKind.UPSERT,
        subject_ref=resource_id,
        subject_type="compute.vm",
        properties={"state": "ready"},
        property_mask=("state",),
        properties_complete=True,
        links_complete=True,
        tombstone_confirmed=False,
        source_identity="inventory.reconciliation",
        source_event_id=f"snapshot:{generation}",
        source_revision=generation,
        effective_at=NOW,
        observed_at=NOW,
        evidence_cutoff=NOW,
        recorded_at=NOW,
    )


def test_projection_replay_recovers_legacy_verifier_drop_counts() -> None:
    drops = projection_replay_drops(
        {
            "relationship_drop_classifications": [],
            "relationship_coverage": {
                "reviewed_unavailable": 1,
                "unclassified": 0,
            },
        },
        {"dropped_reasons": ["missing_target_endpoint"]},
    )

    assert len(drops) == 1
    assert drops[0].reason is RelationshipDropReason.MISSING_TARGET_ENDPOINT
    assert drops[0].classified_unavailable is True
