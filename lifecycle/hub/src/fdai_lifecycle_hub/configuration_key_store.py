"""Durable configuration key decisions on the existing enrollment lock and audit chain."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from fdai_lifecycle_hub import audit, models, rows
from fdai_lifecycle_hub.configuration_keys import (
    ConfigurationKeyRequest,
    KeyBindingError,
    SignedKeyRequest,
)


class ConfigurationKeyStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def deny(self, installation_id: str, *, actor: str, now: datetime, reason: str) -> None:
        def decision(session: Session, installation: models.Installation) -> str:
            raise KeyBindingError(reason)

        self._decide(installation_id, actor, now, "request", decision)

    def pending_request(self, installation_id: str, digest: str) -> dict[str, Any]:
        with self._sessions() as session:
            row = session.get(models.ConfigurationKeyRequest, digest)
            if row is None or row.installation_id != installation_id:
                raise KeyBindingError("configuration_request_missing")
            request = ConfigurationKeyRequest.model_validate_json(row.payload)
            if request.digest != digest or request.installation_id != installation_id:
                raise KeyBindingError("configuration_request_mismatch")
            return {"request_digest": row.digest, "request": request.model_dump(mode="json")}

    def _decide(
        self,
        installation_id: str,
        actor: str,
        now: datetime,
        action: str,
        decision: Callable[[Session, models.Installation], str],
    ) -> str:
        failure: KeyBindingError | None = None
        digest = installation_id
        with self._sessions.begin() as session:
            installation = rows.lock_enrolled(session, installation_id)
            try:
                digest = decision(session, installation)
            except KeyBindingError as error:
                failure = error
            audit.append(
                session,
                now,
                f"configuration.keys.{action}" if failure is None else "configuration.keys.denied",
                installation_id,
                digest,
                {
                    "actor": actor,
                    "operation": action,
                    "reason": str(failure) if failure else "accepted",
                },
            )
        if failure is not None:
            raise failure
        return digest

    def request(
        self, installation_id: str, signed: SignedKeyRequest, *, actor: str, now: datetime
    ) -> str:
        def decision(session: Session, installation: models.Installation) -> str:
            try:
                request = signed.parsed()
            except ValueError:
                raise KeyBindingError("configuration_request_invalid") from None
            if request.installation_id != installation_id:
                raise KeyBindingError("configuration_installation_mismatch")
            request.verify(
                identity=installation.installation_key,
                identity_proof=signed.identity_proof,
                signer_proof=signed.signer_proof,
                actor=actor,
                now=now,
            )
            _check_successor(session, request)
            if session.scalar(
                select(models.ConfigurationKeyRequest.digest).where(
                    models.ConfigurationKeyRequest.installation_id == installation_id,
                    models.ConfigurationKeyRequest.request_id == request.request_id,
                )
            ):
                raise KeyBindingError("configuration_request_replayed")
            session.add(
                models.ConfigurationKeyRequest(
                    digest=request.digest,
                    installation_id=installation_id,
                    request_id=request.request_id,
                    payload=request.payload,
                    identity_proof=signed.identity_proof,
                    signer_proof=signed.signer_proof,
                    requested_by=actor,
                    recorded_at=now,
                )
            )
            return request.digest

        return self._decide(installation_id, actor, now, "requested", decision)

    def approve(self, installation_id: str, digest: str, *, actor: str, now: datetime) -> str:
        def decision(session: Session, installation: models.Installation) -> str:
            row = session.get(models.ConfigurationKeyRequest, digest)
            if row is None or row.installation_id != installation_id:
                raise KeyBindingError("configuration_request_missing")
            request = ConfigurationKeyRequest.model_validate_json(row.payload)
            if request.digest != digest or request.installation_id != installation_id:
                raise KeyBindingError("configuration_request_mismatch")
            if row.requested_by == actor:
                raise KeyBindingError("configuration_independent_approval_required")
            if now < row.recorded_at or now >= request.approval_expires_at:
                raise KeyBindingError("configuration_approval_expired")
            # Recheck the enrolled identity and exact persisted proofs, not the approval body.
            request.verify(
                identity=installation.installation_key,
                identity_proof=row.identity_proof,
                signer_proof=row.signer_proof,
                actor=row.requested_by,
                now=row.recorded_at,
            )
            _check_successor(session, request)
            session.add(
                models.ConfigurationKeyBinding(
                    installation_id=installation_id,
                    version=request.version,
                    request_digest=digest,
                    approved_by=actor,
                    approved_at=now,
                    revoked_at=None,
                )
            )
            return digest

        return self._decide(installation_id, actor, now, "approved", decision)

    def revoke(self, installation_id: str, digest: str, *, actor: str, now: datetime) -> str:
        def decision(session: Session, installation: models.Installation) -> str:
            binding = _head(session, installation_id)
            if (
                binding is None
                or binding.request_digest != digest
                or binding.revoked_at is not None
            ):
                raise KeyBindingError("configuration_binding_conflict")
            if now < binding.approved_at:
                raise KeyBindingError("configuration_binding_conflict")
            binding.revoked_at = now
            return digest

        return self._decide(installation_id, actor, now, "revoked", decision)

    def status(self, installation_id: str) -> dict[str, Any]:
        with self._sessions() as session:
            rows.get_installation(session, installation_id)
            binding = _head(session, installation_id)
            return (
                {
                    "version": binding.version,
                    "request_digest": binding.request_digest,
                    "revoked": binding.revoked_at is not None,
                    "approved_by": binding.approved_by,
                }
                if binding
                else {"version": 0, "request_digest": None, "revoked": False}
            )


def resolve_binding(
    session: Session, installation: models.Installation, version: int, now: datetime
) -> ConfigurationKeyRequest:
    """Resolve current trust only; retained older versions are never substituted."""
    binding = _head(session, installation.installation_id)
    if binding is None or binding.version != version or binding.revoked_at is not None:
        raise KeyBindingError("configuration_binding_unavailable")
    return _verified_binding(session, installation, binding, now)


def resolve_retained_binding(
    session: Session, installation: models.Installation, version: int, accepted_at: datetime
) -> ConfigurationKeyRequest:
    """Verify historical acceptance with its exact key, without granting current permission."""
    binding = session.get(models.ConfigurationKeyBinding, (installation.installation_id, version))
    if binding is None or binding.revoked_at is not None:
        raise KeyBindingError("configuration_history_binding_unavailable")
    return _verified_binding(session, installation, binding, accepted_at)


def _verified_binding(
    session: Session,
    installation: models.Installation,
    binding: models.ConfigurationKeyBinding,
    now: datetime,
) -> ConfigurationKeyRequest:
    row = session.get(models.ConfigurationKeyRequest, binding.request_digest)
    if row is None:
        raise KeyBindingError("configuration_binding_unavailable")
    request = ConfigurationKeyRequest.model_validate_json(row.payload)
    if (
        request.digest != binding.request_digest
        or request.installation_id != installation.installation_id
        or request.version != binding.version
        or request.payload != row.payload
        or request.requester != row.requested_by
        or request.request_id != row.request_id
    ):
        raise KeyBindingError("configuration_binding_mismatch")
    if (
        now < binding.approved_at
        or now >= request.binding_expires_at
        or row.requested_by == binding.approved_by
        or binding.approved_at < row.recorded_at
        or binding.approved_at >= request.approval_expires_at
    ):
        raise KeyBindingError("configuration_binding_expired")
    # Proof freshness applies to registration, not every later package.
    request.verify(
        identity=installation.installation_key,
        identity_proof=row.identity_proof,
        signer_proof=row.signer_proof,
        actor=row.requested_by,
        now=row.recorded_at,
    )
    approval = session.scalar(
        select(models.AuditRecord).where(
            models.AuditRecord.installation_id == installation.installation_id,
            models.AuditRecord.action == "configuration.keys.approved",
            models.AuditRecord.subject == request.digest,
            models.AuditRecord.recorded_at == binding.approved_at,
        )
    )
    if (
        approval is None
        or approval.payload.get("actor") != binding.approved_by
        or approval.record_hash != audit.record_hash(approval)
    ):
        raise KeyBindingError("configuration_binding_unprovable")
    return request


def _head(session: Session, installation_id: str) -> models.ConfigurationKeyBinding | None:
    return session.scalar(
        select(models.ConfigurationKeyBinding)
        .where(models.ConfigurationKeyBinding.installation_id == installation_id)
        .order_by(models.ConfigurationKeyBinding.version.desc())
        .limit(1)
    )


def _check_successor(session: Session, request: ConfigurationKeyRequest) -> None:
    head = _head(session, request.installation_id)
    if request.version != (head.version + 1 if head else 1) or request.predecessor_digest != (
        head.request_digest if head else None
    ):
        raise KeyBindingError("configuration_binding_conflict")
