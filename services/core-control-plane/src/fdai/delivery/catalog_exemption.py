"""Immutable governance-catalog exemption lookup for the runtime risk gate."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fdai.rule_catalog.schema.exemption import Exemption, ExemptionState
from fdai.shared.providers.exemption import ExemptionMatch, ExemptionRegistry


class CatalogExemptionRegistry:
    """Resolve reviewed Azure-shaped exemptions without widening their scope.

    Resource-group exemptions match only when the action target is a complete
    Azure resource id carrying the same subscription and resource-group. An
    unparseable target cannot prove scope identity and therefore does not match.
    """

    def __init__(
        self,
        exemptions: tuple[Exemption, ...],
        *,
        fallback: ExemptionRegistry,
    ) -> None:
        self._exemptions = tuple(
            sorted(
                exemptions,
                # Exact-resource exemptions are narrower and therefore win
                # before resource-group exemptions; id breaks same-tier ties.
                key=lambda exemption: (
                    exemption.scope.resource_ref is None,
                    exemption.id,
                ),
            )
        )
        self._fallback = fallback

    def find_match(
        self,
        *,
        rule_id: str,
        resource_ref: str,
        resource_group: str | None = None,
        at: datetime | None = None,
    ) -> ExemptionMatch | None:
        moment = at or datetime.now(tz=UTC)
        target = _parse_azure_resource_id(resource_ref)
        for exemption in self._exemptions:
            if exemption.rule_id != rule_id or exemption.state is not ExemptionState.ACTIVE:
                continue
            if exemption.expires_at <= moment:
                continue
            scope = exemption.scope
            if scope.resource_ref is not None:
                if scope.resource_ref != resource_ref:
                    continue
                scope_summary = f"resource={scope.resource_ref}"
            else:
                if target is None or scope.resource_group is None:
                    continue
                subscription_id, target_resource_group = target
                if subscription_id != scope.subscription_id:
                    continue
                if target_resource_group.casefold() != scope.resource_group.casefold():
                    continue
                scope_summary = f"subscription={scope.subscription_id};rg={scope.resource_group}"
            return ExemptionMatch(
                exemption_id=exemption.id,
                rule_id=rule_id,
                reason=exemption.justification,
                scope_summary=scope_summary,
            )
        return self._fallback.find_match(
            rule_id=rule_id,
            resource_ref=resource_ref,
            resource_group=resource_group,
            at=moment,
        )


def _parse_azure_resource_id(resource_ref: str) -> tuple[UUID, str] | None:
    parts = resource_ref.strip("/").split("/")
    if len(parts) < 8:
        return None
    lowered = [part.casefold() for part in parts]
    if lowered[0] != "subscriptions" or lowered[2] != "resourcegroups":
        return None
    if lowered[4] != "providers":
        return None
    try:
        subscription_id = UUID(parts[1])
    except ValueError:
        return None
    resource_group = parts[3]
    if not resource_group or not parts[5] or not parts[6] or not parts[7]:
        return None
    return subscription_id, resource_group


__all__ = ["CatalogExemptionRegistry"]
