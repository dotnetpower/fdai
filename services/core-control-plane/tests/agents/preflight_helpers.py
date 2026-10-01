from __future__ import annotations

from fdai.agents._framework import thor_preflight
from fdai.agents.thor import ActionRun


class PassingPreflightSimulator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def simulate(self, run: ActionRun) -> thor_preflight.PreflightSimulationResult:
        self.calls.append(run.action_run_identity())
        return thor_preflight.PreflightSimulationResult(
            outcome="passed",
            simulator_id="test-preflight",
            simulator_version="1",
            reason="test pass",
        )
