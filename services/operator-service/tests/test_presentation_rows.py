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
        "capacity_tpm": 50_000,
        "capacity_tpm_source": "properties.rateLimits",
        "type": "llm-model-deployment",
    }
    assert ordered_columns(tuple(row))[:10] == [
        "name",
        "provisioning_state",
        "model_name",
        "model_version",
        "model_format",
        "sku_name",
        "capacity_units",
        "capacity_tpm",
        "capacity_tpm_source",
        "type",
    ]
