from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.forecast_history import ForecastHistoryBinding
from fdai.core.detection.forecast_history_ingress import ProducingForecastHistoryCollector
from fdai.core.detection.forecast_history_producer import ForecastHistoryProducer
from fdai.delivery.forecast_change_history import ForecastChangeHistoryWitness
from fdai.delivery.forecast_history_readiness import forecast_history_projection
from fdai.delivery.forecast_history_sources import (
    FORECAST_ACTION_HISTORY_SOURCE_IDENTITY,
    FORECAST_ACTION_HISTORY_SOURCE_REVISION,
    FORECAST_CHANGE_HISTORY_SOURCE_IDENTITY,
    FORECAST_CHANGE_HISTORY_SOURCE_REVISION,
    FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY,
    FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION,
    IncarnationLifecycleHistorySource,
    JournalChangeHistorySource,
)
from fdai.delivery.integration_readiness import integration_projection
from fdai.delivery.persistence.postgres_forecast_lifecycle_history import (
    LifecycleIncarnationRow,
    LifecycleLedgerRead,
)
from fdai.runtime.forecast_learning import (
    build_forecast_history_collector,
    forecast_history_collector_from_environment,
)
from fdai.shared.providers.forecast_context import ForecastContextRequest

from tests.core.detection.test_forecast_history_producer import MemoryStore, binding
from tests.delivery.test_forecast_change_history import QUERY, MemoryReader, row

NOW = datetime(2026, 9, 20, tzinfo=UTC)
SCOPE = "a" * 64
ID_A, ID_B = "sha256:" + "1" * 64, "sha256:" + "2" * 64


def history(kind: str, identity: str, revision: str, **values: object) -> ForecastHistoryBinding:
    stateful = kind == "resource_lifecycle"
    return ForecastHistoryBinding.model_validate(
        {
            "kind": kind,
            "access_scope_digest": SCOPE,
            "target_ref": QUERY.subject_ref,
            "state_type": f"forecast.{kind}",
            "to_states": ["deleted", "present"] if stateful else ["changed"],
            "active_states": ["deleted"] if stateful else [],
            "source_identity": identity,
            "source_revision": revision,
            "freshness_seconds": 600,
            "lookback_seconds": 3600,
            **values,
        }
    )


async def test_journal_changes_keep_witness_provenance_and_incomplete_coverage() -> None:
    reader = MemoryReader([row(1), row(2), row(3, revision="revision-2")])
    source = JournalChangeHistorySource(
        witness=ForecastChangeHistoryWitness(reader=reader), scope_ref=QUERY.scope_ref
    )
    read = await source.read(
        subject_ref=QUERY.subject_ref, start_at=QUERY.start_at, end_at=QUERY.end_at, known_at=NOW
    )
    assert read.exhausted and {item.source_state for item in read.records} == {"full:upsert"}
    assert [item.evidence_ref for item in read.records] == [
        f"inventory-observation:sha256:{value:064x}" for value in (3, 2, 1)
    ]
    assert read.checkpoint.complete is False
    assert read.checkpoint.limitation == "start_checkpoint_unverified"
    changes = history(
        "changes", FORECAST_CHANGE_HISTORY_SOURCE_IDENTITY, FORECAST_CHANGE_HISTORY_SOURCE_REVISION
    )
    store = MemoryStore()
    producer = ForecastHistoryProducer(
        binding=binding("changes", **{"full:upsert": "changed"}).model_copy(
            update={"target_ref": QUERY.subject_ref}
        ),
        history=changes,
        source=source,
        store=store,
    )
    receipt = await producer.produce(
        ForecastContextRequest(SCOPE, producer.target_digest, QUERY.start_at, QUERY.end_at, NOW)
    )
    assert receipt.transition_count == 0 and not receipt.complete
    assert not store.keys
    assert receipt.limitation == "start_checkpoint_unverified"


class Ledger:
    def __init__(self, *rows: LifecycleIncarnationRow, pending: tuple[str, ...] = ()) -> None:
        self.rows, self.pending, self.truncated = rows, pending, False

    async def read_ledger(self, **_: object) -> LifecycleLedgerRead:
        return LifecycleLedgerRead(
            self.rows, self.pending, self.truncated, "inventory-incarnation-ledger:1"
        )


