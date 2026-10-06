"""Deployment-selected production approval profile composition."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from fdai_service_contracts.approval_profile import (
    approval_profile_effective_from,
    approval_profile_policy_digest,
)
from fdai_service_contracts.policy_administration import (
    ApprovalPolicyContent,
    PolicyKind,
    PolicyRevisionRecord,
)

from fdai.agents import ApprovalRuntimeBindings
from fdai.core.risk_gate.approval_profile import ApprovalProfileKind, ApprovalProfileRevision
from fdai.runtime.development_authority import PROFILE_ENV as DEVELOPMENT_PROFILE_ENV

if TYPE_CHECKING:
    from fdai.shared.providers.state_store import StateStore

PROFILE_JSON_ENV = "FDAI_APPROVAL_PROFILE_JSON"
PROFILE_PATH_ENV = "FDAI_APPROVAL_PROFILE_PATH"
_LOGGER = logging.getLogger(__name__)
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
_ZERO_DIGEST = "sha256:" + "0" * 64


class ApprovalProfileRevisionReader(Protocol):
    """Read the active approval policy pointer and immutable revision."""

    async def active_revision_id(self, policy_kind: PolicyKind) -> str | None: ...

    async def revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
    ) -> PolicyRevisionRecord | None: ...


class ApprovalProfileAuditStore(Protocol):
    """Append an audit entry without importing a concrete persistence backend."""

    def append_audit_entry(self, entry: Mapping[str, Any]) -> Awaitable[None]: ...


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
    payload = _bootstrap_payload(raw_json=raw_json, raw_path=raw_path)
    if payload is None:
        return None
    return _profile_from_payload(payload, clock=clock)


async def load_active_approval_profile(
    environment: Mapping[str, str],
    *,
    reader: ApprovalProfileRevisionReader | None = None,
    audit_store: ApprovalProfileAuditStore | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> ApprovalProfileRevision | None:
    """Return the active policy-admin approval revision, falling back to bootstrap env.

    The activation pointer is authoritative when it exists. The environment
    bootstrap path remains only for first-start installations that have not yet
    activated an approval policy revision through Mimir.
    """

    env_profile = load_approval_profile(environment, clock=clock)
    if reader is None:
        return env_profile
    try:
        revision_id = await reader.active_revision_id(PolicyKind.APPROVAL)
        if revision_id is None:
            return env_profile
        active = await _active_profile_from_reader(reader, revision_id=revision_id, clock=clock)
        if env_profile is not None and active.as_audit_dict() != env_profile.as_audit_dict():
            await _audit_pointer_env_mismatch(
                audit_store,
                active=active,
                bootstrap=env_profile,
            )
        return active
    except Exception as exc:
        _LOGGER.warning("approval_profile_pointer_binding_failed", exc_info=True)
        raise RuntimeError("active approval profile revision is invalid") from exc


def approval_runtime_bindings(
    environment: Mapping[str, str],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> ApprovalRuntimeBindings | None:
    """Return composition bindings for the selected production approval profile."""

    profile = load_approval_profile(environment, clock=clock)
    return (
        ApprovalRuntimeBindings(profile, bootstrap_profile=profile) if profile is not None else None
    )


async def active_approval_runtime_bindings(
    environment: Mapping[str, str],
    *,
    reader: ApprovalProfileRevisionReader | None = None,
    audit_store: ApprovalProfileAuditStore | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
) -> ApprovalRuntimeBindings | None:
    """Return composition bindings for the active policy-admin approval profile."""

    bootstrap_profile = load_approval_profile(environment, clock=clock)
    profile = await load_active_approval_profile(
        environment,
        reader=reader,
        audit_store=audit_store,
        clock=clock,
    )
    return (
        ApprovalRuntimeBindings(profile, bootstrap_profile=bootstrap_profile)
        if profile is not None
        else None
    )


async def active_approval_runtime_bindings_from_store(
    environment: Mapping[str, str],
    store: StateStore,
) -> ApprovalRuntimeBindings | None:
    """Return active approval bindings from the StateStore policy pointer."""

    return await active_approval_runtime_bindings(
        environment,
        reader=StateStoreApprovalProfileRevisionReader(store),
        audit_store=store,
    )


class StateStoreApprovalProfileRevisionReader:
    """Read active approval revisions from Mimir's StateStore projection."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def active_revision_id(self, policy_kind: PolicyKind) -> str | None:
        stored = await self._store.read_state(_activation_key(policy_kind))
        if stored is None:
            return None
        revision_id = stored.get("revision_id") if stored is not None else None
        if not isinstance(revision_id, str) or not revision_id:
            raise RuntimeError("active approval profile pointer is malformed")
        return revision_id

    async def revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
    ) -> PolicyRevisionRecord | None:
        stored = await self._store.read_state(_revision_key(policy_kind, revision_id))
        if stored is None:
            return None
        return PolicyRevisionRecord.model_validate(stored)


def _bootstrap_payload(*, raw_json: str, raw_path: str) -> dict[str, object] | None:
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
    return dict(payload)


async def _active_profile_from_reader(
    reader: ApprovalProfileRevisionReader,
    *,
    revision_id: str,
    clock: Callable[[], datetime],
) -> ApprovalProfileRevision:
    revision = await reader.revision(policy_kind=PolicyKind.APPROVAL, revision_id=revision_id)
    if revision is None or not isinstance(revision.content, ApprovalPolicyContent):
        raise RuntimeError("active approval profile revision is missing")
    return _profile_from_payload(revision.content.document, clock=clock)


def _profile_from_payload(
    payload: Mapping[str, object],
    *,
    clock: Callable[[], datetime],
) -> ApprovalProfileRevision:
    unknown = set(payload) - _TOP_LEVEL_FIELDS
    if unknown:
        raise RuntimeError("approval profile JSON contains unknown fields")
    expected_digest = approval_profile_policy_digest(payload)
    if payload.get("policy_digest") != expected_digest:
        raise RuntimeError("approval profile policy_digest does not match revision content")
    try:
        effective_from = approval_profile_effective_from(payload.get("effective_from"))
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    try:
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


async def _audit_pointer_env_mismatch(
    audit_store: ApprovalProfileAuditStore | None,
    *,
    active: ApprovalProfileRevision,
    bootstrap: ApprovalProfileRevision,
) -> None:
    detail = {
        "event_type": "approval_profile_bootstrap_mismatch",
        "actor": "fdai.runtime.approval_profile",
        "active_revision_id": active.revision_id,
        "active_policy_digest": active.policy_digest,
        "bootstrap_revision_id": bootstrap.revision_id,
        "bootstrap_policy_digest": bootstrap.policy_digest,
    }
    _LOGGER.warning("approval_profile_bootstrap_mismatch", extra=detail)
    if audit_store is not None:
        await audit_store.append_audit_entry(detail)


def _revision_key(policy_kind: PolicyKind, revision_id: str) -> str:
    return f"policy_revision:{policy_kind.value}:{revision_id}"


def _activation_key(policy_kind: PolicyKind) -> str:
    return f"policy_activation:{policy_kind.value}"


__all__ = [
    "PROFILE_JSON_ENV",
    "PROFILE_PATH_ENV",
    "StateStoreApprovalProfileRevisionReader",
    "active_approval_runtime_bindings",
    "active_approval_runtime_bindings_from_store",
    "approval_runtime_bindings",
    "load_active_approval_profile",
    "load_approval_profile",
]
