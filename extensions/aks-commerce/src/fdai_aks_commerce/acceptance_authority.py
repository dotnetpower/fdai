"""Current approval, promotion and risk readback for the exact original acceptance Action."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from fdai.agents import read_current_action_approval
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.risk_gate.authority import evaluate_execution_authority
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.shared.contracts.models import Action, CeilingRole, Mode, Rule, Tier
from fdai.shared.providers.state_store import StateStore

from fdai_aks_commerce.acceptance_material import StoredAcceptanceDispatchMaterials


class AcceptanceCurrentAuthority:
    """Read current server-owned policy and Var's immutable approval; never create authority."""

    def __init__(
        self,
        *,
        store: StateStore,
        builder: ActionBuilder,
        rule: Rule,
        risk_gate: RiskGate,
        risk_table: RiskTable,
        principal_role: CeilingRole,
        can_approve: Callable[[str, str], bool | Awaitable[bool]],
        refresh_policy: Callable[[], Awaitable[None]],
        safety_held: Callable[[], bool],
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._builder = builder
        self._rule = Rule.model_validate_json(rule.model_dump_json())
        self._risk_gate = risk_gate
        self._risk_table = risk_table
        self._principal_role = principal_role
        self._can_approve = can_approve
        self._refresh_policy = refresh_policy
        self._safety_held = safety_held
        self._clock = clock

    async def __call__(self, action: Action, context: dict[str, Any]) -> None:
        """Require the original catalog and reviewed Rule, current promotion, safety and quorum."""
        if action.action_type != "ops.scale-out" or self._rule.remediates != action.action_type:
            raise ValueError("acceptance authority requires its reviewed scale recovery Rule")
        await self._refresh_policy()
        material = await StoredAcceptanceDispatchMaterials(self._store).read(str(action.action_id))
        expected_rule = (
            "sha256:" + hashlib.sha256(self._rule.model_dump_json().encode()).hexdigest()
        )
        if (
            material is None
            or material.action_json != action.model_dump_json()
            or material.rule_digest != expected_rule
        ):
            raise ValueError("acceptance original Rule material is unavailable or changed")
        declaration = self._builder.action_types_by_name[action.action_type]
        if action.action_type_ref != self._builder._action_type_ref(
            declaration
        ) or action.citing_rules != [self._rule.id]:
            raise ValueError("acceptance original action catalog or Rule changed")
        risk = self._risk_gate.evaluate(action=action, rule=self._rule, action_type=declaration)
        decision = evaluate_execution_authority(
            tier=Tier.T0,
            action_type=declaration,
            table=self._risk_table,
            principal_role=self._principal_role,
            environment="prod",
            system_degraded=self._safety_held(),
        )
        if (
            action.mode is not Mode.ENFORCE
            or risk.effective_mode is not Mode.ENFORCE
            or risk.outcome.value not in {"auto", "hil"}
            or decision.final_level not in {AxisLevel.ENFORCE_HIL, AxisLevel.ENFORCE_AUTO}
        ):
            raise PermissionError("current acceptance risk or promotion does not permit dispatch")
        run = context["run"]
        people = await read_current_action_approval(
            store=self._store,
            action_run=run.to_dict(),
            can_approve=self._can_approve,
            clock=self._clock,
        )
        if (
            len(people) < max(decision.quorum, 2 if declaration.irreversible else 1)
            or self._safety_held()
        ):
            raise PermissionError("current acceptance human quorum or safety is unavailable")
