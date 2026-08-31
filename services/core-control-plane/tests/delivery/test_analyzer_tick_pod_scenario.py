"""Bounded Pod restart and replacement scenario through the real analyzer CLI.

The scenario declares typed Pod observations exactly as a venue does, then runs
:func:`fdai.delivery.analyzer_tick_cli.main`. Nothing here supplies a finding,
a completeness flag, or a recovery verdict: the CLI composes the production
:class:`~fdai.core.investigation.KubernetesPodLifecycleAnalyzer`, which delegates
both conclusions to the canonical reducers, so the joined receipt the CLI prints
is re-derivable from the declared observations alone.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery import analyzer_tick_cli as cli
from fdai.delivery.persistence.postgres_analyzer_publication import (
    PostgresAnalyzerPublicationLedger,
)
from fdai.shared.providers.event_bus import PublishReceipt

from tests.delivery.publication_store import ConditionalStore

# The scenario is anchored to the current tick so the CLI's own clock produces a
# bounded detection latency, exactly as a live window would.
_CUTOFF = datetime.now(tz=UTC)
_WINDOW_START = _CUTOFF - timedelta(minutes=30)
_RESTART_REF = "scenario/same-uid"
_REPLACEMENT_REF = "scenario/distinct-uid"


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
        observed_at=_CUTOFF - timedelta(minutes=10),
        created_at=_WINDOW_START - timedelta(hours=1),
        phase="Failed",
        ready=False,
        ready_container_count=0,
        restart_count=0,
        evidence_ref="pod-old",
        link_suffix="old",
    )


def _termination() -> dict[str, Any]:
    at = _CUTOFF - timedelta(minutes=5)
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
            {"observed_at": _CUTOFF.isoformat(), "desired_replicas": 1},
        ],
        "replica_history_complete": True,
        "ready_replicas": 1,
        "available_replicas": 1,
        "unavailable_replicas": 0,
        "metadata": _metadata(_CUTOFF),
        "evidence_refs": ["deployment-current"],
    }


def _recovery_pod(pod_id: str, restart_count: int) -> dict[str, Any]:
    return {
        "pod_id": pod_id,
        "phase": "Running",
        "ready": True,
        "container_count": 1,
        "ready_container_count": 1,
        "restart_count": restart_count,
        "waiting_reasons": [],
        "metadata": _metadata(_CUTOFF),
    }


def _restart_history(pod_id: str, restart_delta: int) -> dict[str, Any]:
    return {
        "pod_id": pod_id,
        "start": _WINDOW_START.isoformat(),
        "end": _CUTOFF.isoformat(),
        "restart_delta": restart_delta,
        "complete": True,
        "missing_reason": None,
        "evidence_refs": [f"restart-history:{pod_id}"],
    }


def _owner_deployment() -> dict[str, Any]:
    return {
        "deployment_id": "deployment/orders",
        "desired_replicas": 1,
        "ready_replicas": 1,
        "available_replicas": 1,
        "unavailable_replicas": 0,
        "metadata": _metadata(_CUTOFF),
    }


def _restart_evidence() -> dict[str, Any]:
    """A same-UID container restart the workload recovered from."""

    restarted = _pod(
        pod_id="pod/old",
        pod_uid="pod-uid-old",
        observed_at=_CUTOFF,
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
        "recovery_pod": _recovery_pod("pod/old", 1),
        "restart_history": _restart_history("pod/old", 1),
        "owner_deployment": _owner_deployment(),
        "correlation_window_start": _WINDOW_START.isoformat(),
        "cutoff": _CUTOFF.isoformat(),
        "graph_complete": True,
        "ownership_complete": True,
        "detected_at": (_CUTOFF - timedelta(seconds=12)).isoformat(),
    }


def _replacement_evidence() -> dict[str, Any]:
    """A distinct-UID Pod replacement under the same controller."""

    replacement = _pod(
        pod_id="pod/new",
        pod_uid="pod-uid-new",
        observed_at=_CUTOFF,
        created_at=_CUTOFF - timedelta(minutes=4),
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
        "recovery_pod": _recovery_pod("pod/new", 1),
        "restart_history": _restart_history("pod/new", 1),
        "owner_deployment": _owner_deployment(),
        "correlation_window_start": _WINDOW_START.isoformat(),
        "cutoff": _CUTOFF.isoformat(),
        "graph_complete": True,
        "ownership_complete": True,
        "detected_at": (_CUTOFF - timedelta(seconds=7)).isoformat(),
    }


class _ScenarioBus:
    """Accept every record and report a broker acknowledgement."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> PublishReceipt:
        self.published.append(payload)
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published) - 1)

    async def close(self) -> None:
        return None


