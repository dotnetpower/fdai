"""Evidence readers bind the decision functions to the runtime ontology graph."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fdai.core.ontology_platform.decision_evidence_readers import (
    ChangeRiskLookbacks,
    OntologyBlastRadiusEvidenceReader,
    OntologyChangeRiskEvidenceReader,
    OntologyCostOfDelayEvidenceReader,
)
from fdai.core.ontology_platform.decision_functions import (
    assess_blast_radius,
    assess_change_risk,
    assess_cost_of_delay,
)
from fdai.core.ontology_platform.recent_resource_changes import (
    RecentResourceChange,
    RecentResourceChangeRead,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
EARLIER = NOW - timedelta(days=1)


def _catalog():
    return load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )


def _store(**kwargs: object) -> InMemoryOntologyInstanceStore:
    catalog = _catalog()
    return InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        **kwargs,  # type: ignore[arg-type]
    )


def _metadata(*, cutoff: datetime = NOW, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "lane": StateFactLane.OBSERVED,
        "authority": StateFactAuthority.PROVIDER,
        "source_identity": "inventory-provider",
        "source_revision": "generation-1",
        "effective_at": cutoff,
        "recorded_at": cutoff,
        "evidence_cutoff": cutoff,
        "freshness_ceiling_seconds": 3600,
        "completeness": 1.0,
        "synthetic": False,
        "evidence_refs": ("inventory-generation:generation-1",),
    }
    values.update(overrides)
    return StateFactMetadata(**values).to_mapping()  # type: ignore[arg-type]


def _resource(ref: str, *, metadata: dict[str, object] | None = None) -> OntologyObjectRecord:
    properties: dict[str, object] = {"id": ref, "type": "compute"}
    if metadata is not None:
        properties["properties"] = {STATE_FACT_METADATA_PROPERTY: metadata}
    return OntologyObjectRecord(id=ref, object_type="Resource", properties=properties)


def _service(ref: str, criticality: str, **extra: object) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=ref,
        object_type="BusinessService",
        properties={
            "id": ref,
            "name": ref,
            "criticality": criticality,
            "effective_from": EARLIER - timedelta(days=30),
            "source_ref": "catalog",
            **extra,
        },
    )


def _workload(ref: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=ref,
        object_type="Workload",
        properties={
            "id": ref,
            "name": ref,
            "workload_kind": "service",
            "effective_from": EARLIER - timedelta(days=30),
            "source_ref": "catalog",
        },
    )


async def _put(store: InMemoryOntologyInstanceStore, *records: OntologyObjectRecord) -> None:
    for record in records:
        await store.upsert_object(record)


async def _link(store: InMemoryOntologyInstanceStore, kind: str, source: str, target: str) -> None:
    await store.upsert_link(OntologyLinkRecord(link_type=kind, from_id=source, to_id=target))


async def _commerce_graph(**store_kwargs: object) -> InMemoryOntologyInstanceStore:
    """db <- api <- web, each hosting one workload, web's workload backing a critical service."""

    store = _store(**store_kwargs)
    await _put(
        store,
        _resource("db", metadata=_metadata()),
        _resource("api"),
        _resource("web"),
        _workload("web-workload"),
        _service("checkout", "critical"),
    )
    await _link(store, "depends_on", "api", "db")
    await _link(store, "runtime_calls", "web", "api")
    await _link(store, "workload_runs_on", "web-workload", "web")
    await _link(store, "implemented_by", "checkout", "web-workload")
    return store


def _reader(
    store: InMemoryOntologyInstanceStore, **kwargs: object
) -> OntologyBlastRadiusEvidenceReader:
    return OntologyBlastRadiusEvidenceReader(store, clock=lambda: NOW, **kwargs)  # type: ignore[arg-type]


async def test_blast_radius_follows_dependents_and_inherits_service_criticality() -> None:
    evidence = await _reader(await _commerce_graph()).read(target_ref="db")

    assert evidence is not None
    depths = {item.resource_ref: item.depth for item in evidence.resources}
    assert depths == {"db": 0, "api": 1, "web": 2}
    criticality = {item.resource_ref: item.criticality for item in evidence.resources}
    assert criticality == {"db": "critical", "api": "critical", "web": "critical"}
    assert evidence.traversal_complete is True
    result = assess_blast_radius(evidence, target_ref="db", max_tier="critical")
    assert result["complete"] is True
    assert result["affected_count"] == 2


