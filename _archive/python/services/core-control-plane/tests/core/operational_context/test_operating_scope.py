"""Operating-scope coverage keeps unmapped resources explicit."""

from __future__ import annotations

import pytest
from fdai.core.operational_context import (
    UNMAPPED_SERVICE_REF,
    project_operating_scope,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.operating_model import OperatingModelSnapshot


def _object(object_id: str, object_type: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(id=object_id, object_type=object_type, properties={"id": object_id})


def _snapshot(
    objects: tuple[OntologyObjectRecord, ...],
    links: tuple[OntologyLinkRecord, ...] = (),
) -> OperatingModelSnapshot:
    return OperatingModelSnapshot(source_revision="rev-1", objects=objects, links=links)


def test_mapped_resource_reports_its_reviewed_service() -> None:
    coverage = project_operating_scope(
        _snapshot(
            (
                _object("service:checkout", "BusinessService"),
                _object("workload:api", "Workload"),
                _object("resource:vm-1", "Resource"),
            ),
            (
                OntologyLinkRecord("implemented_by", "service:checkout", "workload:api"),
                OntologyLinkRecord("workload_runs_on", "workload:api", "resource:vm-1"),
            ),
        )
    )

    assert [item.resource_id for item in coverage.resources] == ["resource:vm-1"]
    assert coverage.resources[0].service_ref == "service:checkout"
    assert coverage.resources[0].mapped is True
    assert coverage.unmapped_resource_ids == ()
    assert coverage.complete is True


def test_unmapped_resource_stays_visible_without_a_synthetic_service() -> None:
    coverage = project_operating_scope(
        _snapshot(
            (
                _object("service:checkout", "BusinessService"),
                _object("workload:api", "Workload"),
                _object("resource:vm-1", "Resource"),
                _object("resource:orphan", "Resource"),
            ),
            (
                OntologyLinkRecord("implemented_by", "service:checkout", "workload:api"),
                OntologyLinkRecord("workload_runs_on", "workload:api", "resource:vm-1"),
            ),
        )
    )

    assert [item.resource_id for item in coverage.resources] == [
        "resource:orphan",
        "resource:vm-1",
    ]
    orphan = coverage.resources[0]
    assert orphan.service_ref == UNMAPPED_SERVICE_REF
    assert orphan.service_ids == ()
    assert orphan.workload_ids == ()
    assert orphan.mapped is False
    assert coverage.unmapped_resource_ids == ("resource:orphan",)
    assert coverage.complete is False


def test_workload_without_a_service_never_becomes_a_service() -> None:
    coverage = project_operating_scope(
        _snapshot(
            (
                _object("workload:api", "Workload"),
                _object("resource:vm-1", "Resource"),
            ),
            (OntologyLinkRecord("workload_runs_on", "workload:api", "resource:vm-1"),),
        )
    )

    assert coverage.resources[0].workload_ids == ("workload:api",)
    assert coverage.resources[0].service_ids == ()
    assert coverage.resources[0].service_ref == UNMAPPED_SERVICE_REF


def test_conflicting_services_do_not_silently_pick_one() -> None:
    coverage = project_operating_scope(
        _snapshot(
            (
                _object("service:a", "BusinessService"),
                _object("service:b", "BusinessService"),
                _object("workload:api", "Workload"),
                _object("resource:vm-1", "Resource"),
            ),
            (
                OntologyLinkRecord("implemented_by", "service:a", "workload:api"),
                OntologyLinkRecord("implemented_by", "service:b", "workload:api"),
                OntologyLinkRecord("workload_runs_on", "workload:api", "resource:vm-1"),
            ),
        )
    )

    entry = coverage.resources[0]
    assert entry.service_ids == ("service:a", "service:b")
    assert entry.service_ref == UNMAPPED_SERVICE_REF
    assert entry.conflicting is True
    assert entry.mapped is False


def test_undeclared_or_wrong_typed_endpoints_never_create_a_mapping() -> None:
    coverage = project_operating_scope(
        _snapshot(
            (
                _object("service:checkout", "BusinessService"),
                _object("resource:vm-1", "Resource"),
            ),
            (
                OntologyLinkRecord("implemented_by", "service:checkout", "workload:missing"),
                OntologyLinkRecord("workload_runs_on", "workload:missing", "resource:vm-1"),
                OntologyLinkRecord("workload_runs_on", "service:checkout", "resource:vm-1"),
            ),
        )
    )

    assert coverage.resources[0].service_ref == UNMAPPED_SERVICE_REF
    assert coverage.resources[0].workload_ids == ()


def test_reserved_unmapped_marker_cannot_be_supplied_as_a_service() -> None:
    with pytest.raises(ValueError, match="reserved unmapped marker"):
        project_operating_scope(
            _snapshot(
                (
                    _object(UNMAPPED_SERVICE_REF, "BusinessService"),
                    _object("resource:vm-1", "Resource"),
                )
            )
        )
