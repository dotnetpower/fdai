"""Bounded environment parsing for the scenario-lab governed Chaos provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GovernedChaosProviderConfig:
    state_store_dsn: str
    promotion_ledger_path: Path
    target_binding_id: str
    approval_prefix: str = "governed-chaos-approval:"
    plan_prefix: str = "governed-chaos-plan:"
    dispatch_prefix: str = "governed-chaos-dispatch:"
    evidence_prefix: str = "governed-chaos-recovery-evidence:"
    stop_event_prefix: str = "governed-chaos-stop-event:"
    statement_timeout_ms: int = 15_000
    lock_timeout_ms: int = 30_000
    connect_timeout_seconds: int = 10

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> GovernedChaosProviderConfig:
        return cls(
            state_store_dsn=_required(environment, "FDAI_STATE_STORE_DSN", max_length=4096),
            promotion_ledger_path=_required_path(
                environment,
                "FDAI_GOVERNED_CHAOS_PROMOTION_LEDGER",
            ),
            target_binding_id=_required(
                environment,
                "FDAI_GOVERNED_CHAOS_TARGET_BINDING_ID",
                max_length=200,
            ),
            approval_prefix=_prefix(environment, "FDAI_GOVERNED_CHAOS_APPROVAL_PREFIX"),
            plan_prefix=_prefix(environment, "FDAI_GOVERNED_CHAOS_PLAN_PREFIX"),
            dispatch_prefix=_prefix(environment, "FDAI_GOVERNED_CHAOS_DISPATCH_PREFIX"),
            evidence_prefix=_prefix(environment, "FDAI_GOVERNED_CHAOS_EVIDENCE_PREFIX"),
            stop_event_prefix=_prefix(environment, "FDAI_GOVERNED_CHAOS_STOP_EVENT_PREFIX"),
            statement_timeout_ms=_bounded_int(
                environment,
                "FDAI_GOVERNED_CHAOS_STATEMENT_TIMEOUT_MS",
                default=15_000,
                minimum=1,
                maximum=300_000,
            ),
            lock_timeout_ms=_bounded_int(
                environment,
                "FDAI_GOVERNED_CHAOS_LOCK_TIMEOUT_MS",
                default=30_000,
                minimum=1,
                maximum=300_000,
            ),
            connect_timeout_seconds=_bounded_int(
                environment,
                "FDAI_GOVERNED_CHAOS_CONNECT_TIMEOUT_SECONDS",
                default=10,
                minimum=1,
                maximum=120,
            ),
        )


def _required(environment: Mapping[str, str], name: str, *, max_length: int) -> str:
    value = environment.get(name, "").strip()
    if not value or len(value) > max_length or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} must be a bounded non-empty value")
    return value


def _required_path(environment: Mapping[str, str], name: str) -> Path:
    raw = _required(environment, name, max_length=4096)
    path = Path(raw)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{name} must be an existing absolute file path")
    return path


def _prefix(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None:
        defaults = {
            "FDAI_GOVERNED_CHAOS_APPROVAL_PREFIX": "governed-chaos-approval:",
            "FDAI_GOVERNED_CHAOS_PLAN_PREFIX": "governed-chaos-plan:",
            "FDAI_GOVERNED_CHAOS_DISPATCH_PREFIX": "governed-chaos-dispatch:",
            "FDAI_GOVERNED_CHAOS_EVIDENCE_PREFIX": "governed-chaos-recovery-evidence:",
            "FDAI_GOVERNED_CHAOS_STOP_EVENT_PREFIX": "governed-chaos-stop-event:",
        }
        return defaults[name]
    if not value or len(value) > 128 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} must be a bounded state-store prefix")
    return value


def _bounded_int(
    environment: Mapping[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = environment.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


__all__ = ["GovernedChaosProviderConfig"]
