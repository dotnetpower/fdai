"""Chaos Mesh CRD injector + probe for the enforce harness.

The SRE demo scenarios S2 / S3 / S4 inject faults with Chaos Mesh CRDs
(StressChaos / NetworkChaos / HTTPChaos) rather than a bare ``kubectl``
verb. This adapter is the delivery-layer enforce injector for that path:
``inject`` applies the CRD, ``stop`` deletes it (rollback), and the probe
reports the fault as observed once Chaos Mesh marks it ``AllInjected``.

Same discipline as :mod:`fdai.delivery.chaos.live_injectors`: subprocess
over ``kubectl`` (no SDK), never imported by ``core/``. The CRD body is
supplied by the caller (customer-agnostic, upstream Chaos Mesh syntax) so
this module carries no scenario-specific values.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Final

_DEFAULT_TIMEOUT: Final[float] = 60.0


async def _kubectl(
    args: Sequence[str],
    *,
    context: str,
    kubectl: str = "kubectl",
    stdin: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        kubectl,
        "--context",
        context,
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    payload = stdin.encode() if stdin is not None else None
    try:
        out, err = await asyncio.wait_for(proc.communicate(payload), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class ChaosMeshInjector:
    """Apply/delete one Chaos Mesh CRD as an enforce-mode fault injector."""

    def __init__(
        self,
        *,
        fault_type: str,
        context: str,
        kind: str,
        name: str,
        namespace: str,
        crd_yaml: str,
        kubectl: str = "kubectl",
    ) -> None:
        self._fault_type = fault_type
        self._ctx = context
        self._kind = kind
        self._name = name
        self._ns = namespace
        self._crd = crd_yaml
        self._kubectl = kubectl

    @property
    def fault_type(self) -> str:
        return self._fault_type

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await _kubectl(
            ["apply", "-f", "-"], context=self._ctx, kubectl=self._kubectl, stdin=self._crd
        )
        if rc != 0:
            raise RuntimeError(f"chaos-mesh apply {self._kind}/{self._name} failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        # Deleting the CRD reverses the fault (Chaos Mesh recovers the target).
        await _kubectl(
            [
                "delete",
                self._kind,
                self._name,
                "-n",
                self._ns,
                "--ignore-not-found",
                "--wait=false",
            ],
            context=self._ctx,
            kubectl=self._kubectl,
        )


class ChaosMeshInjectedProbe:
    """Observe a fault as live once Chaos Mesh reports ``AllInjected=True``."""

    def __init__(
        self,
        *,
        context: str,
        kind: str,
        name: str,
        namespace: str,
        kubectl: str = "kubectl",
    ) -> None:
        self._ctx = context
        self._kind = kind
        self._name = name
        self._ns = namespace
        self._kubectl = kubectl

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _kubectl(
            [
                "get",
                self._kind,
                self._name,
                "-n",
                self._ns,
                "-o",
                "json",
            ],
            context=self._ctx,
            kubectl=self._kubectl,
        )
        if rc != 0:
            return False
        try:
            status = json.loads(out).get("status", {})
        except json.JSONDecodeError:
            return False
        for cond in status.get("conditions", []):
            if cond.get("type") == "AllInjected" and cond.get("status") == "True":
                return True
        # Fallback: some Chaos Mesh versions expose phase only.
        return status.get("experiment", {}).get("desiredPhase") == "Run" and bool(
            status.get("experiment", {}).get("containerRecords")
            or status.get("experiment", {}).get("podRecords")
        )


__all__ = ["ChaosMeshInjectedProbe", "ChaosMeshInjector"]
