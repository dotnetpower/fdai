"""Read-only Thor pre-flight simulation for AKS commerce acceptance recovery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents._framework.thor_preflight import PreflightSimulationResult
from fdai.shared.contracts.models import Action

from fdai_aks_commerce.acceptance_action import AcceptanceGuardedExecutor
from fdai_aks_commerce.acceptance_material import AcceptanceDispatchMaterial


class AcceptancePreflightSimulator:
    """Validate prepared acceptance material and current evidence without applying effects."""

    def __init__(
        self,
        *,
        guard: AcceptanceGuardedExecutor,
        read_material: Callable[[str], Awaitable[AcceptanceDispatchMaterial | None]],
        check_authority: Callable[[Action, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._guard = guard
        self._read_material = read_material
        self._check_authority = check_authority

    async def simulate(self, run: ActionRun) -> PreflightSimulationResult:
        context: dict[str, Any] = {"run": run}
        try:
            await self._guard.bind(context)()
            action_id = str(run.action_id or "")
            if not action_id:
                return _failed("missing_action_id")
            material = await self._read_material(action_id)
            if material is None:
                return _failed("material_unavailable")
            await self._check_authority(material.action(), context)
        except PermissionError:
            return _failed("authority_unavailable")
        except ValueError:
            return _failed("validation_failed")
        return PreflightSimulationResult(
            outcome="passed",
            simulator_id="aks-commerce-acceptance",
            simulator_version="1",
            reason="passed",
        )


def _failed(reason: str) -> PreflightSimulationResult:
    return PreflightSimulationResult(
        outcome="failed",
        simulator_id="aks-commerce-acceptance",
        simulator_version="1",
        reason=reason,
    )


__all__ = ["AcceptancePreflightSimulator"]
