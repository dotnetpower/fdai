"""Produce Console-safe Azure provider execution receipts from registered plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai_service_contracts.discovery import (
    DiscoveryBackend,
    DiscoveryOperationProfile,
    DiscoveryQueryPlan,
    DiscoveryUniverse,
)
from fdai_service_contracts.discovery_evidence import (
    ProviderExecutionCommand,
    ProviderExecutionPreview,
    ProviderExecutionReceipt,
    ProviderExecutionResult,
    provider_execution_receipt_digest,
)

from fdai.delivery.azure.discovery_explanation import render_registered_azure_command

_PREVIEW_FIELDS = frozenset({"name", "type", "resource_group", "location", "status"})


def build_provider_execution_receipt(
    *,
    plan: DiscoveryQueryPlan,
    operation: DiscoveryOperationProfile,
    page_count: int,
    count: int,
    preview_rows: Sequence[Mapping[str, object]],
) -> ProviderExecutionReceipt:
    """Build a receipt without accepting raw argv, tokens, ids, errors, or pagination state."""

    if plan.backend not in {
        DiscoveryBackend.RESOURCE_GRAPH,
        DiscoveryBackend.GENERIC_ARM,
        DiscoveryBackend.TYPED_ARM,
        DiscoveryBackend.REGISTERED_CLI,
    }:
        raise ValueError("provider execution receipt requires an executed Azure read backend")
    rendered = render_registered_azure_command(plan=plan, operation=operation)
    preview = tuple(_preview(row) for row in preview_rows[:10])
    result = ProviderExecutionResult(
        count=count,
        preview=preview,
        truncated=count > len(preview),
    )
    command = ProviderExecutionCommand(
        label=(
            "resource_groups"
            if plan.universes == (DiscoveryUniverse.RESOURCE_CONTAINERS,)
            else "resources"
        ),
        command_id=rendered.command_id,
        command=" ".join(rendered.argv),
        result=result,
    )
    values: dict[str, object] = {
        "backend": (
            "azure_resource_graph"
            if plan.backend is DiscoveryBackend.RESOURCE_GRAPH
            else "azure_resource_manager"
        ),
        "page_count": page_count,
        "commands": (command,),
    }
    return ProviderExecutionReceipt.model_validate(
        {"receipt_digest": provider_execution_receipt_digest(**values), **values}
    )


def provider_execution_projection(receipt: ProviderExecutionReceipt) -> dict[str, object]:
    """Return the Console wire shape while retaining the digest for audit correlation."""

    return receipt.model_dump(mode="json")


def _preview(row: Mapping[str, object]) -> ProviderExecutionPreview:
    projected = {
        key: value
        for key, value in row.items()
        if key in _PREVIEW_FIELDS and isinstance(value, str) and value
    }
    return ProviderExecutionPreview.model_validate(projected)


__all__ = ["build_provider_execution_receipt", "provider_execution_projection"]
