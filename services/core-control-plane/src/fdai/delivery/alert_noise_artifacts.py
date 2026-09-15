"""Prepare immutable private IaC artifacts from exact deployment-owned source bindings."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from fdai_service_contracts.alert_noise import AlertEvidence, digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.delivery.alert_noise_iac import AlertIaCBinding, render_alert_iac
from fdai.delivery.alert_noise_pr import AlertIaCSourceReader
from fdai.shared.providers.state_store import StateStore


class AlertPlanArtifactPreparer:
    """Retain one reviewed-file candidate; no approval, PR publication or Azure call."""

    def __init__(
        self,
        *,
        source: AlertIaCSourceReader,
        store: StateStore,
        bindings: Mapping[str, AlertIaCBinding],
    ) -> None:
        self._source, self._store, self._bindings = source, store, dict(bindings)

    async def prepare(self, *, plan: AlertChangePlan, evidence: AlertEvidence) -> None:
        """Read the pinned existing source, then retain a replayable forward/restore pair."""
        target = plan.treatment.processing_rule_ref or plan.treatment.target_ref
        binding = self._bindings.get(target)
        if binding is None:
            raise AlertExecutionHeld("iac_target_unbound")
        async with asyncio.timeout(20):
            source = await self._source.read(path=binding.path)
            if source is None:
                raise AlertExecutionHeld("iac_source_missing")
            patch = render_alert_iac(plan, evidence, binding=binding, source=source)
            digest = digest_record(plan)
            value = {**asdict(patch), "plan_digest": digest}
            key = "alert-noise:patch:" + digest
            created = await self._store.write_state_with_audit_if_absent(
                key,
                value,
                {
                    "actor": "Forseti",
                    "action_kind": "alert_noise.patch.prepared",
                    "plan_digest": digest,
                    "source_digest": patch.source_digest,
                    "result_digest": patch.result_digest,
                    "execution_authority": False,
                },
            )
            if not created and await self._store.read_state(key) != value:
                raise AlertExecutionHeld("iac_artifact_conflict")


def parse_alert_iac_bindings(environment: Mapping[str, str]) -> Mapping[str, AlertIaCBinding]:
    """Decode optional private source selectors; no path or source is inferred from a request."""
    raw = environment.get("FDAI_ALERT_NOISE_IAC_BINDINGS_JSON")
    if raw is None:
        return {}
    try:
        if not 1 <= len(raw.encode()) <= 262_144:
            raise ValueError("invalid size")
        rows = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
            raise ValueError("invalid bindings")
        result: dict[str, AlertIaCBinding] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid binding")
            binding = AlertIaCBinding(**row)
            if binding.target_ref in result:
                raise ValueError("duplicate target")
            result[binding.target_ref] = binding
        return result
    except (ValueError, TypeError, RecursionError):
        raise ValueError(
            "alert IaC configuration MUST contain exact bounded private bindings"
        ) from None


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate IaC configuration field")
        result[key] = value
    return result
