"""Translate bounded ontology resource identities for Azure metric reads."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from fdai.core.ontology_platform.metric_semantics import (
    MetricSemanticDefinition,
    MetricWindow,
    MetricWindowProvider,
)

_LOGICAL_RESOURCE = re.compile(
    r"^scope-[a-f0-9]{16}/resource-group/"
    r"(?P<group>[A-Za-z0-9._()-]{1,90})/providers/"
    r"(?P<provider>[A-Za-z0-9._()/-]{3,512})$"
)


@dataclass(frozen=True, slots=True)
class AzureMetricWindowConfig:
    """Server-owned subscription scope for ontology-bound Azure metrics."""

    subscription_id: str

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.subscription_id))
        except (AttributeError, ValueError) as exc:
            raise ValueError("subscription_id MUST be a canonical UUID") from exc
        if canonical != self.subscription_id.casefold():
            raise ValueError("subscription_id MUST be a canonical UUID")


class AzureMetricWindowProvider:
    """Read Azure metrics without exposing provider scope in ontology results."""

    def __init__(
        self,
        *,
        provider: MetricWindowProvider,
        config: AzureMetricWindowConfig,
    ) -> None:
        self._provider: Final = provider
        self._config: Final = config

    async def read(
        self,
        *,
        definition: MetricSemanticDefinition,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> MetricWindow:
        arm_id = azure_arm_resource_id(
            resource_id,
            subscription_id=self._config.subscription_id,
        )
        result = await self._provider.read(
            definition=definition,
            resource_id=arm_id,
            start=start,
            end=end,
        )
        if result.resource_id != arm_id:
            raise ValueError("Azure metric provider widened the exact resource identity")
        return replace(result, resource_id=resource_id)


def azure_arm_resource_id(resource_id: str, *, subscription_id: str) -> str:
    folded = resource_id.casefold().rstrip("/")
    arm_prefix = f"/subscriptions/{subscription_id.casefold()}/"
    if folded.startswith("/subscriptions/"):
        if not folded.startswith(arm_prefix):
            raise ValueError("Azure metric resource is outside the server subscription")
        return folded
    match = _LOGICAL_RESOURCE.fullmatch(resource_id)
    if match is None:
        raise ValueError("ontology resource identity cannot be bound to an Azure metric target")
    provider = match.group("provider")
    if "//" in provider or provider.startswith("/") or provider.endswith("/"):
        raise ValueError("ontology resource provider path is malformed")
    return (
        f"/subscriptions/{subscription_id}/resourceGroups/{match.group('group')}/"
        f"providers/{provider}"
    ).casefold()


__all__ = [
    "AzureMetricWindowConfig",
    "AzureMetricWindowProvider",
    "azure_arm_resource_id",
]
