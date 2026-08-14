from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fdai.core.operational_context.console_projection import project_context_snapshot
from fdai.core.operational_context.models import (
    OperationalContextEvidenceLink,
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
    SourceFreshness,
)
from fdai.shared.contracts.models import Autonomy

CUTOFF = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
RESULT_DIGEST = "sha256:" + "b" * 64


@dataclass(frozen=True)
class _Object:
    id: str


@dataclass(frozen=True)
class _Link:
    link_type: str
    from_id: str
    to_id: str


def _snapshot() -> OperationalContextSnapshot:
    link = OperationalContextEvidenceLink(
        link_type="workload_runs_on",
        from_id="workload-example",
        to_id="resource-example",
    )
    return OperationalContextSnapshot(
        snapshot_id="context-example",
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        recorded_at=CUTOFF,
        catalog_versions=(("ontology", DIGEST),),
        service_ids=(),
        workload_ids=("workload-example",),
        objective_ids=(),
        service_objective_ids=(),
        recovery_objective_ids=(),
        cost_objective_ids=(),
        constraint_ids=(),
        ownership_ids=(),
        dependency_ids=("workload-example",),
        source_freshness=(
            SourceFreshness(source="inventory", observed_at=CUTOFF, max_age_seconds=300),
        ),
        evidence_links=(link,),
        evidence_paths=(
            OperationalContextEvidencePath(
                object_id="resource-example",
                object_type="Resource",
                revision=2,
                effective_from=None,
                effective_to=None,
                provenance_refs=("inventory-generation:example",),
                links=(),
            ),
            OperationalContextEvidencePath(
                object_id="workload-example",
                object_type="Workload",
                revision=1,
                effective_from=None,
                effective_to=None,
                provenance_refs=("service-catalog:example",),
                links=(link,),
            ),
        ),
        temporal_exclusions=(),
        stale_sources=(),
        conflicts=(),
        autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )


def _secured_result(
    *,
    purpose: str = "operator_context",
    release_digest: str = DIGEST,
    cutoff: datetime = CUTOFF,
    object_ids: tuple[str, ...] = ("resource-example", "workload-example"),
) -> object:
    receipt = SimpleNamespace(
        ontology_release=SimpleNamespace(digest=release_digest),
        projected_result_digest=RESULT_DIGEST,
        purpose=purpose,
        observation_cutoff=cutoff,
        complete=True,
        truncated=False,
        truncation_reason=None,
        execution_authority=False,
    )
    graph = SimpleNamespace(
        objects=tuple(_Object(item) for item in object_ids),
        links=(_Link("workload_runs_on", "workload-example", "resource-example"),),
    )
    return SimpleNamespace(receipt=receipt, materialization=SimpleNamespace(graph=graph))


def test_projects_bounded_context_from_matching_secured_receipt() -> None:
    projection = project_context_snapshot(
        snapshot=_snapshot(),
        secured_result=_secured_result(),
        expected_purpose="operator_context",
    )

    assert projection["ontology_release_digest"] == DIGEST
    assert projection["query_result_digest"] == RESULT_DIGEST
    assert projection["complete"] is True
    assert projection["mutation_authority"] is False
    assert projection["execution_authority"] is False
    assert projection["object_count"] == 2
    assert projection["link_count"] == 1
    assert projection["evidence_paths"][1]["revision"] == 1
    assert "properties" not in projection["evidence_paths"][1]


@pytest.mark.parametrize(
    ("secured_result", "message"),
    (
        (_secured_result(purpose="other"), "purpose"),
        (_secured_result(release_digest="sha256:" + "c" * 64), "release"),
        (_secured_result(cutoff=datetime(2026, 8, 14, 0, 1, tzinfo=UTC)), "cutoff"),
        (_secured_result(object_ids=("resource-example",)), "object coverage"),
    ),
)
def test_rejects_receipt_or_coverage_mismatch(secured_result: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        project_context_snapshot(
            snapshot=_snapshot(),
            secured_result=secured_result,
            expected_purpose="operator_context",
        )
