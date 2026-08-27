from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.impact_analysis import (
    ChangeAssessmentService,
    ChangeAssessmentUnavailableError,
    GraphFreshnessReceipt,
    ImpactAnalyzer,
    build_graph_freshness_receipt,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

_NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
_RELEASE = "sha256:" + "a" * 64
_OBSERVED = _NOW - timedelta(minutes=5)
_RECORDED = _NOW - timedelta(minutes=4)
_VALID_UNTIL = _NOW + timedelta(hours=1)


class _Store:
    async def traverse(self, **_kwargs: object) -> OntologyGraphSnapshot:
        return OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord("resource-a", "Resource", {"id": "resource-a"}),
                OntologyObjectRecord("workload-a", "Workload", {"id": "workload-a"}),
                OntologyObjectRecord("service-a", "BusinessService", {"id": "service-a"}),
                OntologyObjectRecord("slo-a", "ServiceObjective", {"id": "slo-a"}),
            ),
            links=(
                OntologyLinkRecord("workload_runs_on", "workload-a", "resource-a"),
                OntologyLinkRecord("implemented_by", "service-a", "workload-a"),
                OntologyLinkRecord("service_has_service_objective", "service-a", "slo-a"),
            ),
            source_generation="inventory-generation-1",
        )


class _Source:
    def __init__(self, receipt: GraphFreshnessReceipt | None) -> None:
        self.receipt = receipt
        self.targets: list[str] = []

    async def resolve(self, *, target_ref: str) -> GraphFreshnessReceipt | None:
        self.targets.append(target_ref)
        return self.receipt


class _ChangingSource:
    def __init__(
        self,
        first: GraphFreshnessReceipt,
        second: GraphFreshnessReceipt,
    ) -> None:
        self._receipts = iter((first, second))

    async def resolve(self, *, target_ref: str) -> GraphFreshnessReceipt:
        del target_ref
        return next(self._receipts)


class _ProviderError(Exception):
    pass


class _FailingSource:
    async def resolve(self, *, target_ref: str) -> None:
        del target_ref
        raise _ProviderError("unavailable")


class _FailingStore:
    async def traverse(self, **_kwargs: object) -> OntologyGraphSnapshot:
        raise _ProviderError("unavailable")


def _receipt(
    *,
    ontology_release_digest: str = _RELEASE,
    target_ref: str = "resource-a",
    source_generation: str = "inventory-generation-1",
    graph_revision: str = "sha256:" + "b" * 64,
    observed_at: datetime = _OBSERVED,
    recorded_at: datetime = _RECORDED,
    valid_until: datetime = _VALID_UNTIL,
    complete: bool = True,
    truncated: bool = False,
    conflicts: tuple[str, ...] = (),
) -> GraphFreshnessReceipt:
    return build_graph_freshness_receipt(
        ontology_release_digest=ontology_release_digest,
        target_ref=target_ref,
        source_generation=source_generation,
        graph_revision=graph_revision,
        observed_at=observed_at,
        recorded_at=recorded_at,
        valid_until=valid_until,
        complete=complete,
        truncated=truncated,
        conflicts=conflicts,
    )


def _service(receipt: GraphFreshnessReceipt | None) -> ChangeAssessmentService:
    return ChangeAssessmentService(
        analyzer=ImpactAnalyzer(store=_Store()),
        graph_freshness_source=_Source(receipt),
        ontology_release_digest=_RELEASE,
        clock=lambda: _NOW,
    )


def _change(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "change-1",
        "correlation_id": "correlation-1",
        "target_ref": "resource-a",
        "occurred_at": datetime(2026, 8, 4, tzinfo=UTC).isoformat(),
        "intent_kind": "planned",
        "desired_state_digest": "sha256:desired",
        "plan_receipt_ref": "plan:1",
    }
    value.update(overrides)
    return value


async def test_complete_planned_change_is_eligible_for_later_gates() -> None:
    service = _service(_receipt())
    first = await service.assess(_change())
    second = await service.assess(_change())

    assert not first.review_required
    assert first.affected_set.all_resource_ids == ("resource-a", "workload-a")
    assert first.graph_freshness_receipt is not None
    assert (
        first.to_mapping()["graph_freshness_receipt"]["execution_authority"]  # type: ignore[index]
        is False
    )
    assert first.evidence_digest == second.evidence_digest


