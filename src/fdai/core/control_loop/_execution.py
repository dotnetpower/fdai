"""Governance, risk-authority, and executor dispatch stages."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime

from fdai.core.control_loop._helpers import (
    _unified_audit_dict,
    build_shadow_authority_audit,
    evaluate_unified,
)
from fdai.core.executor import ExecutionResult, ShadowExecutor
from fdai.core.executor.direct_api import (
    DirectApiExecutionResult,
    DirectApiShadowExecutor,
)
from fdai.core.executor.tool_call import (
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.rule_catalog.schema.assignment import (
    Assignment,
    AssignmentResolution,
    resolve_assignments,
)
from fdai.rule_catalog.schema.scope import ResourceContext
from fdai.shared.contracts.models import (
    Action,
    Event,
    ExecutionPath,
    OntologyActionType,
    Rule,
)
from fdai.shared.providers.cost_estimator import (
    CostEstimator,
    resolve_cost_impact_monthly,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.resilience import DegradationController, KillSwitch

_LOGGER = logging.getLogger("fdai.core.control_loop.orchestrator")


class ControlLoopExecutionMixin:
    """Resolve governance, execution authority, and executor selection."""

    _action_types_by_name: Mapping[str, OntologyActionType]
    _audit_store: StateStore
    _cost_estimator: CostEstimator | None
    _degradation: DegradationController | None
    _direct_api_executor: DirectApiShadowExecutor | None
    _executor: ShadowExecutor
    _governance_assignments: Iterable[Assignment]
    _inventory_age_provider: Callable[[str], Awaitable[int | None]] | None
    _kill_switch: KillSwitch | None
    _promotion_state_refresher: Callable[[str], Awaitable[None]] | None
    _risk_gate: RiskGate | None
    _risk_table: RiskTable | None
    _tool_executor: ToolCallShadowExecutor | None

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

        context = ResourceContext(
            organization=_text("organization", "tenant_id"),
            account=_text("account", "subscription_id"),
            resource_group=_text("resource_group"),
            resource_id=resource_id,
            resource_type=resource_type,
            tags={str(key): str(value) for key, value in tag_data.items()},
        )
        return resolve_assignments(
            assignments=self._governance_assignments,
            ctx=context,
            rule_id=rule_id,
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

    async def _dispatch_action(
        self, *, action: Action, rule: Rule
    ) -> ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult:
        """Route an action to the executor its ActionType declares."""
        action_type = self._action_types_by_name.get(action.action_type)
        path = action_type.execution_path if action_type is not None else None

        if path is ExecutionPath.DIRECT_API and self._direct_api_executor is not None:
            return await self._direct_api_executor.execute(action=action)
        if path is ExecutionPath.TOOL_CALL and self._tool_executor is not None:
            return await self._tool_executor.execute(action=action)
        if path in (ExecutionPath.DIRECT_API, ExecutionPath.TOOL_CALL):
            _LOGGER.warning(
                "action_type opts into %s but no matching executor is wired; "
                "falling back to PR-native (which cannot render this path)",
                path.value,
                extra={
                    "action_type": action.action_type,
                    "execution_path": path.value,
                    "idempotency_key": action.idempotency_key,
                },
            )
        return await self._executor.execute(action=action, rule=rule)

    async def _evaluate_and_audit(
        self, *, event: Event, action: Action, rule: Rule
    ) -> UnifiedRiskDecision | None:
        """Evaluate unified risk authority and append its audit row."""
        if self._risk_table is None:
            return None
        action_type = self._action_types_by_name.get(action.action_type)
        if action_type is None:
            return None
        if self._promotion_state_refresher is not None:
            await self._promotion_state_refresher(action_type.name)
        cost_override = await self._resolve_cost_override(rule=rule, action_type=action_type)
        system_degraded = (
            self._degradation is not None and not self._degradation.autonomy_permitted()
        )
        kill_switch_engaged = self._kill_switch is not None and self._kill_switch.is_engaged()
        inventory_age_seconds = None
        if self._inventory_age_provider is not None:
            try:
                inventory_age_seconds = await self._inventory_age_provider(
                    action.target_resource_ref
                )
            except Exception:  # noqa: BLE001 - freshness lookup fails closed
                _LOGGER.warning(
                    "inventory_age_lookup_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        if self._risk_gate is not None:
            unified = evaluate_unified(
                event=event,
                action=action,
                rule=rule,
                action_type=action_type,
                table=self._risk_table,
                risk_gate=self._risk_gate,
                cost_override=cost_override,
                system_degraded=system_degraded,
                kill_switch_engaged=kill_switch_engaged,
                inventory_age_seconds=inventory_age_seconds,
            )
            entry = _unified_audit_dict(event=event, action=action, unified=unified)
            entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
            await self._audit_store.append_audit_entry(entry)
            return unified
        entry = build_shadow_authority_audit(
            event=event,
            action=action,
            rule=rule,
            action_type=action_type,
            table=self._risk_table,
            cost_override=cost_override,
            system_degraded=system_degraded,
            kill_switch_engaged=kill_switch_engaged,
        )
        entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
        await self._audit_store.append_audit_entry(entry)
        return None


__all__ = ["ControlLoopExecutionMixin"]
