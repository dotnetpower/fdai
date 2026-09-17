"""Independent effect verification and terminalization for Thor ActionRuns."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypedDict

from fdai.agents._framework import action_run_lineage
from fdai.agents._framework.action_run_state import ActionRunState

if TYPE_CHECKING:
    from fdai.agents.thor import ActionRun


class DurableEffectVerification(TypedDict):
    effect_verification_ref: str | None
    execution_closure_ref: str | None
    effect_verified_at: datetime | None


def _is_sha256_ref(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def validate_effect_verification(
    effect_ref: str | None,
    closure_ref: str | None,
    verified_at: datetime | None,
) -> None:
    verification = (effect_ref, closure_ref, verified_at)
    if any(value is not None for value in verification) and (
        not all(value is not None for value in verification)
        or not _is_sha256_ref(effect_ref)
        or not _is_sha256_ref(closure_ref)
        or verified_at is None
        or verified_at.tzinfo is None
        or verified_at.utcoffset() is None
    ):
        raise ValueError("ActionRun effect verification must be complete and canonical")


def effect_verification_mapping(run: ActionRun) -> dict[str, object]:
    return {
        "effect_verification_ref": run.effect_verification_ref,
        "execution_closure_ref": run.execution_closure_ref,
        "effect_verified_at": (
            run.effect_verified_at.isoformat() if run.effect_verified_at is not None else None
        ),
    }


def durable_effect_verification(data: Mapping[str, Any]) -> DurableEffectVerification:
    return {
        "effect_verification_ref": action_run_lineage.optional_bounded_text(
            data.get("effect_verification_ref"),
            field_name="effect_verification_ref",
        ),
        "execution_closure_ref": action_run_lineage.optional_bounded_text(
            data.get("execution_closure_ref"),
            field_name="execution_closure_ref",
        ),
        "effect_verified_at": action_run_lineage.optional_datetime(
            data.get("effect_verified_at"),
            field_name="effect_verified_at",
        ),
    }


def effect_publication_fields(run: ActionRun) -> dict[str, object]:
    return {
        "operational_success": run.outcome == "independent_effect_verified",
        "effect_verification_status": (
            "verified"
            if run.outcome == "independent_effect_verified"
            else "pending"
            if run.outcome == "command_accepted_verification_pending"
            else "not_applicable"
        ),
        **effect_verification_mapping(run),
    }


class ThorEffectVerificationMixin:
    """Close an exact ActionRun only from Heimdall's independent verified effect."""

    action_runs: dict[str, ActionRun]

    if TYPE_CHECKING:

        async def _emit_action_run(self, run: ActionRun) -> None: ...

        async def _finalize_terminal_replay(self, run: ActionRun) -> None: ...

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    async def _handle_effect_observation(self, observation: dict[str, Any]) -> None:
        """Terminalize only the exact ActionRun named by a Heimdall verified-effect event."""
        if observation.get("event_type") != "action.execution.effect_verified.v1":
            return
        if (
            observation.get("producer_principal") != "Heimdall"
            or observation.get("schema_version") != "1.0.0"
        ):
            raise ValueError("ActionRun effect verification requires Heimdall evidence")
        correlation = str(observation.get("correlation_id") or "")
        run = self.action_runs.get(correlation)
        if run is None:
            return
        if (
            observation.get("action_id") != run.action_id
            or observation.get("action_type") != run.action_type
            or observation.get("resource_id") != run.resource_id
            or observation.get("action_idempotency_key") != run.idempotency_key
            or observation.get("params") != run.params
            or run.shadow_mode
            or run.state not in {ActionRunState.EXECUTION_UNKNOWN, ActionRunState.SUCCEEDED}
        ):
            raise ValueError("verified effect does not match the exact ActionRun")
        effect_ref = action_run_lineage.optional_bounded_text(
            observation.get("effect_verification_ref"),
            field_name="effect_verification_ref",
        )
        closure_ref = action_run_lineage.optional_bounded_text(
            observation.get("execution_closure_ref"),
            field_name="execution_closure_ref",
        )
        verified_at = action_run_lineage.optional_datetime(
            observation.get("observed_at"),
            field_name="effect_verified_at",
        )
        if (
            effect_ref is None
            or closure_ref is None
            or not effect_ref.startswith("sha256:")
            or not closure_ref.startswith("sha256:")
            or verified_at is None
        ):
            raise ValueError("ActionRun effect verification references are invalid")
        if run.effect_verification_ref is not None and (
            run.effect_verification_ref != effect_ref
            or run.execution_closure_ref != closure_ref
            or run.effect_verified_at != verified_at
        ):
            raise ValueError("ActionRun already binds different effect verification")
        if run.state is ActionRunState.SUCCEEDED:
            return
        run.effect_verification_ref = effect_ref
        run.execution_closure_ref = closure_ref
        run.effect_verified_at = verified_at
        run.outcome = "independent_effect_verified"
        if run.state is ActionRunState.EXECUTION_UNKNOWN:
            run.transition(ActionRunState.SUCCEEDED)
        await self._emit_action_run(run)
        await self._finalize_terminal_replay(run)
        self.record_behavior("execution:independent_effect_verified")


__all__ = [
    "ThorEffectVerificationMixin",
    "durable_effect_verification",
    "effect_publication_fields",
    "effect_verification_mapping",
    "validate_effect_verification",
]
