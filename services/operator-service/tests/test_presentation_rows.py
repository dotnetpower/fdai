"""Readable conversation rows for observed model deployments."""

from __future__ import annotations

from fdai_operator_service.families.conversation.presentation_rows import (
    ordered_columns,
    readable_row,
)


def test_model_deployment_summary_is_readable_without_raw_provider_bags() -> None:
    row = readable_row(
        {
            "id": "deployment-1",
            "object_type": "Resource",
            "properties": {
                "name": "gpt-example",
                "type": "llm-model-deployment",
                "properties": {
                    "model_name": "gpt-5.4",
                    "model_version": "2026-09-01",
                    "model_format": "OpenAI",
                    "provisioning_state": "Succeeded",
                    "sku_name": "GlobalStandard",
                    "capacity_units": 50,
                    "current_capacity_units": 40,
                    "capacity_transitioning": True,
                    "capacity_tpm": 50_000,
                    "capacity_tpm_source": "properties.rateLimits",
                    "properties": {"provider_internal": "not-presented"},
                },
            },
        }
    )

    assert row == {
        "id": "deployment-1",
        "object_type": "Resource",
        "name": "gpt-example",
        "provisioning_state": "Succeeded",
        "model_name": "gpt-5.4",
        "model_version": "2026-09-01",
        "model_format": "OpenAI",
        "sku_name": "GlobalStandard",
        "capacity_units": 50,
        "current_capacity_units": 40,
        "capacity_transitioning": True,
        "capacity_tpm": 50_000,
        "capacity_tpm_source": "properties.rateLimits",
        "type": "llm-model-deployment",
    }
    assert ordered_columns(tuple(row))[:12] == [
        "name",
        "provisioning_state",
        "model_name",
        "model_version",
        "model_format",
        "sku_name",
        "capacity_units",
        "current_capacity_units",
        "capacity_transitioning",
        "capacity_tpm",
        "capacity_tpm_source",
        "type",
    ]


def test_an_aggregate_group_keeps_its_group_fields_as_leading_columns() -> None:
    first = readable_row(
        {
            "group": {"resource_type": "Microsoft.Network/networkSecurityGroups"},
            "operation": "count",
            "value": 5,
        }
    )
    second = readable_row(
        {"group": {"resource_type": "Microsoft.KeyVault/vaults"}, "operation": "count", "value": 1}
    )

    assert first["resource_type"] == "Microsoft.Network/networkSecurityGroups"
    assert "group" not in first
    assert ordered_columns(list(first)) == ["resource_type", "operation", "value"]
    assert second["resource_type"] == "Microsoft.KeyVault/vaults"


def test_group_values_are_redacted_and_never_overwrite_the_row_own_fields() -> None:
    row = readable_row(
        {
            "group": {"resource_id": "/subscriptions/00000000/resourceGroups/rg", "value": "x"},
            "operation": "count",
            "value": 3,
        }
    )

    assert row["resource_id"] == "<redacted>"
    assert row["value"] == 3


def test_an_ungrouped_aggregate_has_no_group_column() -> None:
    row = readable_row({"group": {}, "operation": "count", "value": 25})

    assert row == {"operation": "count", "value": 25}
    assert ordered_columns(list(row)) == ["operation", "value"]


async def test_password_and_api_key_suffixes_are_redacted_and_handle_refs_deduplicate() -> None:
    from datetime import UTC, datetime, timedelta

    import pytest
    from fdai_operator_service.families.conversation.result_handles import latest_result_handle_refs
    from fdai_service_contracts import ResultHandleRef

    row = readable_row(
        {"name": "vm-1", "admin_password": "secret-password", "service_api_key": "k"}
    )
    assert row["admin_password"] == "<redacted>"
    assert row["service_api_key"] == "<redacted>"

    now = datetime(2026, 9, 27, tzinfo=UTC)
    ref = ResultHandleRef(
        handle_ref="OpaqueHandleRef0123456789abcdefABCDEF",
        key_version="v1",
        issued_at=now,
        expires_at=now + timedelta(minutes=15),
    )

    class _Store:
        async def latest_result_handle_refs(
            self, *, principal_id: str, session_id: str, limit: int = 4
        ) -> tuple[ResultHandleRef, ...]:
            del principal_id, session_id, limit
            return (ref, ref)

    assert await latest_result_handle_refs(
        _Store(), principal_id="p1", session_id="s1", limit=2
    ) == (ref,)
    assert await latest_result_handle_refs(_Store(), principal_id="  ", session_id="s1") == ()
    with pytest.raises(ValueError, match="limit MUST be"):
        await latest_result_handle_refs(_Store(), principal_id="p1", session_id="s1", limit=0)