async def test_unmapped_resources_stay_unreviewed_and_close_the_gate() -> None:
    store = _store()
    await _put(store, _resource("solo", metadata=_metadata()))

    evidence = await _reader(store).read(target_ref="solo")

    assert evidence is not None
    assert [item.criticality for item in evidence.resources] == [None]
    result = assess_blast_radius(evidence, target_ref="solo", max_tier="high")
    assert result["tier"] == "unknown"
    assert result["gate_satisfied"] is False


async def test_unknown_target_and_non_resource_target_have_no_evidence() -> None:
    store = await _commerce_graph()

    assert await _reader(store).read(target_ref="missing") is None
    assert await _reader(store).read(target_ref="checkout") is None


async def test_expired_service_does_not_contribute_criticality() -> None:
    store = _store()
    await _put(
        store,
        _resource("db", metadata=_metadata()),
        _workload("w"),
        _service("old", "critical", effective_to=EARLIER),
    )
    await _link(store, "workload_runs_on", "w", "db")
    await _link(store, "implemented_by", "old", "w")

    evidence = await _reader(store).read(target_ref="db")

    assert evidence is not None
    assert evidence.resources[0].criticality is None


async def test_unrecognized_service_criticality_is_unreviewed() -> None:
    store = _store()
    await _put(
        store,
        _resource("db", metadata=_metadata()),
        _workload("w1"),
        _workload("w2"),
        _service("good", "low"),
        _service("odd", "unreviewed-tier"),
    )
    await _link(store, "workload_runs_on", "w1", "db")
    await _link(store, "workload_runs_on", "w2", "db")
    await _link(store, "implemented_by", "good", "w1")
    await _link(store, "implemented_by", "odd", "w2")

    evidence = await _reader(store).read(target_ref="db")

    assert evidence is not None
    assert evidence.resources[0].criticality is None


async def test_a_dependent_without_any_reviewed_service_stays_unreviewed() -> None:
    store = await _commerce_graph()
    await _put(store, _resource("batch"))
    await _link(store, "depends_on", "batch", "db")

    evidence = await _reader(store).read(target_ref="db")

    assert evidence is not None
    criticality = {item.resource_ref: item.criticality for item in evidence.resources}
    assert criticality["batch"] is None
    assert criticality["db"] == "critical"
    assert assess_blast_radius(evidence, target_ref="db", max_tier="high")["tier"] == "unknown"


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        _metadata(cutoff=NOW - timedelta(hours=2)),
        _metadata(synthetic=True),
        _metadata(completeness=0.5),
        _metadata(conflicts=("equal_time_conflict",)),
    ],
)
async def test_unobserved_stale_synthetic_or_conflicted_graph_is_incomplete(
    metadata: dict[str, object] | None,
) -> None:
    store = _store()
    await _put(store, _resource("db", metadata=metadata), _workload("w"), _service("s", "low"))
    await _link(store, "workload_runs_on", "w", "db")
    await _link(store, "implemented_by", "s", "w")

    evidence = await _reader(store).read(target_ref="db")

    assert evidence is not None
    assert evidence.traversal_complete is False
    result = assess_blast_radius(evidence, target_ref="db", max_tier="high")
    assert result["gate_satisfied"] is False


async def test_incomplete_source_and_depth_limit_close_the_traversal() -> None:
    incomplete = await _commerce_graph(source_complete=False)
    evidence = await _reader(incomplete).read(target_ref="db")
    assert evidence is not None and evidence.traversal_complete is False

    store = await _commerce_graph()
    shallow = await _reader(store, max_depth=1).read(target_ref="db")
    assert shallow is not None
    assert {item.resource_ref for item in shallow.resources} == {"db", "api"}
    assert shallow.traversal_complete is False


def test_blast_radius_reader_rejects_out_of_bound_configuration() -> None:
    store = _store()
    with pytest.raises(ValueError, match="max_depth"):
        OntologyBlastRadiusEvidenceReader(store, max_depth=6)
    with pytest.raises(ValueError, match="limits"):
        OntologyBlastRadiusEvidenceReader(store, resource_limit=1_001)


class _Windows:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.calls: list[tuple[str, datetime]] = []

    async def is_active(self, *, target_ref: str, at: datetime) -> bool:
        self.calls.append((target_ref, at))
        return self.active


class _Changes:
    def __init__(self, read: RecentResourceChangeRead) -> None:
        self.read = read
        self.windows: list[tuple[datetime, datetime]] = []

    async def read_recent_resource_changes(
        self, *, start_at: datetime, end_at: datetime, known_at: datetime, limit: int
    ) -> RecentResourceChangeRead:
        del known_at, limit
        self.windows.append((start_at, end_at))
        return self.read

    async def read_recent_resource_change_page(self, **_: object) -> object:
        raise AssertionError("paging is not used")


