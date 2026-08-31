"""One pinned revision of the real Pod detection path, end to end.

Nothing here supplies a finding, a completeness flag, a recovery verdict, or a
delivery outcome. The test declares typed Kubernetes observations exactly as a
venue does and then runs the production components in order:

``StaticPodLifecycleEvidenceSource`` -> ``KubernetesPodLifecycleAnalyzer`` ->
``InvestigationCoordinator`` -> ``AnalyzerTickRunner`` (with the real durable
publication ledger) -> ``DetectionLifecycleRecorder`` -> tracked state ->
``RuntimeProjectionReader`` -> ``detection_lifecycle_projection``.

The resulting ``/detection-readiness`` lifecycle section is pinned to
``console/src/routes/fixtures/detection-lifecycle-projection.json``, which the
Console decoder test loads. Both sides therefore agree on one revision of one
contract: if the reducer, the recorder, the reader, or the Console decoder
drifts, exactly one of the two tests fails and names the drift.

Every clock is injected, so the pinned document is byte-stable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fdai.core.investigation import InvestigationCoordinator
from fdai.core.investigation.kubernetes_pod import (
    KubernetesPodLifecycleAnalyzer,
    StaticPodLifecycleEvidenceSource,
)
from fdai.delivery.analyzer_tick import AnalyzerTarget, AnalyzerTickRunner
from fdai.delivery.detection_lifecycle_state import DetectionLifecycleRecorder
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.delivery.pod_evidence_binding import (
    parse_pod_lifecycle_evidence,
)
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service.detection_lifecycle_projection import (
    detection_lifecycle_projection,
)
from fdai_operator_service.families.operations import ProjectionQuery
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)
from fdai_service_contracts import OperatorRole

_PINNED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_WINDOW_START = _PINNED_AT - timedelta(minutes=30)
_RESTART_REF = "cluster-a/default/orders"
_REPLACEMENT_REF = "cluster-a/default/payments"
_GAP_REF = "cluster-a/default/reports"
_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "console"
    / "src"
    / "routes"
    / "fixtures"
    / "detection-lifecycle-projection.json"
)


# --------------------------------------------------------------------------
# Declared Kubernetes observations - the only inputs this test authors.
# --------------------------------------------------------------------------


def _metadata(at: datetime) -> dict[str, Any]:
    return {
        "lane": "observed",
        "authority": "provider",
        "source_identity": "kubernetes-api-inventory",
        "source_revision": "resource-version-10",
        "effective_at": at.isoformat(),
        "recorded_at": at.isoformat(),
        "evidence_cutoff": at.isoformat(),
        "freshness_ceiling_seconds": 300,
        "completeness": 1.0,
        "synthetic": False,
        "conflicts": [],
        "evidence_refs": ["kubernetes-api-inventory"],
    }


def _link(at: datetime, suffix: str) -> dict[str, Any]:
    return {
        "state_fact": _metadata(at),
        "verification_method": "independent-source",
        "verified": True,
        "verifier_identity": "kubernetes-link-verifier",
        "verifier_revision": "verifier-v1",
        "verification_receipt_ref": f"link-verification:{suffix}",
        "inventory_generation": None,
        "mapping_id": None,
        "mapping_revision": None,
        "source_schema_version": None,
        "source_schema_digest": None,
    }


def _pod(
    *,
    pod_id: str,
    pod_uid: str,
    observed_at: datetime,
    created_at: datetime,
    phase: str,
    ready: bool,
    ready_container_count: int,
    restart_count: int,
    evidence_ref: str,
    link_suffix: str,
) -> dict[str, Any]:
    return {
        "pod_id": pod_id,
        "pod_uid": pod_uid,
        "cluster_id": "cluster-a",
        "namespace": "default",
        "owner_uid": "replicaset-uid-a",
        "root_controller_uid": "deployment-uid-a",
        "root_controller_kind": "Deployment",
        "owner_link": _link(observed_at, f"{link_suffix}-owner"),
        "root_controller_link": _link(observed_at, f"{link_suffix}-root"),
        "created_at": created_at.isoformat(),
        "phase": phase,
        "ready": ready,
        "container_count": 1,
        "ready_container_count": ready_container_count,
        "restart_count": restart_count,
        "waiting_reasons": [],
        "workload_revision": "revision-a",
        "metadata": _metadata(observed_at),
        "evidence_refs": [evidence_ref],
    }


def _old_pod() -> dict[str, Any]:
    return _pod(
        pod_id="pod/old",
        pod_uid="pod-uid-old",
        observed_at=_PINNED_AT - timedelta(minutes=10),
        created_at=_WINDOW_START - timedelta(hours=1),
        phase="Failed",
        ready=False,
        ready_container_count=0,
        restart_count=0,
        evidence_ref="pod-old",
        link_suffix="old",
    )


def _termination() -> dict[str, Any]:
    at = _PINNED_AT - timedelta(minutes=5)
    return {
        "pod_uid": "pod-uid-old",
        "cluster_id": "cluster-a",
        "namespace": "default",
        "event_type": "Failed",
        "reason": "OOMKilled",
        "exit_code": 137,
        "event_time": at.isoformat(),
        "recorded_at": at.isoformat(),
        "source_identity": "kubernetes-event-watch",
        "source_revision": "resource-version-20",
        "evidence_refs": ["termination-old"],
    }


def _deployment() -> dict[str, Any]:
    return {
        "deployment_id": "deployment/orders",
        "deployment_uid": "deployment-uid-a",
        "cluster_id": "cluster-a",
        "namespace": "default",
        "desired_replicas_before": 1,
        "desired_replicas_after": 1,
        "desired_replica_history": [
            {"observed_at": _WINDOW_START.isoformat(), "desired_replicas": 1},
            {"observed_at": _PINNED_AT.isoformat(), "desired_replicas": 1},
        ],
        "replica_history_complete": True,
        "ready_replicas": 1,
        "available_replicas": 1,
        "unavailable_replicas": 0,
        "metadata": _metadata(_PINNED_AT),
        "evidence_refs": ["deployment-current"],
    }


def _recovery_pod(pod_id: str, *, ready: bool = True) -> dict[str, Any]:
    return {
        "pod_id": pod_id,
        "phase": "Running" if ready else "CrashLoopBackOff",
        "ready": ready,
        "container_count": 1,
        "ready_container_count": 1 if ready else 0,
        "restart_count": 1,
        "waiting_reasons": [] if ready else ["CrashLoopBackOff"],
        "metadata": _metadata(_PINNED_AT),
    }


def _restart_history(pod_id: str, *, complete: bool = True) -> dict[str, Any]:
    return {
        "pod_id": pod_id,
        "start": _WINDOW_START.isoformat(),
        "end": _PINNED_AT.isoformat(),
        "restart_delta": 1 if complete else None,
        "complete": complete,
        "missing_reason": None if complete else "restart_history_retention_gap",
        "evidence_refs": [f"restart-history:{pod_id}"],
    }


def _owner_deployment() -> dict[str, Any]:
    return {
        "deployment_id": "deployment/orders",
        "desired_replicas": 1,
        "ready_replicas": 1,
        "available_replicas": 1,
        "unavailable_replicas": 0,
        "metadata": _metadata(_PINNED_AT),
    }


def _same_uid_restart() -> dict[str, Any]:
    """A container restarted in place; the same Pod UID kept serving."""

    restarted = _pod(
        pod_id="pod/old",
        pod_uid="pod-uid-old",
        observed_at=_PINNED_AT,
        created_at=_WINDOW_START - timedelta(hours=1),
        phase="Running",
        ready=True,
        ready_container_count=1,
        restart_count=1,
        evidence_ref="pod-old",
        link_suffix="restarted",
    )
    return {
        "resource_ref": _RESTART_REF,
        "old_pod": _old_pod(),
        "candidates": [restarted],
        "termination": _termination(),
        "deployment": _deployment(),
        "recovery_pod": _recovery_pod("pod/old"),
        "restart_history": _restart_history("pod/old"),
        "owner_deployment": _owner_deployment(),
        "correlation_window_start": _WINDOW_START.isoformat(),
        "cutoff": _PINNED_AT.isoformat(),
        "graph_complete": True,
        "ownership_complete": True,
        "detected_at": (_PINNED_AT - timedelta(seconds=12)).isoformat(),
    }


def _distinct_uid_replacement() -> dict[str, Any]:
    """The old Pod UID is gone and a new one serves under the same controller."""

    replacement = _pod(
        pod_id="pod/new",
        pod_uid="pod-uid-new",
        observed_at=_PINNED_AT,
        created_at=_PINNED_AT - timedelta(minutes=4),
        phase="Running",
        ready=True,
        ready_container_count=1,
        restart_count=1,
        evidence_ref="pod-new",
        link_suffix="new",
    )
    return {
        "resource_ref": _REPLACEMENT_REF,
        "old_pod": _old_pod(),
        "candidates": [replacement],
        "termination": _termination(),
        "deployment": _deployment(),
        "recovery_pod": _recovery_pod("pod/new"),
        "restart_history": _restart_history("pod/new"),
        "owner_deployment": _owner_deployment(),
        "correlation_window_start": _WINDOW_START.isoformat(),
        "cutoff": _PINNED_AT.isoformat(),
        "graph_complete": True,
        "ownership_complete": True,
        "detected_at": (_PINNED_AT - timedelta(seconds=7)).isoformat(),
    }


def _missed_recovery_evidence() -> dict[str, Any]:
    """The replacement is observed, but the restart window was never retained."""

    document = _distinct_uid_replacement()
    document["resource_ref"] = _GAP_REF
    document["recovery_pod"] = _recovery_pod("pod/new", ready=False)
    document["restart_history"] = _restart_history("pod/new", complete=False)
    document["detected_at"] = (_PINNED_AT - timedelta(seconds=21)).isoformat()
    return document


# --------------------------------------------------------------------------
# The production path, composed exactly once.
# --------------------------------------------------------------------------


class _ConditionalStore:
    """Compare-and-set store with the durable idempotency-store contract.

    Publication safety is a property of the record transitions, so the real
    ledger runs over this store rather than over a mock that returns verdicts.
    """

    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    async def seen(self, key: str) -> dict[str, Any] | None:
        value = self.values.get(key)
        return dict(value) if value is not None else None

    async def record(self, key: str, result: Mapping[str, Any]) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(result)
        return True

    async def remove_if(self, key: str, expected: Mapping[str, Any]) -> bool:
        if self.values.get(key) != expected:
            return False
        del self.values[key]
        return True

    async def insert_or_replace_if(
        self,
        key: str,
        expected: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> bool:
        current = self.values.get(key)
        if current is None:
            self.values[key] = dict(result)
            return True
        if current != expected and current != result:
            return False
        self.values[key] = dict(result)
        return True


class _RecordingBus:
    """Accept every record and report a broker acknowledgement."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
        self.published.append(dict(payload))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published) - 1)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        raise AssertionError("this proof never consumes")

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        raise AssertionError("this proof never dead-letters")


