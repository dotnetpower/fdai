from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.composition import Container
from fdai.core.assurance_twin import AbstainCode, AbstainResult, DiscoveryHandoffStatus
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.runtime.assurance_twin_query import build_assurance_twin_semantic_query

REPO_ROOT = Path(__file__).resolve().parents[4]


def _registry() -> ResourceTypeRegistry:
    path = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    return load_resource_type_registry_from_mapping(yaml.safe_load(path.read_text()))


@pytest.mark.asyncio
async def test_runtime_defaults_to_explicit_semantic_unavailable(
    container: Container,
) -> None:
    coordinator = build_assurance_twin_semantic_query(
        container,
        resource_types=_registry(),
    )

    response = await coordinator.compile("count compute.vm")

    assert isinstance(response.compiled, AbstainResult)
    assert response.compiled.code is AbstainCode.SEMANTIC_MODEL_UNAVAILABLE
    assert response.discovery_status is DiscoveryHandoffStatus.UNAVAILABLE
