"""Thor-owned pre-flight simulation receipt helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from fdai.agents._framework import action_semantics
from fdai.agents._framework.thor_action_run import ActionRun

_MAX_REASON_CHARS = 256
_MAX_SIMULATOR_ID_CHARS = 128
_MAX_SIMULATOR_VERSION_CHARS = 64
_DIGEST_PREFIX = "sha256:"

PreflightOutcome = Literal["passed", "failed"]


@dataclass(frozen=True, slots=True)
class PreflightSimulationResult:
    """Bounded result returned by an injected Thor pre-flight simulator."""

    outcome: PreflightOutcome
    simulator_id: str
    simulator_version: str
    reason: str = ""


class ThorPreflightSimulator(Protocol):
    """Provider-neutral pre-flight simulation seam for Thor enforce dispatch."""

    async def simulate(self, run: ActionRun) -> PreflightSimulationResult: ...


@dataclass(frozen=True, slots=True)
class CompositeThorPreflightSimulator:
    """Route Thor pre-flight simulation by ActionType and fail closed on gaps."""

    simulators_by_action_type: Mapping[str, ThorPreflightSimulator]

    async def simulate(self, run: ActionRun) -> PreflightSimulationResult:
        simulator = self.simulators_by_action_type.get(run.action_type)
        if simulator is None:
            return PreflightSimulationResult(
                outcome="failed",
                simulator_id="thor-composite-preflight",
                simulator_version="1",
                reason="no_simulator_for_action_type",
            )
        return await simulator.simulate(run)


def params_digest(params: Mapping[str, Any]) -> str:
    """Return a canonical digest for one ActionRun params mapping."""

    encoded = json.dumps(
        params,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _DIGEST_PREFIX + hashlib.sha256(encoded).hexdigest()


def high_risk(run: ActionRun, catalog: action_semantics.ActionSemanticsCatalog | None) -> bool:
    """Return whether Thor must simulate this non-shadow run before executor I/O."""

    return (
        (catalog is not None and catalog.irreversible(run.action_type))
        or run.original_quorum_required is not None
        and run.original_quorum_required >= action_semantics.IRREVERSIBLE_QUORUM
        or run.effective_quorum_required is not None
        and run.effective_quorum_required >= action_semantics.IRREVERSIBLE_QUORUM
        or run.verdict == "hil"
    )


def requires_preflight(run: ActionRun) -> bool:
    """Return whether this run needs a Thor pre-flight receipt."""

    return run.preflight_required or run.dry_run_evidence == "declared_obligation"


def receipt_is_fresh(
    receipt: Mapping[str, Any] | None,
    *,
    run: ActionRun,
    now: datetime,
    ttl_seconds: int,
) -> bool:
    """Return whether a stored passing receipt still binds this exact run."""

    if receipt is None or ttl_seconds < 1:
        return False
    completed_at = _parse_timestamp(receipt.get("completed_at"))
    receipt_digest = receipt.get("receipt_digest")
    return (
        receipt.get("schema_version") == "1.0.0"
        and receipt.get("outcome") == "passed"
        and isinstance(receipt_digest, str)
        and receipt_digest == digest(receipt)
        and receipt.get("action_run_identity") == run.action_run_identity()
        and receipt.get("action_type") == run.action_type
        and receipt.get("target") == run.resource_id
        and receipt.get("params_digest") == params_digest(run.params)
        and completed_at is not None
        and now - completed_at <= timedelta(seconds=ttl_seconds)
    )


def build_receipt(
    *,
    run: ActionRun,
    result: PreflightSimulationResult,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    """Build a bounded, digest-addressable pre-flight simulation receipt."""

    receipt = {
        "schema_version": "1.0.0",
        "action_run_identity": run.action_run_identity(),
        "action_type": run.action_type,
        "target": run.resource_id,
        "params_digest": params_digest(run.params),
        "simulator_id": _bounded_text(result.simulator_id, _MAX_SIMULATOR_ID_CHARS),
        "simulator_version": _bounded_text(
            result.simulator_version,
            _MAX_SIMULATOR_VERSION_CHARS,
        ),
        "outcome": result.outcome,
        "started_at": started_at.astimezone(UTC).isoformat(),
        "completed_at": completed_at.astimezone(UTC).isoformat(),
        "reason": _bounded_text(result.reason, _MAX_REASON_CHARS),
    }
    receipt["receipt_digest"] = digest(receipt)
    return receipt


def digest(receipt: Mapping[str, Any]) -> str:
    """Return the receipt digest excluding any existing digest field."""

    payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _DIGEST_PREFIX + hashlib.sha256(encoded).hexdigest()


def _bounded_text(value: object, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


__all__ = [
    "CompositeThorPreflightSimulator",
    "PreflightSimulationResult",
    "ThorPreflightSimulator",
    "build_receipt",
    "high_risk",
    "receipt_is_fresh",
    "requires_preflight",
]
