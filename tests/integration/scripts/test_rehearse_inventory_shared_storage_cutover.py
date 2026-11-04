"""Tests for coordinated runtime cutover qualification of inventory shared storage (#2702)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from scripts.deployment.local.rehearse_inventory_shared_storage_cutover import (
    AuditPurgePolicySpec,
    CoordinatedCutoverWindow,
    evaluate_legacy_cache_and_binary_offload,
    rehearse_inventory_shared_storage_cutover,
    require_validation_postgres_dsn,
)

NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def test_cutover_window_and_purge_policy_guards_fail_closed() -> None:
    with pytest.raises(ValueError, match="readers_stopped=True and writers_stopped=True"):
        CoordinatedCutoverWindow(
            runtime_owner="dotnetpower",
            source_revision="b5b201f4d2bf0174ca65d926d5bad251188c261a",
            target_scope="loopback-isolated-cutover-qualification",
            window_start=NOW,
            window_end=NOW + timedelta(minutes=30),
            readers_stopped=True,
            writers_stopped=False,
        )

    with pytest.raises(ValueError, match="40-character lowercase hex"):
        CoordinatedCutoverWindow(
            runtime_owner="dotnetpower",
            source_revision="not-a-git-sha",
            target_scope="loopback-isolated-cutover-qualification",
            window_start=NOW,
            window_end=NOW + timedelta(minutes=30),
            readers_stopped=True,
            writers_stopped=True,
        )

    with pytest.raises(ValueError, match="MUST be 'retain'"):
        AuditPurgePolicySpec(
            deployment_purpose="local-development-lifecycle-retention",
            observation_disposition="purge",
        )

    with pytest.raises(ValueError, match="port 5433"):
        require_validation_postgres_dsn("postgresql://localhost/fdai")
    with pytest.raises(ValueError, match="port 5433"):
        require_validation_postgres_dsn("postgresql://127.0.0.1:5432/fdai")
    assert (
        require_validation_postgres_dsn("postgresql+psycopg://127.0.0.1:5433/fdai")
        == "postgresql://127.0.0.1:5433/fdai"
    )

    zero_details = {
        "conversation_image": {"rows": 0, "payload_bytes": 0},
        "trusted_artifact": {"rows": 0, "payload_bytes": 0},
        "t2_cache": {"rows": 4, "expired_rows": 1},
        "t2_cache_legacy_default": {"rows": 0, "expired_rows": 0},
    }
    zero_eval = evaluate_legacy_cache_and_binary_offload(zero_details)
    assert zero_eval["disposition"] == "defer_retirement_and_offload_zero_measured_payloads"
    assert zero_eval["action_permitted"] is False

    nonzero_details = {
        **zero_details,
        "conversation_image": {"rows": 2, "payload_bytes": 8192},
        "t2_cache_legacy_default": {"rows": 3, "expired_rows": 1},
    }
    held_eval = evaluate_legacy_cache_and_binary_offload(nonzero_details)
    assert held_eval["disposition"] == "hold_requires_selected_rollback_and_storage_contract"
    assert held_eval["action_permitted"] is False

    eligible_eval = evaluate_legacy_cache_and_binary_offload(
        nonzero_details,
        selected_rollback_contract="contract-storage-offload-v1",
    )
    assert eligible_eval["disposition"] == "eligible_for_governed_reassessment"
    assert eligible_eval["action_permitted"] is True

    with pytest.raises(ValueError, match="is not available"):
        evaluate_legacy_cache_and_binary_offload(
            {
                **zero_details,
                "trusted_artifact": {"status": "select_permission_required"},
            }
        )
    with pytest.raises(ValueError, match="missing required cache relation"):
        evaluate_legacy_cache_and_binary_offload(
            {
                "conversation_image": {"rows": 0, "payload_bytes": 0},
                "trusted_artifact": {"rows": 0, "payload_bytes": 0},
                "t2_cache": {"rows": 0, "expired_rows": 0},
            }
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rehearse_inventory_shared_storage_cutover_satisfies_all_criteria() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    result = await rehearse_inventory_shared_storage_cutover(dsn)

    assert all(result["criteria_satisfied"].values())
    assert result["existing_conversion"] == {
        "converted_resource_rows": 48,
        "existing_body_deduplication_ratio": 3.0,
        "legacy_evidence_delete_blocked": True,
        "legacy_member_rows_retained": 48,
        "legacy_resource_rows_before": 48,
        "shared_property_bodies_after_conversion": 16,
    }
    dedup = result["prospective_deduplication"]
    assert dedup["additional_pages_on_unchanged_generations"] == 0
    assert dedup["all_generations_round_trip_verified"] is True
    assert dedup["prospective_bindings"] == 3
    assert dedup["prospective_generations"] == 3
    assert dedup["prospective_logical_members"] == 48
    assert dedup["prospective_set_deduplication_ratio"] == 3.0
    assert dedup["prospective_set_rows"] == 1
    cert = result["purge_certification"]
    assert cert["archive_verified"] is True
    assert cert["restore_certified"] is True
    assert cert["suffix_chain_verified"] is True
    assert cert["observation_rows_purged"] == 0
    assert cert["archived_prefix_rows"] == 49
    assert cert["deleted_prefix_rows"] == 49
    assert cert["retained_suffix_rows"] == 551
    assert cert["restored_total_rows"] == 600
    assert cert["restored_head_hash"] == cert["original_head_hash"]