def incarnation(
    identity: str,
    opened: int,
    closed: int | None = None,
    *,
    closed_known: int | None = None,
    journal: bool = True,
) -> LifecycleIncarnationRow:
    at = NOW - timedelta(minutes=120)
    return LifecycleIncarnationRow(
        incarnation_id=identity,
        opened_at=at + timedelta(minutes=opened),
        opened_recorded_at=at + timedelta(minutes=opened) if journal else None,
        opening_observation_id="sha256:" + identity[-1] * 64,
        closed_at=at + timedelta(minutes=closed) if closed is not None else None,
        closed_recorded_at=(
            at + timedelta(minutes=closed_known if closed_known is not None else closed)
            if closed is not None
            else None
        ),
        closing_observation_id="sha256:" + "c" * 64 if closed is not None else None,
    )


async def lifecycle_read(ledger: Ledger, *, known: int = 120):  # type: ignore[no-untyped-def]
    start = NOW - timedelta(minutes=90)
    return await IncarnationLifecycleHistorySource(reader=ledger).read(
        subject_ref="resource-example",
        start_at=start,
        end_at=NOW - timedelta(minutes=10),
        known_at=NOW - timedelta(minutes=120) + timedelta(minutes=known),
    )


async def test_confirmed_deletion_and_recreation_come_only_from_incarnation_boundaries() -> None:
    read = await lifecycle_read(Ledger(incarnation(ID_A, 0, 60), incarnation(ID_B, 80)))
    assert read.checkpoint.initial_state == "present" and read.exhausted
    assert [(item.source_state, item.source_event_id) for item in read.records] == [
        ("deleted", f"incarnation-deleted:{ID_A}"),
        ("present", f"incarnation-present:{ID_B}"),
    ]
    assert read.checkpoint.limitation == "reconciliation_checkpoint_unverified"
    unknown_closure = await lifecycle_read(Ledger(incarnation(ID_A, 0, 60, closed_known=125)))
    assert unknown_closure.records == () and unknown_closure.checkpoint.initial_state == "present"


@pytest.mark.parametrize(
    ("ledger", "token"),
    [
        (Ledger(incarnation(ID_A, 0), pending=("sha256:" + "d" * 64,)), "pending_tombstone"),
        (Ledger(incarnation(ID_A, 0, journal=False)), "lifecycle_record_time_unverified"),
    ],
)
async def test_unconfirmed_or_unplaced_lifecycle_evidence_stays_explicit(
    ledger: Ledger, token: str
) -> None:
    read = await lifecycle_read(ledger)
    assert token in (read.checkpoint.limitation or "").split("+")


async def test_lifecycle_without_a_prior_incarnation_has_no_initial_state() -> None:
    ledger = Ledger(incarnation(ID_A, 50))
    ledger.truncated = True
    read = await lifecycle_read(ledger)
    assert read.checkpoint.initial_state is None and read.exhausted is False


def _env(**values: str) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def test_settings_row_uses_runtime_validation_and_never_reports_ready() -> None:
    unset = forecast_history_projection({})
    assert unset["configured"] is False and unset["mode"] == "disabled"
    assert unset["ready"] is False and unset["available"] is False
    bindings, producers = _configuration()
    env = _env(
        FDAI_STATE_STORE_DSN="postgresql://user:secret@127.0.0.1/db",
        FDAI_FORECAST_TARGETS_JSON=json.dumps([{"target_kind": "example"}]),
        FDAI_FORECAST_HISTORY_SOURCES_JSON=json.dumps(bindings),
        FDAI_FORECAST_HISTORY_PRODUCERS_JSON=json.dumps(producers),
    )
    assert isinstance(
        build_forecast_history_collector(
            dsn=env["FDAI_STATE_STORE_DSN"],
            bindings_json=env["FDAI_FORECAST_HISTORY_SOURCES_JSON"],
            producers_json=env["FDAI_FORECAST_HISTORY_PRODUCERS_JSON"],
        ),
        ProducingForecastHistoryCollector,
    )
    opted = forecast_history_projection(env)
    assert opted["ready"] is False and opted["available"] is False
    assert opted["enabled"] is True and opted["enabled_source"] == "deployment_configuration"
    assert opted["mode"] == "shadow" and opted["reason"] == opted["unavailable_reason"]
    assert opted["scoring_authority"] is False and opted["execution_authority"] is False
    assert "secret" not in json.dumps(opted)
    assert {item["kind"]: item["bound"] for item in opted["sources"]} == {
        "actions": True,
        "changes": True,
        "excluded_windows": False,
        "resource_lifecycle": True,
    }
    assert {item["name"]: item["satisfied"] for item in opted["prerequisites"]} == {
        "FDAI_STATE_STORE_DSN": True,
        "FDAI_FORECAST_TARGETS_JSON": True,
        "FDAI_FORECAST_HISTORY_SOURCES_JSON": True,
        "FDAI_FORECAST_HISTORY_PRODUCERS_JSON": True,
        "positive_source_checkpoints": False,
        "independent_operational_proof_issuance": False,
    }
    no_targets = forecast_history_projection({**env, "FDAI_FORECAST_TARGETS_JSON": ""})
    assert no_targets["enabled"] is False and no_targets["mode"] == "disabled"
    assert no_targets["reason"] == "configuration is incomplete"
    for broken in ('[{"kind": "changes"}]', "[{"):
        invalid = forecast_history_projection(
            {**env, "FDAI_FORECAST_HISTORY_PRODUCERS_JSON": broken}
        )
        assert invalid["reason"] == "configuration is invalid" and invalid["mode"] == "disabled"
        assert not any(item["bound"] for item in invalid["sources"])
    orphan = forecast_history_projection(
        {"FDAI_FORECAST_HISTORY_PRODUCERS_JSON": json.dumps(producers)}
    )
    assert orphan["reason"] == "configuration is invalid" and orphan["enabled"] is False
    rows = {item["key"]: item for item in integration_projection(env)}
    assert rows["forecast-history"]["ready"] is False


