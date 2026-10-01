"""Bounded multi-target ActionRun batch helpers for Thor."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents._framework.topics import stable_idempotency_key

_MAX_TARGETS = 64
_MAX_TARGET_CHARS = 512


@dataclass(frozen=True, slots=True)
class BatchTargetSet:
    targets: tuple[str, ...]
    digest: str
    max_targets: int


@dataclass(frozen=True, slots=True)
class BatchHold:
    outcome: Literal["batch_target_set_unknown", "batch_target_set_over_limit"]
    target_count: int
    max_targets: int | None


def parse_batch_target_set(verdict: Mapping[str, Any]) -> BatchTargetSet | BatchHold | None:
    """Return a bounded explicit multi-target set, a visible hold, or ``None``."""

    if "targets" in verdict:
        raw_targets = verdict.get("targets")
    elif "target_set" in verdict:
        raw_targets = verdict.get("target_set")
    else:
        return None
    max_targets = _max_targets(verdict)
    if max_targets is None:
        return BatchHold(
            outcome="batch_target_set_unknown",
            target_count=_raw_target_count(raw_targets),
            max_targets=None,
        )
    if not isinstance(raw_targets, list | tuple):
        return BatchHold(
            outcome="batch_target_set_unknown",
            target_count=0,
            max_targets=max_targets,
        )
    targets: list[str] = []
    seen: set[str] = set()
    for item in raw_targets:
        if not isinstance(item, str):
            return BatchHold(
                outcome="batch_target_set_unknown",
                target_count=len(raw_targets),
                max_targets=max_targets,
            )
        normalized = item.strip()
        if not normalized or len(normalized) > _MAX_TARGET_CHARS or normalized in seen:
            return BatchHold(
                outcome="batch_target_set_unknown",
                target_count=len(raw_targets),
                max_targets=max_targets,
            )
        seen.add(normalized)
        targets.append(normalized)
    if len(targets) <= 1:
        return None
    if len(targets) > max_targets or len(targets) > _MAX_TARGETS:
        return BatchHold(
            outcome="batch_target_set_over_limit",
            target_count=len(targets),
            max_targets=max_targets,
        )
    return BatchTargetSet(
        targets=tuple(targets),
        digest=_target_set_digest(targets),
        max_targets=max_targets,
    )


def rollup_resource_id(target_set: BatchTargetSet) -> str:
    return f"target-set:{target_set.digest[7:39]}"


def build_rollup_fields(target_set: BatchTargetSet) -> dict[str, Any]:
    return {
        "batch_role": "rollup",
        "target_set_digest": target_set.digest,
        "target_set": list(target_set.targets),
        "target_count": len(target_set.targets),
        "batch_rollup": {
            "schema_version": "1.0.0",
            "total": len(target_set.targets),
            "states": {},
            "succeeded": 0,
            "failed": 0,
            "rolled_back": 0,
            "rollback_failed": 0,
            "rollback_refused": 0,
            "execution_unknown": 0,
            "terminal": False,
            "terminal_state_rule": "pending_attempts",
            "failed_target_digests": [],
            "rolled_back_target_digests": [],
        },
    }


def attempt_identity(rollup: ActionRun, target: str) -> str:
    return stable_idempotency_key("action-attempt", rollup.action_run_identity(), target)


def attempt_verdict(
    verdict: Mapping[str, Any],
    *,
    rollup: ActionRun,
    target: str,
) -> dict[str, Any]:
    attempt_id = attempt_identity(rollup, target)
    payload = deepcopy(dict(verdict))
    payload.pop("targets", None)
    payload.pop("target_set", None)
    payload["correlation_id"] = stable_idempotency_key(
        "action-attempt-correlation",
        rollup.correlation_id,
        target,
    )
    payload["idempotency_key"] = stable_idempotency_key(
        "action-attempt-verdict",
        rollup.idempotency_key,
        target,
    )
    payload["action_idempotency_key"] = stable_idempotency_key(
        "action-attempt-execution",
        rollup.idempotency_key,
        target,
    )
    payload["resource_id"] = target
    payload["batch_role"] = "attempt"
    payload["attempt_id"] = attempt_id
    payload["rollup_correlation_id"] = rollup.correlation_id
    payload["rollup_action_run_identity"] = rollup.action_run_identity()
    payload["target_set_digest"] = rollup.target_set_digest
    payload["target_count"] = rollup.target_count
    return payload


def apply_batch_verdict_fields(run: ActionRun, verdict: Mapping[str, Any]) -> None:
    role = verdict.get("batch_role")
    if role not in {"attempt", "rollup"}:
        return
    run.batch_role = role
    run.attempt_id = _optional_string(verdict.get("attempt_id"))
    run.rollup_correlation_id = _optional_string(verdict.get("rollup_correlation_id"))
    run.rollup_action_run_identity = _optional_string(verdict.get("rollup_action_run_identity"))
    run.target_set_digest = _optional_string(verdict.get("target_set_digest"))
    target_set = bounded_target_set(verdict.get("target_set"))
    if target_set is not None:
        run.target_set = target_set
    target_count = verdict.get("target_count")
    if isinstance(target_count, int) and not isinstance(target_count, bool) and target_count > 0:
        run.target_count = min(target_count, _MAX_TARGETS)


def bounded_target_set(raw_targets: object) -> tuple[str, ...] | None:
    if not isinstance(raw_targets, list | tuple):
        return None
    targets: list[str] = []
    seen: set[str] = set()
    for item in raw_targets:
        if not isinstance(item, str):
            return None
        normalized = item.strip()
        if not normalized or len(normalized) > _MAX_TARGET_CHARS or normalized in seen:
            return None
        seen.add(normalized)
        targets.append(normalized)
    if len(targets) > _MAX_TARGETS:
        return None
    return tuple(targets)


def target_set_digest(targets: tuple[str, ...]) -> str:
    return _target_set_digest(list(targets))


def target_set_matches_digest(targets: tuple[str, ...] | None, digest: str | None) -> bool:
    return targets is not None and digest is not None and target_set_digest(targets) == digest


def refresh_rollup(rollup: ActionRun, attempts: tuple[ActionRun, ...]) -> None:
    """Update typed rollup counts and terminal state from current attempts."""

    states: dict[str, int] = {}
    failed_target_digests: list[str] = []
    rolled_back_target_digests: list[str] = []
    for attempt in attempts:
        state = attempt.state.value
        states[state] = states.get(state, 0) + 1
        if attempt.state in {
            ActionRunState.FAILED,
            ActionRunState.EXECUTION_UNKNOWN,
            ActionRunState.ROLLBACK_FAILED,
            ActionRunState.ROLLBACK_REFUSED,
        }:
            failed_target_digests.append(_target_digest(str(attempt.resource_id or "")))
        if attempt.state is ActionRunState.ROLLED_BACK:
            rolled_back_target_digests.append(_target_digest(str(attempt.resource_id or "")))
    total = rollup.target_count or len(attempts)
    terminal = len(attempts) == total and all(_attempt_terminal(attempt) for attempt in attempts)
    succeeded = states.get(ActionRunState.SUCCEEDED.value, 0)
    rolled_back = states.get(ActionRunState.ROLLED_BACK.value, 0)
    rollback_failed = states.get(ActionRunState.ROLLBACK_FAILED.value, 0)
    rollback_refused = states.get(ActionRunState.ROLLBACK_REFUSED.value, 0)
    failed = states.get(ActionRunState.FAILED.value, 0)
    execution_unknown = states.get(ActionRunState.EXECUTION_UNKNOWN.value, 0)
    terminal_rule = "pending_attempts"
    if terminal:
        if succeeded == total:
            terminal_rule = "all_attempts_succeeded"
        elif rollback_failed or rollback_refused or failed or execution_unknown:
            terminal_rule = "unrecovered_attempt_failure"
        else:
            terminal_rule = "mixed_success_and_target_rollback"
    rollup.batch_rollup = {
        "schema_version": "1.0.0",
        "total": total,
        "states": states,
        "succeeded": succeeded,
        "failed": failed,
        "rolled_back": rolled_back,
        "rollback_failed": rollback_failed,
        "rollback_refused": rollback_refused,
        "execution_unknown": execution_unknown,
        "terminal": terminal,
        "terminal_state_rule": terminal_rule,
        "failed_target_digests": sorted(failed_target_digests),
        "rolled_back_target_digests": sorted(rolled_back_target_digests),
    }
    if not terminal:
        return
    if rollup.state not in {
        ActionRunState.SUCCEEDED,
        ActionRunState.ROLLED_BACK,
        ActionRunState.ROLLBACK_FAILED,
    }:
        if terminal_rule == "all_attempts_succeeded":
            rollup.transition(ActionRunState.SUCCEEDED)
            rollup.outcome = "batch_succeeded"
        elif terminal_rule == "mixed_success_and_target_rollback":
            rollup.transition(ActionRunState.ROLLED_BACK)
            rollup.outcome = "batch_mixed_outcome"
        else:
            rollup.transition(ActionRunState.ROLLBACK_FAILED)
            rollup.outcome = "batch_failed"


def _attempt_terminal(attempt: ActionRun) -> bool:
    if attempt.state in {
        ActionRunState.SUCCEEDED,
        ActionRunState.DENY_DROPPED,
        ActionRunState.REJECTED,
        ActionRunState.ROLLED_BACK,
        ActionRunState.ROLLBACK_FAILED,
        ActionRunState.ROLLBACK_REFUSED,
    }:
        return True
    return False


def _target_set_digest(targets: list[str]) -> str:
    encoded = json.dumps(
        targets,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _target_digest(target: str) -> str:
    return "sha256:" + hashlib.sha256(target.encode("utf-8")).hexdigest()


def _max_targets(verdict: Mapping[str, Any]) -> int | None:
    safeguards = verdict.get("safeguards")
    if not isinstance(safeguards, Mapping):
        return None
    blast = safeguards.get("blast_radius_limit") or safeguards.get("blast_radius")
    if isinstance(blast, Mapping):
        for key in ("max_targets", "max_affected_objects", "max_resources"):
            value = blast.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return min(value, _MAX_TARGETS)
    return None


def _raw_target_count(raw_targets: object) -> int:
    if isinstance(raw_targets, list | tuple):
        return len(raw_targets)
    return 0


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


__all__ = [
    "BatchHold",
    "BatchTargetSet",
    "apply_batch_verdict_fields",
    "attempt_identity",
    "attempt_verdict",
    "bounded_target_set",
    "build_rollup_fields",
    "parse_batch_target_set",
    "refresh_rollup",
    "rollup_resource_id",
    "target_set_digest",
    "target_set_matches_digest",
]
