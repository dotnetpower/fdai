from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.persistence import postgres_ontology
from fdai.shared.providers.ontology_instance import OntologyInstanceValidationError


def test_object_row_decode_normalizes_datetime() -> None:
    record = postgres_ontology._object_from_row(  # noqa: SLF001 - persistence boundary
        {
            "id": "resource-example",
            "object_type": "Resource",
            "properties": {"observed_at": datetime(2026, 7, 31, tzinfo=UTC)},
            "revision": 1,
        }
    )

    assert record.properties["observed_at"] == "2026-07-31T00:00:00Z"


def test_link_row_decode_rejects_excessive_nesting() -> None:
    nested: object = "leaf"
    for _ in range(34):
        nested = {"next": nested}

    with pytest.raises(OntologyInstanceValidationError, match="nesting depth"):
        postgres_ontology._link_from_row(  # noqa: SLF001 - persistence boundary
            {
                "link_type": "implemented_by",
                "from_id": "service-example",
                "to_id": "workload-example",
                "properties": {"nested": nested},
            }
        )
