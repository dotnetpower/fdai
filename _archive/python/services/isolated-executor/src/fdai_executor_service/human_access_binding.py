"""Optional human-access composition inside the already isolated effect authority boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai_service_contracts.executor import DirectApiExecutor, DirectApiReceipt, DirectApiRequest
from fdai_service_contracts.human_access import parse_human_access_role_groups
from fdai_service_contracts.human_access_execution import HUMAN_ACCESS_ACTIONS

from fdai_executor_service.human_access import IsolatedHumanAccessExecutor


def human_access_role_groups(environment: Mapping[str, str]) -> dict[str, str] | None:
    """Validate complete distinct private role groups without creating credentials or doing I/O."""
    raw = environment.get("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON", "").strip()
    if not raw:
        return None
    return parse_human_access_role_groups(raw)


def require_human_access_identity(environment: Mapping[str, str]) -> None:
    """Never share the membership writer identity with transport or cloud-resource execution."""
    identity = environment.get("FDAI_HUMAN_ACCESS_MI_CLIENT_ID", "").strip().casefold()
    if not identity or identity in {
        environment.get(key, "").strip().casefold()
        for key in (
            "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID",
            "FDAI_CHANGE_MI_CLIENT_ID",
            "FDAI_RESILIENCE_MI_CLIENT_ID",
            "FDAI_FINOPS_MI_CLIENT_ID",
            "FDAI_MI_CLIENT_ID",
        )
    }:
        raise ValueError("human access requires a distinct dedicated isolated workload identity")


@dataclass(frozen=True, slots=True)
class HumanAccessDirectApiRouter:
    """Route only the two exact membership ActionTypes; gateway identity routing is unchanged."""

    human_access: IsolatedHumanAccessExecutor
    gateway: DirectApiExecutor

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        """Dispatch through exactly one service-owned guarded provider route."""
        route = (
            self.human_access if request.action_type_name in HUMAN_ACCESS_ACTIONS else self.gateway
        )
        return await route.execute(request)

    async def operation_status(self, request: DirectApiRequest) -> DirectApiReceipt | None:
        """Recover only a durable receipt; no status path may retry the original mutation."""
        if request.action_type_name in HUMAN_ACCESS_ACTIONS:
            return await self.human_access.operation_status(request)
        reader = getattr(self.gateway, "operation_status", None)
        if reader is None:
            return None
        result: DirectApiReceipt | None = await reader(request)
        return result


__all__ = [
    "HumanAccessDirectApiRouter",
    "human_access_role_groups",
    "require_human_access_identity",
]
