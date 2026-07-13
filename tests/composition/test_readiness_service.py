"""Operational-readiness application-service wiring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from fdai.composition.readiness import OperationalReadinessService
from fdai.core.deploy_preflight import PreflightAnalyzer
from fdai.core.readiness import HandoffVerdict, OwnershipTransfer
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Posture:
    def __init__(self, findings: Sequence[Finding] = (), *, error: Exception | None = None) -> None:
        self._findings = tuple(findings)
        self._error = error

    async def findings_for_scope(self, scope: str) -> Sequence[Finding]:
        assert scope
        if self._error is not None:
            raise self._error
        return self._findings


class _Publisher:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.reports: list[Mapping[str, Any]] = []
        self._error = error

    async def publish_readiness_report(self, report: Mapping[str, Any]) -> None:
        if self._error is not None:
            raise self._error
        self.reports.append(report)


def _service(
    *,
    posture: _Posture | None = None,
    publisher: _Publisher | None = None,
    mode: Mode = Mode.SHADOW,
) -> tuple[OperationalReadinessService, InMemoryStateStore, _Publisher]:
    store = InMemoryStateStore()
    bound_publisher = publisher or _Publisher()
    service = OperationalReadinessService(
        posture=posture or _Posture(),
        preflight=PreflightAnalyzer((), mode=mode, clock=lambda: "ignored"),
        publisher=bound_publisher,
        state_store=store,
        mode=mode,
        clock=lambda: "2026-07-13T00:00:00Z",
    )
    return service, store, bound_publisher


def _signal() -> OwnershipTransfer:
    return OwnershipTransfer(
        scope="rg-example",
        submitter="user@example.com",
        target_environment="prod",
        correlation_id="corr-orr-1",
    )


def _audit_payloads(store: InMemoryStateStore) -> list[Mapping[str, Any]]:
    return [record["entry"] for record in store.audit_entries]


async def test_clear_review_is_audited_then_published() -> None:
    service, store, publisher = _service(mode=Mode.ENFORCE)

    report = await service.review(_signal())

    assert report.verdict is HandoffVerdict.CLEAR
    assert publisher.reports == [report.to_dict()]
    audits = _audit_payloads(store)
    assert len(audits) == 1
    audit = audits[0]
    assert audit["decision"] == "clear"
    assert audit["outcome"] == "reviewed"
    assert audit["tier"] == "t0"
    assert audit["mode"] == "enforce"
    assert store.verify_chain() is True


async def test_blocking_posture_finding_gates_enforce_handoff() -> None:
    finding = Finding(
        rule_id="managed-identity.role-assignment.over-privileged",
        resource=ResourceRef(resource_type="managed_identity", ref="id-example"),
        severity="critical",
        reason="role exceeds the approved action set",
    )
    service, store, publisher = _service(posture=_Posture((finding,)), mode=Mode.ENFORCE)

    report = await service.review(_signal())

    assert report.verdict is HandoffVerdict.BLOCKED
    assert report.blocks_handoff is True
    assert publisher.reports[0]["blocks_handoff"] is True
    assert _audit_payloads(store)[0]["decision"] == "blocked"


async def test_partial_assessment_failure_audits_abstain_and_does_not_publish() -> None:
    service, store, publisher = _service(posture=_Posture(error=RuntimeError("probe failed")))

    with pytest.raises(ExceptionGroup):
        await service.review(_signal())

    assert publisher.reports == []
    audit = _audit_payloads(store)[0]
    assert audit["decision"] == "abstain"
    assert audit["outcome"] == "assessment_failed"
    assert audit["error_type"] == "ExceptionGroup"


async def test_delivery_failure_is_audited_and_propagated() -> None:
    service, store, _ = _service(publisher=_Publisher(error=RuntimeError("delivery failed")))

    with pytest.raises(RuntimeError, match="delivery failed"):
        await service.review(_signal())

    audits = _audit_payloads(store)
    assert [entry["outcome"] for entry in audits] == [
        "reviewed",
        "delivery_failed",
    ]
    assert audits[0]["idempotency_key"] + ":delivery" == audits[1]["idempotency_key"]