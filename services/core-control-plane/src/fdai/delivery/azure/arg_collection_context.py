"""Fingerprint the effective ARG query contract without persisting private configuration."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from fdai.delivery.inventory_collection import collection_configuration_digest

if TYPE_CHECKING:
    from .arg_query import AzureArgQueryFactory


def arg_collection_contract_digest(factory: AzureArgQueryFactory) -> str:
    configuration = asdict(factory._config)
    configuration.pop("relationship_mapping_root")
    configuration["subscription_scopes"] = sorted(factory._config.subscription_scopes)
    return collection_configuration_digest(
        {
            "schema_version": "1.0.0",
            "configuration": configuration,
            "relationships": factory._relationship_mappings.model_dump(mode="json"),
            "queries": {
                entry.id: factory._build_query(arm_type=entry.azure_arm_type)
                for entry in factory._resource_types
                if entry.azure_arm_type is not None
            },
            "coverage_query": factory._build_scope_coverage_query(),
            "unmapped_query": factory._build_unmapped_resource_query(),
        }
    )
