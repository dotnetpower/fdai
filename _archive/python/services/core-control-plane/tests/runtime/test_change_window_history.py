from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.runtime.change_window_history import (
    CHANGE_WINDOW_COVERAGE_PREFIX,
    CHANGE_WINDOW_HISTORY_PREFIX,
    record_change_window_history,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.operating_model import OperatingModelSnapshot
from fdai.shared.providers.testing import InMemoryStateStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def _window(window_id: str, *, start: int, end: int, status: str = "active"):
    return OntologyObjectRecord(
        id=window_id,
        object_type="ChangeWindow",
        properties={
            "id": window_id,
            "window_kind": "maintenance",
            "scope_ref": "resource-example",
            "status": status,
            "effective_from": (NOW + timedelta(minutes=start)).isoformat(),
            "effective_to": (NOW + timedelta(minutes=end)).isoformat(),
            "policy_ref": "policy:change-window",
        },
    )


async def test_change_window_history_is_append_only_and_supersedes_prior_revision() -> None:
    store = InMemoryStateStore()
    first = OperatingModelSnapshot("intent-rev-1", (_window("window-1", start=0, end=30),), ())
    second = OperatingModelSnapshot("intent-rev-2", (_window("window-1", start=5, end=35),), ())

    first_receipt = await record_change_window_history(
        store,
        first,
        document_digest="sha256:" + "1" * 64,
        recorded_at=NOW,
    )
    second_receipt = await record_change_window_history(
        store,
        second,
        document_digest="sha256:" + "2" * 64,
        recorded_at=NOW + timedelta(minutes=1),
    )

    rows, total = await store.read_state_page(
        CHANGE_WINDOW_HISTORY_PREFIX, limit=10, field="window_id", value="window-1"
    )
    assert total == 2
    assert rows[0]["source_revision"] == "intent-rev-2"
    assert rows[0]["supersedes_revision_ref"] == rows[1]["revision_ref"]
    assert first_receipt.watermark != second_receipt.watermark
    coverage, coverage_total = await store.read_state_page(CHANGE_WINDOW_COVERAGE_PREFIX, limit=10)
    assert coverage_total == 2
    assert {item["source_revision"] for item in coverage} == {"intent-rev-1", "intent-rev-2"}