def _change(ref: str, status: str | None) -> RecentResourceChange:
    return RecentResourceChange(
        subject_ref=ref,
        subject_name=None,
        subject_type="compute",
        operation="write",
        operation_status=status,
        mutation_kind="update",
        observation_kind="activity",
        occurred_at=EARLIER,
        source_identity="source",
        evidence_ref="evidence",
    )


def _plan(ref: str, **overrides: object) -> OntologyObjectRecord:
    properties: dict[str, object] = {
        "id": ref,
        "strategy": "rollback",
        "status": "ready",
        "workflow_ref": "wf@1.0.0",
        "action_type_refs": ["ops.scale-in@1.0.0"],
        "compensation_order": ["a"],
        "impact_envelope_id": "envelope",
        "recovery_objective_ref": "objective",
        "verification_probes": ["target_healthy"],
        "last_rehearsed_at": EARLIER,
        "expires_at": NOW + timedelta(days=5),
    }
    properties.update(overrides)
    return OntologyObjectRecord(id=ref, object_type="RecoveryPlan", properties=properties)


def _action_run(ref: str, **overrides: object) -> OntologyObjectRecord:
    properties: dict[str, object] = {
        "id": ref,
        "action_type_ref": "ops.scale-in",
        "action_type_version": "1.0.0",
        "target_ref": "db",
        "status": "dispatched",
        "mode": "shadow",
        "idempotency_key": ref,
        "started_at": EARLIER,
        "ended_at": EARLIER,
    }
    properties.update(overrides)
    properties = {key: value for key, value in properties.items() if value is not None}
    return OntologyObjectRecord(id=ref, object_type="ActionRun", properties=properties)


def _risk_reader(
    store: InMemoryOntologyInstanceStore,
    *,
    windows: _Windows | None = None,
    changes: _Changes | None = None,
    **kwargs: object,
) -> OntologyChangeRiskEvidenceReader:
    return OntologyChangeRiskEvidenceReader(
        store,
        blast_radius=_reader(store),
        change_windows=windows or _Windows(True),
        recent_changes=changes
        if changes is not None
        else _Changes(RecentResourceChangeRead((), True)),
        clock=lambda: NOW,
        **kwargs,  # type: ignore[arg-type]
    )


async def _safe_graph() -> InMemoryOntologyInstanceStore:
    store = _store()
    await _put(
        store,
        _resource("db", metadata=_metadata()),
        _workload("w"),
        _service("s", "low"),
        _plan("plan-1"),
        _action_run("run-1"),
    )
    await _link(store, "workload_runs_on", "w", "db")
    await _link(store, "implemented_by", "s", "w")
    await _link(store, "recovery_targets_resource", "plan-1", "db")
    return store


async def test_change_risk_observes_every_factor_from_real_sources() -> None:
    windows = _Windows(True)
    changes = _Changes(RecentResourceChangeRead((_change("db", "Succeeded"),), True))
    evidence = await _risk_reader(await _safe_graph(), windows=windows, changes=changes).read(
        target_ref="db"
    )

    assert evidence is not None
    assert evidence.blast_radius_tier == "low"
    assert evidence.change_window_active is True
    assert evidence.recent_failed_changes == 0
    assert evidence.rollback_tested is True
    assert evidence.dry_run_passed is True
    assert windows.calls == [("db", NOW)]
    assert changes.windows == [(NOW - timedelta(days=7), NOW)]
    assert assess_change_risk(evidence, target_ref="db", max_tier="low")["gate_satisfied"] is True


async def test_failed_latest_change_counts_and_other_targets_do_not() -> None:
    changes = _Changes(
        RecentResourceChangeRead((_change("DB", "Failed"), _change("other", "Failed")), True)
    )

    evidence = await _risk_reader(await _safe_graph(), changes=changes).read(target_ref="db")

    assert evidence is not None and evidence.recent_failed_changes == 1


async def test_missing_or_incomplete_change_feed_is_unobserved() -> None:
    store = await _safe_graph()
    incomplete = _Changes(RecentResourceChangeRead((), False, limitation="bounded"))
    for changes in (incomplete,):
        evidence = await _risk_reader(store, changes=changes).read(target_ref="db")
        assert evidence is not None and evidence.recent_failed_changes is None
    absent = OntologyChangeRiskEvidenceReader(
        store, blast_radius=_reader(store), change_windows=_Windows(True), clock=lambda: NOW
    )
    unbound = await absent.read(target_ref="db")
    assert unbound is not None and unbound.recent_failed_changes is None
    assert assess_change_risk(unbound, target_ref="db", max_tier="high")["tier"] == "unknown"


