"""LitmusChaos ChaosEngine injector and ChaosResult probe."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from fdai.delivery.chaos.chaos_mesh import _kubectl


class LitmusChaosInjector:
    """Apply one ChaosEngine and stop it through the operator contract."""

    def __init__(
        self,
        *,
        fault_type: str,
        context: str,
        engine_name: str,
        namespace: str,
        engine_yaml: str,
        kubectl: str = "kubectl",
    ) -> None:
        self._fault_type = fault_type
        self._context = context
        self._engine_name = engine_name
        self._namespace = namespace
        self._engine_yaml = engine_yaml
        self._kubectl = kubectl

    @property
    def fault_type(self) -> str:
        return self._fault_type

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await _kubectl(
            ["apply", "-f", "-"],
            context=self._context,
            kubectl=self._kubectl,
            stdin=self._engine_yaml,
        )
        if rc != 0:
            raise RuntimeError(
                f"litmus apply chaosengine/{self._engine_name} failed: {err.strip()}"
            )

    async def stop(self, *, target: str) -> None:
        await _kubectl(
            [
                "patch",
                "chaosengine",
                self._engine_name,
                "-n",
                self._namespace,
                "--type=merge",
                "-p",
                '{"spec":{"engineState":"stop"}}',
            ],
            context=self._context,
            kubectl=self._kubectl,
        )
        await _kubectl(
            [
                "delete",
                "chaosengine",
                self._engine_name,
                "-n",
                self._namespace,
                "--ignore-not-found",
                "--wait=false",
            ],
            context=self._context,
            kubectl=self._kubectl,
        )


class LitmusChaosResultProbe:
    """Observe injection from the ChaosResult target history or final verdict."""

    def __init__(
        self,
        *,
        context: str,
        engine_name: str,
        experiment_name: str,
        namespace: str,
        kubectl: str = "kubectl",
    ) -> None:
        self._context = context
        self._result_name = f"{engine_name}-{experiment_name}"
        self._namespace = namespace
        self._kubectl = kubectl

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _kubectl(
            [
                "get",
                "chaosresult",
                self._result_name,
                "-n",
                self._namespace,
                "-o",
                "json",
            ],
            context=self._context,
            kubectl=self._kubectl,
        )
        if rc != 0:
            return False
        try:
            status = json.loads(out).get("status", {})
        except json.JSONDecodeError:
            return False
        history = status.get("history", {})
        for target in history.get("targets", []):
            if str(target.get("chaosStatus", "")).lower() in {"injected", "reverted"}:
                return True
        experiment = status.get("experimentStatus", {})
        return bool(experiment.get("phase") == "Completed" and experiment.get("verdict") == "Pass")


__all__ = ["LitmusChaosInjector", "LitmusChaosResultProbe"]
