from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts.inventory_progress import (
    InventoryClosureReceipt,
    InventoryProgressFractionBasis,
    InventoryProgressRecord,
    InventoryProgressStage,
    InventoryProgressState,
    inventory_closure_receipt_digest,
    inventory_progress_record_digest,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)
GENESIS_DIGEST = "sha256:" + "0" * 64


def _progress_values() -> dict[str, object]:
    return {
        "run_id": "run.abcdef",
        "attempt_id": "attempt.1",
        "sequence": 1,
        "previous_digest": GENESIS_DIGEST,
        "stage": InventoryProgressStage.COLLECT,
        "state": InventoryProgressState.RUNNING,
        "scopes_completed": 0,
        "scopes_total": 1,
        "provider_types_completed": 2,
        "provider_types_total": 8,
        "resources_observed": 20,
        "resources_expected": 100,
        "pages_completed": 2,
        "pages_expected": 8,
        "links_observed": 10,
        "unmapped_objects": 1,
        "coverage_gaps": 0,
        "started_at": NOW,
        "last_progress_at": NOW + timedelta(seconds=1),
        "deadline_at": NOW + timedelta(minutes=5),
        "fraction": 0.25,
        "fraction_basis": InventoryProgressFractionBasis.PROVIDER_TYPES,
    }


def _progress(**changes: object) -> InventoryProgressRecord:
    values = {**_progress_values(), **changes}
    return InventoryProgressRecord(
        **values,
        record_digest=inventory_progress_record_digest(**values),
    )


def _closure_values() -> dict[str, object]:
    return {
        "run_id": "run.abcdef",
        "attempt_id": "attempt.1",
        "generation_digest": "sha256:" + "1" * 64,
        "subscription_root": True,
        "resource_type_filter": False,
        "final_fence": True,
        "provider_coverage_complete": True,
        "truncated": False,
        "active_generation_matches": True,
        "overlay_open": False,
        "child_sources_complete": True,
        "observer_distinct": True,
        "resource_count": 20,
        "link_count": 10,
        "unmapped_object_count": 1,
        "coverage_gap_count": 0,
        "observed_at": NOW,
    }


def test_progress_record_is_count_only_hash_chained_and_no_authority() -> None:
    record = _progress()

    assert record.execution_authority is False
    assert record.record_digest.startswith("sha256:")
    assert "subscription" not in record.model_dump_json()
    assert "resource_id" not in record.model_dump_json()


def test_progress_record_rejects_tamper_and_counter_regression_shapes() -> None:
    with pytest.raises(ValidationError, match="digest does not match"):
        InventoryProgressRecord(
            **_progress_values(),
            record_digest="sha256:" + "f" * 64,
        )
    with pytest.raises(ValidationError, match="completed provider types"):
        _progress(provider_types_completed=9)
    with pytest.raises(ValidationError, match="completed pages"):
        _progress(pages_completed=9)


def test_progress_record_requires_explicit_failed_and_complete_shapes() -> None:
    with pytest.raises(ValidationError, match="failed stage and reason"):
        _progress(state=InventoryProgressState.FAILED, stage=InventoryProgressStage.FAILED)
    with pytest.raises(ValidationError, match="verified closure"):
        _progress(state=InventoryProgressState.COMPLETE, stage=InventoryProgressStage.COMPLETE)
    completed = _progress(
        state=InventoryProgressState.COMPLETE,
        stage=InventoryProgressStage.COMPLETE,
        scopes_completed=1,
        provider_types_completed=8,
        pages_completed=8,
        fraction=1.0,
        fraction_basis=InventoryProgressFractionBasis.VERIFIED_CLOSURE,
        generation_digest="sha256:" + "1" * 64,
    )
    assert completed.state is InventoryProgressState.COMPLETE


def test_closure_receipt_requires_every_independent_readback() -> None:
    values = _closure_values()
    receipt = InventoryClosureReceipt(
        **values,
        receipt_digest=inventory_closure_receipt_digest(**values),
    )
    assert receipt.execution_authority is False

    invalid = {**values, "overlay_open": True}
    with pytest.raises(ValidationError, match="literal_error"):
        InventoryClosureReceipt(
            **invalid,
            receipt_digest=inventory_closure_receipt_digest(**invalid),
        )