def _mapping(kind: str, identity: str, revision: str) -> dict[str, object]:
    return history(kind, identity, revision).model_dump(mode="json")


def _producer(kind: str, mapping: dict[str, str]) -> dict[str, object]:
    return {
        "kind": kind,
        "access_scope_digest": SCOPE,
        "target_ref": QUERY.subject_ref,
        "source_scope_ref": QUERY.scope_ref,
        "subject_type": "Resource",
        "state_mapping": mapping,
    }


def _configuration() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    bindings = [
        _mapping(
            "actions",
            FORECAST_ACTION_HISTORY_SOURCE_IDENTITY,
            FORECAST_ACTION_HISTORY_SOURCE_REVISION,
        ),
        _mapping(
            "changes",
            FORECAST_CHANGE_HISTORY_SOURCE_IDENTITY,
            FORECAST_CHANGE_HISTORY_SOURCE_REVISION,
        ),
        _mapping(
            "resource_lifecycle",
            FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY,
            FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION,
        ),
        {
            **_mapping("resource_lifecycle", "source:windows", "revision-1"),
            "kind": "excluded_windows",
        },
    ]
    producers = [
        _producer("actions", {"succeeded": "changed", "failed": "changed"}),
        _producer("changes", {"full:upsert": "changed"}),
        _producer("resource_lifecycle", {"present": "present", "deleted": "deleted"}),
    ]
    return bindings, producers


def test_runtime_binds_only_reviewed_available_source_producers() -> None:
    bindings, producers = _configuration()
    collector = build_forecast_history_collector(
        dsn="postgresql://127.0.0.1/example",
        bindings_json=json.dumps(bindings),
        producers_json=json.dumps(producers),
    )
    assert isinstance(collector, ProducingForecastHistoryCollector)
    assert collector.bound_kinds() == frozenset({"actions", "changes", "resource_lifecycle"})
    environment = {"FDAI_FORECAST_HISTORY_SOURCES_JSON": json.dumps(bindings)}
    plain = forecast_history_collector_from_environment(
        dsn="postgresql://127.0.0.1/example", environment=environment
    )
    assert plain is not None and not isinstance(plain, ProducingForecastHistoryCollector)
    assert forecast_history_collector_from_environment(dsn=None, environment={}) is None
    failures = [
        ([_producer("excluded_windows", {"open": "excluded"})], "unavailable"),
        ([{**producers[0], "target_ref": "other"}], "no reviewed collector mapping"),
        ([{**producers[0], "kind": "resource_lifecycle"}], "maps outside"),
    ]
    for candidate, message in failures:
        with pytest.raises(ValueError, match=message):
            build_forecast_history_collector(
                dsn="postgresql://127.0.0.1/example",
                bindings_json=json.dumps(bindings),
                producers_json=json.dumps(candidate),
            )
    mismatched = [{**bindings[0], "source_revision": "revision-other"}, *bindings[1:]]
    with pytest.raises(ValueError, match="not the reviewed one"):
        build_forecast_history_collector(
            dsn="postgresql://127.0.0.1/example",
            bindings_json=json.dumps(mismatched),
            producers_json=json.dumps(producers[:1]),
        )
    with pytest.raises(ValueError, match="require reviewed collector"):
        build_forecast_history_collector(dsn=None, bindings_json=None, producers_json="[]")
    with pytest.raises(ValueError, match="duplicate field"):
        build_forecast_history_collector(
            dsn="postgresql://127.0.0.1/example",
            bindings_json=json.dumps(bindings),
            producers_json='[{"kind": "changes", "kind": "changes"}]',
        )
