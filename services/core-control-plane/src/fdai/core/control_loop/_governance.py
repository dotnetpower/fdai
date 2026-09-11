"""Governance assignment, override, and cost-override resolution.

Assignment and override resolution share one event-derived resource context,
so the two never disagree about the scope facts a rule was evaluated under
(rule-governance.md "Overrides - Precedence"). Resolution reads catalogs only;
it grants no execution or approval authority.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from fdai.rule_catalog.schema.assignment import (
    Assignment,
    AssignmentResolution,
    resolve_assignments,
)
from fdai.rule_catalog.schema.override import Override, resolve_override
from fdai.rule_catalog.schema.scope import ResourceContext
from fdai.shared.contracts.models import Event, OntologyActionType, Rule
from fdai.shared.providers.cost_estimator import CostEstimator, resolve_cost_impact_monthly


class ControlLoopGovernanceMixin:
    """Resolve the governance scope one rule decision is bound to."""

    _cost_estimator: CostEstimator | None
    _governance_assignments: Sequence[Assignment]
    _governance_overrides: Sequence[Override]

    def _governance_resource_context(
        self,
        *,
        event: Event,
        resource_id: str,
        resource_type: str,
    ) -> ResourceContext:
        """Build the resource hierarchy context shared by assignment and override
        resolution, so both read the same event-derived scope facts."""
        payload = event.payload
        resource = payload.get("resource")
        resource_data = resource if isinstance(resource, dict) else {}
        props = resource_data.get("props")
        props_data = props if isinstance(props, dict) else {}
        tags = props_data.get("tags")
        tag_data = tags if isinstance(tags, dict) else {}

        def _text(*keys: str) -> str:
            for key in keys:
                value = resource_data.get(key, payload.get(key))
                if isinstance(value, str) and value:
                    return value
            return ""

        return ResourceContext(
            organization=_text("organization", "tenant_id"),
            account=_text("account", "subscription_id"),
            resource_group=_text("resource_group"),
            resource_id=resource_id,
            resource_type=resource_type,
            tags={str(key): str(value) for key, value in tag_data.items()},
        )

    def _resolve_governance_assignment(
        self,
        *,
        event: Event,
        resource_id: str,
        resource_type: str,
        rule_id: str,
    ) -> AssignmentResolution | None:
        if not self._governance_assignments:
            return None
        context = self._governance_resource_context(
            event=event, resource_id=resource_id, resource_type=resource_type
        )
        return resolve_assignments(
            assignments=self._governance_assignments,
            ctx=context,
            rule_id=rule_id,
        )

    def _resolve_governance_override(
        self,
        *,
        event: Event,
        resource_id: str,
        resource_type: str,
        rule_id: str,
    ) -> Override | None:
        """Resolve the narrowest-covering override for ``rule_id`` on this
        resource "on top of" any assignment resolution
        (rule-governance.md "Overrides § Precedence").

        Uses the same event-derived :class:`ResourceContext` as
        :meth:`_resolve_governance_assignment` so scope facts never diverge
        between the two resolutions.
        """
        if not self._governance_overrides:
            return None
        context = self._governance_resource_context(
            event=event, resource_id=resource_id, resource_type=resource_type
        )
        return resolve_override(
            overrides=self._governance_overrides,
            ctx=context,
            rule_id=rule_id,
            at=datetime.now(tz=UTC),
        )

    async def _resolve_cost_override(
        self,
        *,
        rule: Rule,
        action_type: OntologyActionType,
    ) -> float | None:
        """Return the cost override for the authority pipeline."""
        if rule.remediation.cost_impact_monthly_usd is not None:
            return None
        if self._cost_estimator is None:
            return None
        return await resolve_cost_impact_monthly(self._cost_estimator, action_type, arguments=None)


__all__ = ["ControlLoopGovernanceMixin"]
