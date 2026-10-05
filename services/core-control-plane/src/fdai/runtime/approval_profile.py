"""Deployment-selected production approval profile composition."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from fdai_service_contracts.approval_profile import approval_profile_policy_digest

from fdai.agents import ApprovalRuntimeBindings
from fdai.core.risk_gate.approval_profile import ApprovalProfileKind, ApprovalProfileRevision
from fdai.runtime.development_authority import PROFILE_ENV as DEVELOPMENT_PROFILE_ENV

PROFILE_JSON_ENV = "FDAI_APPROVAL_PROFILE_JSON"
PROFILE_PATH_ENV = "FDAI_APPROVAL_PROFILE_PATH"
_REVISION_FIELDS = frozenset(
    (
        "revision_id",
        "approval_profile",
        "executor_principal",
        "effective_from",
        "operator_principal",
    )
)
_TOP_LEVEL_FIELDS = _REVISION_FIELDS | {"policy_digest"}


def load_approval_profile(
    environment: Mapping[str, str],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> ApprovalProfileRevision | None:
    """Return the active approval profile revision or ``None`` for the default."""

    raw_json = environment.get(PROFILE_JSON_ENV, "").strip()
    raw_path = environment.get(PROFILE_PATH_ENV, "").strip()
    if environment.get(DEVELOPMENT_PROFILE_ENV, "").strip() and (raw_json or raw_path):
        raise RuntimeError(
            "approval profile and full-authority development profile are mutually exclusive"
        )
    if raw_json and raw_path:
        raise RuntimeError("approval profile must be supplied as JSON or path, not both")
    if not raw_json and not raw_path:
        return None
    if raw_path:
        try:
            raw_json = Path(raw_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError("approval profile path is unreadable") from exc
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("approval profile JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("approval profile JSON must be an object")
    unknown = set(payload) - _TOP_LEVEL_FIELDS
    if unknown:
        raise RuntimeError("approval profile JSON contains unknown fields")
    expected_digest = approval_profile_policy_digest(payload)
    if payload.get("policy_digest") != expected_digest:
        raise RuntimeError("approval profile policy_digest does not match revision content")
    try:
        effective_from_raw = str(payload["effective_from"])
        effective_from = datetime.fromisoformat(effective_from_raw)
        now = clock()
        if now.tzinfo is None or effective_from.tzinfo is None:
            raise RuntimeError("approval profile clock and effective_from must be timezone-aware")
        if effective_from > now:
            raise RuntimeError("approval profile is not yet effective")
        operator = payload.get("operator_principal")
        return ApprovalProfileRevision(
            revision_id=str(payload["revision_id"]),
            approval_profile=ApprovalProfileKind(str(payload["approval_profile"])),
            executor_principal=str(payload["executor_principal"]),
            policy_digest=str(payload["policy_digest"]),
            effective_from=effective_from,
            operator_principal=(str(operator) if operator is not None else None),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("approval profile revision is invalid") from exc


def approval_runtime_bindings(
    environment: Mapping[str, str],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> ApprovalRuntimeBindings | None:
    """Return composition bindings for the selected production approval profile."""

    profile = load_approval_profile(environment, clock=clock)
    return ApprovalRuntimeBindings(profile) if profile is not None else None


__all__ = [
    "PROFILE_JSON_ENV",
    "PROFILE_PATH_ENV",
    "approval_runtime_bindings",
    "load_approval_profile",
]
