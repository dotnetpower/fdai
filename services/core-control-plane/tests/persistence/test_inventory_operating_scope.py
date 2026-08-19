"""Inventory graph responses consume the read-only operating-scope projection."""

from __future__ import annotations

from typing import Any

import fdai.delivery.persistence.postgres_inventory_graph_helpers as graph_helpers
import pytest
from fdai.delivery.persistence.postgres_inventory_graph_helpers import (
    _annotate_operating_scope,
    _load_operating_scope,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord


def _object(object_id: str, object_type: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(id=object_id, object_type=object_type, properties={})


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Connection:
    def __init__(self, result_sets: list[list[dict[str, Any]]]) -> None:
        self._result_sets = list(result_sets)
        self.executions: list[tuple[str, object]] = []

    async def execute(self, query: str, params: object) -> _Cursor:
        self.executions.append((query, params))
        return _Cursor(self._result_sets.pop(0))


def test_inventory_resources_receive_reviewed_service_or_unknown_marker() -> None:
    resources = [{"id": "resource:mapped"}, {"id": "resource:unmapped"}]
    annotated, summary = _annotate_operating_scope(
        resources,
        source_revision="snapshot:one",
        objects=(
            _object("service:checkout", "BusinessService"),
            _object("workload:api", "Workload"),
        ),
        links=(
            OntologyLinkRecord(
                from_id="service:checkout",
                link_type="implemented_by",
                to_id="workload:api",
            ),
            OntologyLinkRecord(
                from_id="workload:api",
                link_type="workload_runs_on",
                to_id="resource:mapped",
            ),
        ),
    )

    assert annotated == [
        {"id": "resource:mapped", "service_ref": "service:checkout"},
        {"id": "resource:unmapped", "service_ref": "unknown_service"},
    ]
    assert summary == {
        "source_revision": "snapshot:one",
        "input_complete": True,
        "complete": False,
        "resource_count": 2,
        "mapped_resource_count": 1,
        "unmapped_resource_count": 1,
    }


def test_conflicting_services_remain_unknown() -> None:
    annotated, _summary = _annotate_operating_scope(
        [{"id": "resource:shared"}],
        source_revision="snapshot:two",
        objects=(
            _object("service:a", "BusinessService"),
            _object("service:b", "BusinessService"),
            _object("workload:api", "Workload"),
        ),
        links=(
            OntologyLinkRecord("implemented_by", "service:a", "workload:api"),
            OntologyLinkRecord("implemented_by", "service:b", "workload:api"),
            OntologyLinkRecord("workload_runs_on", "workload:api", "resource:shared"),
        ),
    )

    assert annotated[0]["service_ref"] == "unknown_service"


async def test_loader_reads_only_paths_ending_at_response_resources() -> None:
    connection = _Connection(
        [
            [
                {
                    "link_type": "workload_runs_on",
                    "from_id": "workload:api",
                    "to_id": "resource:one",
                }
            ],
            [
                {
                    "link_type": "implemented_by",
                    "from_id": "service:checkout",
                    "to_id": "workload:api",
                }
            ],
            [
                {"id": "service:checkout", "object_type": "BusinessService", "revision": 2},
                {"id": "workload:api", "object_type": "Workload", "revision": 3},
            ],
        ]
    )

    objects, links, complete = await _load_operating_scope(
        connection,  # type: ignore[arg-type]
        ("resource:one",),
    )

    assert complete is True
    assert [(item.id, item.object_type, item.revision) for item in objects] == [
        ("service:checkout", "BusinessService", 2),
        ("workload:api", "Workload", 3),
    ]
    assert [(item.link_type, item.from_id, item.to_id) for item in links] == [
        ("implemented_by", "service:checkout", "workload:api"),
        ("workload_runs_on", "workload:api", "resource:one"),
    ]
    assert "to_id=ANY" in connection.executions[0][0]
    assert connection.executions[0][1] == (["resource:one"], 200_001)


async def test_loader_reports_truncation_without_partial_service_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph_helpers, "_MAX_OPERATING_SCOPE_LINKS", 1)
    connection = _Connection(
        [
            [
                {
                    "link_type": "workload_runs_on",
                    "from_id": "workload:a",
                    "to_id": "resource:one",
                },
                {
                    "link_type": "workload_runs_on",
                    "from_id": "workload:b",
                    "to_id": "resource:one",
                },
            ]
        ]
    )

    objects, links, complete = await _load_operating_scope(
        connection,  # type: ignore[arg-type]
        ("resource:one",),
    )

    assert (objects, links, complete) == ((), (), False)
    assert len(connection.executions) == 1