@pytest.mark.parametrize(
    "plan_overrides",
    [
        {"status": "stale"},
        {"last_rehearsed_at": NOW - timedelta(days=90)},
        {"expires_at": NOW - timedelta(seconds=1)},
    ],
)
async def test_stale_or_unready_recovery_plan_is_not_a_tested_rollback(
    plan_overrides: dict[str, object],
) -> None:
    store = await _safe_graph()
    await _put(store, _plan("plan-1", **plan_overrides))

    evidence = await _risk_reader(store).read(target_ref="db")

    assert evidence is not None and evidence.rollback_tested is False


@pytest.mark.parametrize(
    "run_overrides",
    [
        {"mode": "enforce"},
        {"status": "failed"},
        {"status": "abstained_precondition"},
        {"ended_at": NOW - timedelta(days=90)},
        {"ended_at": None},
    ],
)
async def test_only_a_recent_accepted_shadow_run_counts_as_a_dry_run(
    run_overrides: dict[str, object],
) -> None:
    store = await _safe_graph()
    await _put(store, _action_run("run-1", **run_overrides))

    evidence = await _risk_reader(store).read(target_ref="db")

    assert evidence is not None and evidence.dry_run_passed is False


async def test_risk_lookbacks_must_be_positive() -> None:
    with pytest.raises(ValueError, match="look-back"):
        ChangeRiskLookbacks(dry_run=timedelta(0))
    with pytest.raises(ValueError, match="query_limit"):
        _risk_reader(_store(), query_limit=0)


def _observation(ref: str, **overrides: object) -> OntologyObjectRecord:
    properties: dict[str, object] = {
        "id": ref,
        "target_ref": "db",
        "metric": "cost",
        "value": 240.0,
        "currency": "USD",
        "period_start": NOW - timedelta(hours=24),
        "period_end": NOW - timedelta(hours=1),
        "observed_at": NOW - timedelta(minutes=30),
        "evidence_ref": f"evidence:{ref}",
        "source_revision": "r1",
        "source_authority_ref": "authority",
        "complete": True,
        "synthetic": False,
    }
    properties.update(overrides)
    return OntologyObjectRecord(id=ref, object_type="CostObservation", properties=properties)


def _cost_reader(store: InMemoryOntologyInstanceStore) -> OntologyCostOfDelayEvidenceReader:
    return OntologyCostOfDelayEvidenceReader(
        store, metric="cost", max_observation_age=timedelta(hours=6), clock=lambda: NOW
    )


async def test_cost_basis_is_an_hourly_rate_from_the_newest_valid_observation() -> None:
    store = _store()
    await _put(
        store,
        _resource("db"),
        _observation(
            "older",
            value=1.0,
            period_end=NOW - timedelta(hours=10),
            period_start=NOW - timedelta(hours=11),
        ),
        _observation("newest"),
    )

    evidence = await _cost_reader(store).read(target_ref="db")

    assert evidence is not None
    assert evidence.hourly_cost_amount == Decimal(240) / Decimal(23)
    assert evidence.currency == "USD"
    assert evidence.basis_ref == "evidence:newest"
    priced = assess_cost_of_delay(
        evidence, target_ref="db", delay_hours=23, min_total_amount=Decimal(240)
    )
    assert priced["gate_satisfied"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"complete": False},
        {"synthetic": True},
        {"observed_at": NOW - timedelta(hours=7)},
        {"observed_at": NOW + timedelta(minutes=1)},
        {"value": -1.0},
        {"period_end": NOW - timedelta(hours=25)},
        {"metric": "other"},
    ],
)
async def test_unusable_cost_observation_leaves_the_basis_unobserved(
    overrides: dict[str, object],
) -> None:
    store = _store()
    await _put(store, _resource("db"), _observation("o", **overrides))

    evidence = await _cost_reader(store).read(target_ref="db")

    assert evidence is not None
    assert evidence.hourly_cost_amount is None and evidence.currency is None
    result = assess_cost_of_delay(
        evidence, target_ref="db", delay_hours=1, min_total_amount=Decimal(0)
    )
    assert result["gate_satisfied"] is False


async def test_cost_reader_has_no_evidence_for_an_unknown_target_or_bad_bounds() -> None:
    assert await _cost_reader(_store()).read(target_ref="missing") is None
    with pytest.raises(ValueError, match="metric"):
        OntologyCostOfDelayEvidenceReader(
            _store(), metric=" ", max_observation_age=timedelta(hours=1)
        )
    with pytest.raises(ValueError, match="bounds"):
        OntologyCostOfDelayEvidenceReader(_store(), metric="cost", max_observation_age=timedelta(0))