@pytest.fixture
def scenario_bus(monkeypatch: pytest.MonkeyPatch) -> Iterator[_ScenarioBus]:
    """Run the real CLI composition against a local broker and ledger."""

    bus = _ScenarioBus()
    store = ConditionalStore()
    environment = {
        "FDAI_EXECUTION_VENUE": "local",
        "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
        "KAFKA_TOPIC_EVENTS": "fdai.change.events",
        "FDAI_ANALYZER_TOPIC": "fdai.change.events",
        "FDAI_ANALYZER_WINDOW_SECONDS": "300",
        "FDAI_ANALYZER_SCHEDULING_MODE": "one_shot",
        "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000000",
        "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
        "AZURE_REGION": "koreacentral",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_DATABASE": "fdai",
        "RUNTIME_ENV": "dev",
        "FDAI_ANALYZER_TARGETS": json.dumps(
            [
                {"resource_id": _RESTART_REF, "kind": "kubernetes_pod"},
                {"resource_id": _REPLACEMENT_REF, "kind": "kubernetes_pod"},
            ]
        ),
        cli.POD_EVIDENCE_JSON_ENV: json.dumps([_restart_evidence(), _replacement_evidence()]),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cli, "_build_identity", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "_build_finding_bus", lambda **kwargs: bus)
    monkeypatch.setattr(
        cli,
        "build_publication_ledger",
        lambda: PostgresAnalyzerPublicationLedger(store=store),
    )
    yield bus


def _reports(captured: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in captured.splitlines() if line.startswith('{"analyzer')]


def test_cli_emits_one_joined_receipt_derived_from_the_canonical_reducers(
    scenario_bus: _ScenarioBus,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main([])

    assert exit_code == 0
    report = _reports(capsys.readouterr().out)[-1]
    assert report["published"] == 2
    assert report["unsupported_targets"] == []
    assert report["publish_errors"] == []
    assert report["readiness"]["event_publication"] == "verified"
    assert {payload["event_type"] for payload in scenario_bus.published} == {
        "analyzer.container_restart.observed",
        "analyzer.pod_replacement.observed",
    }
    replacement = next(item for item in report["receipts"] if item["signal"] == "pod_replacement")
    assert 7.0 <= replacement.pop("detection_latency_seconds") < 60.0
    assert replacement == {
        "idempotency_key": replacement["idempotency_key"],
        "signal": "pod_replacement",
        "evidence_complete": True,
        "publication": "published",
        "recovery_closed": True,
        "evidence_refs": [
            "deployment-current",
            "kubernetes-api-inventory",
            "pod-new",
            "pod-old",
            "restart-history:pod/new",
            "termination-old",
        ],
        "assessed_by": "core.ontology_platform.kubernetes_pod_lifecycle",
        "evidence_gaps": [],
    }
    restart = next(item for item in report["receipts"] if item["signal"] == "container_restart")
    assert 12.0 <= restart["detection_latency_seconds"] < 60.0
    assert restart["evidence_complete"] is True
    assert restart["recovery_closed"] is True
    assert restart["assessed_by"] == "core.ontology_platform.kubernetes_pod_lifecycle"


def test_cli_suppresses_the_same_window_on_the_next_tick(
    scenario_bus: _ScenarioBus,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main([]) == 0
    assert cli.main([]) == 0

    first, duplicate = _reports(capsys.readouterr().out)
    assert first["published"] == 2
    assert duplicate["published"] == 0
    assert duplicate["duplicates_suppressed"] == 2
    assert len(scenario_bus.published) == 2
    assert [item["publication"] for item in duplicate["receipts"]] == [
        "duplicate_suppressed",
        "duplicate_suppressed",
    ]


def test_incomplete_recovery_evidence_never_reports_a_closed_recovery(
    scenario_bus: _ScenarioBus,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unverified = _replacement_evidence()
    unverified["restart_history"] = {
        **_restart_history("pod/new", 1),
        "restart_delta": None,
        "complete": False,
        "missing_reason": "restart_history_retention_gap",
    }
    monkeypatch.setenv(cli.POD_EVIDENCE_JSON_ENV, json.dumps([unverified]))
    monkeypatch.setenv(
        "FDAI_ANALYZER_TARGETS",
        json.dumps([{"resource_id": _REPLACEMENT_REF, "kind": "kubernetes_pod"}]),
    )

    assert cli.main([]) == 0

    receipt = _reports(capsys.readouterr().out)[-1]["receipts"][0]
    assert receipt["evidence_complete"] is False
    assert receipt["recovery_closed"] is False
    assert receipt["evidence_gaps"]
    assert receipt["publication"] == "published"


def test_unbound_pod_evidence_reports_unsupported_targets_instead_of_a_verdict(
    scenario_bus: _ScenarioBus,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(cli.POD_EVIDENCE_JSON_ENV)

    assert cli.main([]) == 0

    report = _reports(capsys.readouterr().out)[-1]
    assert report["published"] == 0
    assert report["receipts"] == []
    assert sorted(report["unsupported_targets"]) == [_REPLACEMENT_REF, _RESTART_REF]
    assert report["readiness"]["metric_access"] == "unavailable"
    assert scenario_bus.published == []


def test_malformed_pod_evidence_fails_closed_with_the_environment_key_named(
    scenario_bus: _ScenarioBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = _replacement_evidence()
    del broken["termination"]
    monkeypatch.setenv(cli.POD_EVIDENCE_JSON_ENV, json.dumps([broken]))

    with pytest.raises(ValueError, match=cli.POD_EVIDENCE_JSON_ENV):
        cli.main([])
