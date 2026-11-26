"""Lifecycle commands with mandatory expiry, authority-lowering bounds, and break-glass rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    validate_configuration_package_for_signing,
)
from fdai_deployment_cli.lifecycle_plan import PlanAdmissionDecision

LifecycleCommandKind = Literal["suppression-window", "authority-lowering", "break-glass"]
BreakGlassBypass = Literal["maintenance-window", "suppression-window", "version-range"]

_SUPPORTED_COMMAND_KINDS = frozenset({"suppression-window", "authority-lowering", "break-glass"})
_ALLOWED_BREAK_GLASS_BYPASSES: frozenset[str] = frozenset(
    {"maintenance-window", "suppression-window", "version-range"}
)
_ALLOWED_LOWERED_MODES = frozenset({"shadow"})
_ALLOWED_LOWERED_AUTONOMY = frozenset({"shadow", "hil"})


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} MUST include timezone information")


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleCommand:
    """One time-bounded operator or break-glass command.

    Every command requires an explicit ``expires_at`` after ``starts_at``. No command may
    raise authority (promote an ActionType to ``enforce``, raise autonomy to ``auto``,
    disengage the kill switch, or bypass signature, envelope, recall, schema, residency, or
    destructive-change checks).
    """

    command_id: str
    kind: LifecycleCommandKind
    actor: str
    reason: str
    starts_at: datetime
    expires_at: datetime | None = None
    scope: str = "installation"
    target_action_type: str | None = None
    target_mode: str | None = None
    target_autonomy: str | None = None
    engage_kill_switch: bool = False
    disengage_kill_switch: bool = False
    bypass_scopes: frozenset[str] = field(default_factory=frozenset)
    emergency_overrides: tuple[Mapping[str, object], ...] = ()
    fresh_authenticated: bool = True

    def is_active(self, now: datetime) -> bool:
        _require_aware(now, "now")
        if self.expires_at is None:
            return False
        return self.starts_at <= now < self.expires_at

    def is_expired(self, now: datetime) -> bool:
        _require_aware(now, "now")
        if self.expires_at is None:
            return False
        return now >= self.expires_at


def validate_lifecycle_command(
    command: LifecycleCommand,
    *,
    trusted_now: datetime | None = None,
) -> PlanAdmissionDecision:
    """Validate mandatory expiry, kind-specific bounds, and the no-authority-raising invariant."""

    if not command.command_id.strip() or not command.actor.strip() or not command.reason.strip():
        return PlanAdmissionDecision(False, "command_metadata_missing", (command.command_id,))
    if command.kind not in _SUPPORTED_COMMAND_KINDS:
        return PlanAdmissionDecision(False, "command_kind_unsupported", (str(command.kind),))
    _require_aware(command.starts_at, "starts_at")
    if command.expires_at is None:
        return PlanAdmissionDecision(False, "command_expiry_required", (command.command_id,))
    _require_aware(command.expires_at, "expires_at")
    if command.expires_at <= command.starts_at:
        return PlanAdmissionDecision(False, "command_window_invalid", (command.command_id,))
    if trusted_now is not None:
        _require_aware(trusted_now, "trusted_now")
        if command.expires_at <= trusted_now:
            return PlanAdmissionDecision(False, "command_expired", (command.command_id,))

    # Authority-raising checks apply across every command kind.
    if command.disengage_kill_switch:
        return PlanAdmissionDecision(False, "command_raises_authority", ("disengage_kill_switch",))
    if command.target_mode is not None and command.target_mode not in _ALLOWED_LOWERED_MODES:
        return PlanAdmissionDecision(
            False, "command_raises_authority", (f"target_mode:{command.target_mode}",)
        )
    if (
        command.target_autonomy is not None
        and command.target_autonomy not in _ALLOWED_LOWERED_AUTONOMY
    ):
        return PlanAdmissionDecision(
            False, "command_raises_authority", (f"target_autonomy:{command.target_autonomy}",)
        )
    forbidden_bypasses = sorted(command.bypass_scopes - _ALLOWED_BREAK_GLASS_BYPASSES)
    if forbidden_bypasses:
        return PlanAdmissionDecision(False, "command_raises_authority", tuple(forbidden_bypasses))

    if command.kind == "suppression-window":
        if (
            command.target_mode is not None
            or command.target_autonomy is not None
            or command.engage_kill_switch
            or command.bypass_scopes
            or command.emergency_overrides
        ):
            return PlanAdmissionDecision(False, "command_scope_invalid", (command.command_id,))
    elif command.kind == "authority-lowering":
        if command.bypass_scopes or command.emergency_overrides:
            return PlanAdmissionDecision(False, "command_raises_authority", (command.command_id,))
        if not (
            command.target_mode == "shadow"
            or command.target_autonomy in _ALLOWED_LOWERED_AUTONOMY
            or command.engage_kill_switch
        ):
            return PlanAdmissionDecision(
                False, "command_lowering_effect_missing", (command.command_id,)
            )
    elif command.kind == "break-glass":
        if not command.fresh_authenticated:
            return PlanAdmissionDecision(
                False, "break_glass_fresh_auth_required", (command.command_id,)
            )
        if not (command.bypass_scopes or command.emergency_overrides):
            return PlanAdmissionDecision(False, "break_glass_effect_missing", (command.command_id,))
        if command.emergency_overrides:
            try:
                validate_configuration_package_for_signing(
                    {"overrides": command.emergency_overrides}
                )
            except ConfigurationValidationError as error:
                return PlanAdmissionDecision(
                    False, f"configuration_{error.code}", (command.command_id,)
                )
    return PlanAdmissionDecision(True, "allowed", ())


def require_valid_lifecycle_command(
    command: LifecycleCommand,
    *,
    trusted_now: datetime | None = None,
) -> LifecycleCommand:
    """Return ``command`` if valid, or raise ``ValueError`` with the rejection reason code."""

    decision = validate_lifecycle_command(command, trusted_now=trusted_now)
    if not decision.allowed:
        raise ValueError(decision.reason_code)
    return command


def overrides_adopted(
    emergency_overrides: tuple[Mapping[str, object], ...],
    approved_overrides: tuple[Mapping[str, object], ...],
) -> bool:
    """Return whether every emergency override block is present in the approved overrides."""

    if not emergency_overrides:
        return True
    approved_canonical = {canonical_bytes(block) for block in approved_overrides}
    return all(canonical_bytes(block) in approved_canonical for block in emergency_overrides)