async def test_stale_graph_and_conflicts_require_review() -> None:
    receipt = _receipt(
        observed_at=_NOW - timedelta(days=2),
        recorded_at=_NOW - timedelta(days=2) + timedelta(minutes=1),
        valid_until=_NOW - timedelta(days=1),
        complete=False,
        conflicts=("concurrent_change",),
    )
    assessment = await _service(receipt).assess(_change())

    assert assessment.review_required
    assert assessment.reasons == (
        "concurrent_change",
        "graph_incomplete",
        "graph_stale",
    )


async def test_missing_plan_evidence_requires_review() -> None:
    assessment = await _service(_receipt()).assess(
        _change(desired_state_digest="", plan_receipt_ref="")
    )

    assert assessment.review_required
    assert assessment.reasons == (
        "desired_state_digest_missing",
        "plan_receipt_missing",
    )


async def test_affected_resource_cap_requires_review() -> None:
    source = _Source(_receipt())
    service = ChangeAssessmentService(
        analyzer=ImpactAnalyzer(store=_Store()),
        graph_freshness_source=source,
        ontology_release_digest=_RELEASE,
        clock=lambda: _NOW,
        max_affected_resources=1,
    )
    assessment = await service.assess(_change())

    assert assessment.review_required
    assert assessment.reasons == ("affected_resource_cap_exceeded",)


async def test_missing_freshness_source_can_never_clear_a_planned_change() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()), clock=lambda: _NOW)

    assessment = await service.assess(_change())

    assert assessment.review_required
    assert assessment.reasons == (
        "graph_freshness_receipt_unavailable",
        "graph_stale",
    )


@pytest.mark.parametrize(
    ("receipt", "reason"),
    [
        (_receipt(ontology_release_digest="sha256:" + "c" * 64), "graph_release_mismatch"),
        (_receipt(target_ref="resource-b"), "graph_target_mismatch"),
        (_receipt(source_generation="inventory-generation-2"), "graph_generation_mismatch"),
        (
            _receipt(
                observed_at=_NOW + timedelta(minutes=1),
                recorded_at=_NOW + timedelta(minutes=2),
                valid_until=_NOW + timedelta(hours=1),
            ),
            "graph_time_invalid",
        ),
        (
            _receipt(complete=False, truncated=True, conflicts=("inventory_truncated",)),
            "graph_truncated",
        ),
    ],
)
async def test_freshness_identity_and_completeness_fail_closed(
    receipt: GraphFreshnessReceipt,
    reason: str,
) -> None:
    assessment = await _service(receipt).assess(_change())

    assert assessment.review_required
    assert reason in assessment.reasons


def test_freshness_receipt_rejects_digest_tampering() -> None:
    with pytest.raises(ValueError, match="digest"):
        replace(_receipt(), receipt_digest="sha256:" + "f" * 64)


async def test_generation_change_during_assessment_requires_review() -> None:
    service = ChangeAssessmentService(
        analyzer=ImpactAnalyzer(store=_Store()),
        graph_freshness_source=_ChangingSource(
            _receipt(),
            _receipt(
                source_generation="inventory-generation-2",
                graph_revision="sha256:" + "c" * 64,
            ),
        ),
        ontology_release_digest=_RELEASE,
        clock=lambda: _NOW,
    )

    assessment = await service.assess(_change())

    assert assessment.review_required
    assert "graph_changed_during_assessment" in assessment.reasons


@pytest.mark.parametrize(
    ("source", "store"),
    [
        (_FailingSource(), _Store()),
        (_Source(_receipt()), _FailingStore()),
    ],
)
async def test_authoritative_provider_errors_become_explicit_unavailable(
    source: Any,
    store: Any,
) -> None:
    service = ChangeAssessmentService(
        analyzer=ImpactAnalyzer(store=store),
        graph_freshness_source=source,
        ontology_release_digest=_RELEASE,
        clock=lambda: _NOW,
        analysis_error_types=(_ProviderError,),
    )

    with pytest.raises(ChangeAssessmentUnavailableError):
        await service.assess(_change())