class _BrokerReconciler:
    """Answer from what the broker actually holds, never from a guess."""

    def __init__(self, bus: _RecordingBus) -> None:
        self._bus = bus

    async def reconcile(
        self,
        *,
        event_id: UUID,
        idempotency_key: str,
        topic: str,
    ) -> PublishReceipt | None:
        for offset, payload in enumerate(self._bus.published):
            if payload.get("event_id") == str(event_id):
                return PublishReceipt(topic=topic, partition=0, offset=offset)
        return None


class _Path:
    """One composed detection path bound to a single pinned clock."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        source = StaticPodLifecycleEvidenceSource(
            parse_pod_lifecycle_evidence(json.dumps(documents))
        )
        self.bus = _RecordingBus()
        self.ledger_store = _ConditionalStore()
        self.state_store = InMemoryStateStore()
        self.runner = AnalyzerTickRunner(
            coordinator=InvestigationCoordinator(
                analyzers=(KubernetesPodLifecycleAnalyzer(source),)
            ),
            event_bus=self.bus,
            publication_ledger=PostgresAnalyzerPublicationLedger(store=self.ledger_store),
            publication_reconciler=_BrokerReconciler(self.bus),
            window_seconds=1800,
            clock=lambda: _PINNED_AT,
        )
        self.recorder = DetectionLifecycleRecorder(self.state_store)
        self.targets = tuple(
            AnalyzerTarget(resource_ref=document["resource_ref"], resource_kind="kubernetes_pod")
            for document in documents
        )

    async def tick(self, *, at: datetime = _PINNED_AT) -> Any:
        report = await self.runner.run_once(self.targets)
        await self.recorder.record_report(report, at=at)
        return report

    async def rows(self) -> list[dict[str, Any]]:
        stored = await self.state_store.read_states(
            "runtime:detection-lifecycle:",
            limit=256,
        )
        rows: list[dict[str, Any]] = [
            {"value": dict(value), "updated_at": _PINNED_AT} for value in stored
        ]
        rows.sort(key=lambda row: str(row["value"]["resource_ref"]))
        return rows

    async def section(self, *, now: datetime = _PINNED_AT) -> dict[str, Any]:
        """Read the lifecycle section through the real Operator API reader."""

        rows = await self.rows()
        reader = RuntimeProjectionReader(
            RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
            _UnreachableFallback(),
        )

        async def fetch(_self: Any, statement: str, *params: Any) -> list[dict[str, Any]]:
            if "runtime:detection-lifecycle" in statement:
                return rows
            if "runtime:detection-readiness" in statement:
                return []
            raise AssertionError(statement)

        original = RuntimeProjectionReader._fetch_all
        RuntimeProjectionReader._fetch_all = fetch  # type: ignore[method-assign, assignment]
        try:
            payload = await reader.read(
                ProjectionQuery(
                    operation="detection.readiness",
                    principal_id="operator-a",
                    path={},
                    params={},
                    limit=100,
                    cursor=None,
                    roles=frozenset({OperatorRole.READER}),
                )
            )
        finally:
            RuntimeProjectionReader._fetch_all = original  # type: ignore[method-assign]
        section: dict[str, Any] = dict(cast(Mapping[str, Any], payload["lifecycle"]))
        if now != _PINNED_AT:
            section = dict(detection_lifecycle_projection(rows, now=now))
        return section


class _UnreachableFallback:
    async def read(self, query: ProjectionQuery) -> dict[str, Any]:
        raise AssertionError(f"unexpected fallback for {query.operation}")


def _target(section: dict[str, Any], resource_ref: str) -> dict[str, Any]:
    return next(target for target in section["targets"] if target["resource_ref"] == resource_ref)


# --------------------------------------------------------------------------
# Scenarios.
# --------------------------------------------------------------------------


async def test_a_same_uid_restart_is_reported_as_a_verified_recovery() -> None:
    path = _Path([_same_uid_restart()])

    await path.tick()
    section = await path.section()

    target = _target(section, _RESTART_REF)
    assert target["current_signal"] == "container_restart"
    assert target["current_state"] == "recovered"
    assert target["recovery_state"] == "verified"
    assert target["recovery_verified_at"] == "2026-08-31T12:00:00Z"
    assert target["failure_count"] == 1
    assert target["failures"][0]["recovery_status"] == "restart_observed_recovered"
    assert target["evidence_gaps"] == []


async def test_a_distinct_uid_replacement_is_a_different_signal_than_a_restart() -> None:
    path = _Path([_same_uid_restart(), _distinct_uid_replacement()])

    await path.tick()
    section = await path.section()

    assert _target(section, _RESTART_REF)["current_signal"] == "container_restart"
    assert _target(section, _REPLACEMENT_REF)["current_signal"] == "pod_replacement"
    assert section["counts"] == {"recovered": 2, "failing": 0, "unknown": 0}
    assert section["recovery_counts"] == {"verified": 2, "not_verified": 0, "unknown": 0}


async def test_missed_recovery_evidence_never_becomes_a_verified_recovery() -> None:
    path = _Path([_missed_recovery_evidence()])

    await path.tick()
    section = await path.section()

    target = _target(section, _GAP_REF)
    assert target["current_state"] == "unknown"
    assert target["recovery_state"] == "unknown"
    assert target["recovery_verified_at"] is None
    assert target["evidence_gaps"] == ["incomplete_evidence"]
    assert target["evidence_gap_details"] != []
    assert target["failures"][0]["evidence_complete"] is False
    assert target["failures"][0]["recovery_closed"] is False


async def test_an_expired_projection_withdraws_its_state_but_keeps_its_history() -> None:
    path = _Path([_same_uid_restart()])
    await path.tick()

    section = await path.section(now=_PINNED_AT + timedelta(hours=3))

    target = _target(section, _RESTART_REF)
    assert target["stale"] is True
    assert target["current_state"] == "unknown"
    assert target["recovery_state"] == "unknown"
    assert "stale_evidence" in target["evidence_gaps"]
    assert target["failure_count"] == 1
    assert section["failure_total"] == 1


async def test_a_repeated_tick_is_suppressed_and_counted_once() -> None:
    path = _Path([_same_uid_restart()])

    first = await path.tick()
    second = await path.tick()
    section = await path.section()

    assert first.published == 1
    assert second.published == 0
    assert second.duplicates_suppressed == 1
    assert len(path.bus.published) == 1
    target = _target(section, _RESTART_REF)
    assert target["retained_record_count"] == 1
    assert target["failure_count"] == 1
    assert target["delivery_counts"]["duplicate_suppressed"] == 1
    assert target["delivery_counts"]["published"] == 0


async def test_an_uncertain_publication_is_a_gap_until_it_is_reconciled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _Path([_same_uid_restart()])

    async def refuse(topic: str, key: str, payload: dict[str, Any]) -> PublishReceipt:
        raise TimeoutError("broker acknowledgement never arrived")

    monkeypatch.setattr(path.bus, "publish", refuse)
    await path.tick()
    uncertain = _target(await path.section(), _RESTART_REF)

    monkeypatch.undo()
    await path.tick()
    reconciled = _target(await path.section(), _RESTART_REF)

    assert uncertain["failures"][0]["publication"] == "publish_uncertain"
    assert uncertain["evidence_gaps"] == ["delivery_uncertain"]
    assert reconciled["retained_record_count"] == 1
    assert reconciled["evidence_gaps"] == []
    assert reconciled["delivery_counts"]["publish_uncertain"] == 0
    assert sum(reconciled["delivery_counts"].values()) == 1


async def test_the_operator_section_never_claims_a_cause_or_authority() -> None:
    path = _Path([_same_uid_restart(), _distinct_uid_replacement(), _missed_recovery_evidence()])

    await path.tick()
    section = await path.section()

    assert section["cause_claim_supported"] is False
    assert section["execution_authority"] is False
    encoded = json.dumps(section)
    assert "root_cause" not in encoded
    assert "remediation" not in encoded


async def test_the_console_contract_is_pinned_at_this_revision() -> None:
    """Pin the exact document the Console decoder is tested against.

    Regenerate with ``FDAI_UPDATE_DETECTION_LIFECYCLE_FIXTURE=1`` only after
    reviewing the diff: the fixture is a contract between two services, and a
    silent rewrite would let a Console assertion pass against drifted output.
    """

    import os

    path = _Path([_same_uid_restart(), _distinct_uid_replacement(), _missed_recovery_evidence()])
    await path.tick()
    section = await path.section()

    document = json.dumps(section, indent=2, sort_keys=True) + "\n"
    if os.environ.get("FDAI_UPDATE_DETECTION_LIFECYCLE_FIXTURE") == "1":
        _FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        _FIXTURE.write_text(document, encoding="utf-8")
    assert _FIXTURE.exists(), f"missing pinned Console contract at {_FIXTURE}"
    assert json.loads(_FIXTURE.read_text(encoding="utf-8")) == section
