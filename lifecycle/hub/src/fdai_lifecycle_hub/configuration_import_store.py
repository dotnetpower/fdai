"""Atomic import, independent approval and activation on the enrollment owner lock."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from fdai_deployment_cli.lifecycle_configuration_sealing import read_object
from sqlalchemy import Engine, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from fdai_lifecycle_hub import audit, mapping, models, rows
from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.configuration_import_contracts import (
    MAX_HISTORY_BYTES,
    ImportContext,
    ImportDecision,
    ScopeRequest,
    SignedImportRequest,
    SignedScopeRequest,
    decode,
    fresh,
    read_container,
    verify_identity,
)
from fdai_lifecycle_hub.configuration_import_models import (
    ConfigurationChangeApproval,
    ConfigurationHead,
    ConfigurationImport,
    ConfigurationPlanImport,
    ConfigurationScopeApproval,
    ConfigurationScopeRequest,
)
from fdai_lifecycle_hub.configuration_import_trust import (
    accepted_history,
    candidate_for,
    public_binding,
    receipt_digest,
    require_audit,
    scope_for,
    validate_scope,
)
from fdai_lifecycle_hub.configuration_key_store import (
    DevelopmentRecoveryAuthorizationLike,
    resolve_binding,
    single_owner_binding_audited,
)
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.errors import ConcurrentWriteError
from fdai_lifecycle_hub.migrations import require_writable_schema
from fdai_lifecycle_hub.signing import installation_key_id


class ConfigurationImportStore:
    def __init__(self, engine: Engine | Connection) -> None:
        self._begin_sqlite = isinstance(engine, Engine) and engine.dialect.name == "sqlite"
        self._sessions = sessionmaker(
            engine, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )

    def _decide(
        self,
        installation_id: str,
        actor: str,
        now: datetime,
        action: str,
        decision: Callable[[Session, models.Installation], dict[str, Any]],
    ) -> dict[str, Any]:
        failure: KeyBindingError | None = None
        result: dict[str, Any] = {}
        try:
            with self._sessions.begin() as session:
                if self._begin_sqlite:
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                require_writable_schema(session.connection())
                installation = rows.lock_enrolled(session, installation_id)
                try:
                    with session.begin_nested():
                        result = decision(session, installation)
                except ValueError as error:
                    failure = (
                        error
                        if isinstance(error, KeyBindingError)
                        else KeyBindingError("configuration_revision_invalid")
                    )
                audit.append(
                    session,
                    now,
                    action if failure is None else "configuration.import.denied",
                    installation_id,
                    result.get("receipt_digest", result.get("digest", installation_id)),
                    {
                        "actor": actor,
                        "operation": action,
                        "reason": str(failure) if failure else "accepted",
                    },
                )
        except IntegrityError:
            raise ConcurrentWriteError(
                "configuration concurrent write; retry exact request"
            ) from None
        if failure:
            raise failure
        return result

    def deny(self, installation_id: str, *, actor: str, now: datetime, reason: str) -> None:
        def denied(session: Session, installation: models.Installation) -> dict[str, Any]:
            raise KeyBindingError(reason)

        self._decide(installation_id, actor, now, "request", denied)

    def request_scope(
        self,
        installation_id: str,
        signed: SignedScopeRequest,
        *,
        actor: str,
        now: datetime,
        catalog: ReleaseCatalog,
    ) -> dict[str, Any]:
        def decide(session: Session, installation: models.Installation) -> dict[str, Any]:
            payload, proof = decode(signed.signed_payload), decode(signed.identity_proof)
            scope = ScopeRequest.model_validate_json(payload)
            if scope.payload != payload or scope.requester != actor:
                raise KeyBindingError("configuration_scope_identity_mismatch")
            fresh(scope.requested_at, now)
            if now >= scope.approval_expires_at:
                raise KeyBindingError("configuration_scope_expired")
            verify_identity(payload, proof, installation.installation_key)
            validate_scope(session, installation, scope, catalog)
            if session.get(ConfigurationScopeRequest, scope.digest) is not None:
                raise KeyBindingError("configuration_scope_replayed")
            session.add(
                ConfigurationScopeRequest(
                    digest=scope.digest,
                    installation_id=installation_id,
                    payload=payload,
                    identity_proof=proof,
                    requested_by=actor,
                    recorded_at=now,
                )
            )
            return {"digest": scope.digest}

        return self._decide(installation_id, actor, now, "configuration.scope.requested", decide)

    def approve_scope(
        self,
        installation_id: str,
        digest: str,
        *,
        actor: str,
        now: datetime,
        catalog: ReleaseCatalog,
        recovery_authorization: DevelopmentRecoveryAuthorizationLike | None = None,
    ) -> dict[str, Any]:
        def decide(session: Session, installation: models.Installation) -> dict[str, Any]:
            request = session.get(ConfigurationScopeRequest, digest)
            if request is None or request.installation_id != installation_id:
                raise KeyBindingError("configuration_scope_missing")
            scope = ScopeRequest.model_validate_json(request.payload)
            if (
                scope.digest != digest
                or scope.payload != request.payload
                or scope.requester != request.requested_by
                or (
                    actor == request.requested_by
                    and not _single_owner_configuration_allowed(
                        session,
                        installation,
                        actor=actor,
                        now=now,
                        authorization=recovery_authorization,
                    )
                )
                or now < request.recorded_at
                or now >= scope.approval_expires_at
                or session.get(ConfigurationScopeApproval, digest) is not None
            ):
                raise KeyBindingError("configuration_scope_approval_invalid")
            verify_identity(request.payload, request.identity_proof, installation.installation_key)
            validate_scope(session, installation, scope, catalog)
            session.add(
                ConfigurationScopeApproval(
                    digest=digest,
                    installation_id=installation_id,
                    approved_by=actor,
                    approved_at=now,
                )
            )
            return {"digest": digest}

        return self._decide(installation_id, actor, now, "configuration.scope.approved", decide)

    def import_revision(
        self,
        installation_id: str,
        signed: SignedImportRequest,
        *,
        actor: str,
        now: datetime,
        catalog: ReleaseCatalog,
    ) -> dict[str, Any]:
        def decide(session: Session, installation: models.Installation) -> dict[str, Any]:
            context_bytes, proof = decode(signed.signed_payload), decode(signed.identity_proof)
            context = ImportContext.model_validate_json(context_bytes)
            container = decode(signed.signed_container)
            package = read_container(container)
            if (
                context.payload != context_bytes
                or context.requester != actor
                or context.installation_id != installation_id
                or context.package_digest != package.digest
                or context.container_digest != sha256(container).hexdigest()
            ):
                raise KeyBindingError("configuration_import_context_mismatch")
            verify_identity(context_bytes, proof, installation.installation_key)
            approved = resolve_binding(session, installation, context.binding_version, now)
            scope = scope_for(session, installation, context.scope_digest, catalog, now)
            head = session.get(ConfigurationHead, installation_id)
            previous = head.accepted_digest if head else None
            existing = session.get(ConfigurationImport, package.digest)
            if existing is not None:
                if previous != package.digest or existing.installation_id != installation_id:
                    raise KeyBindingError("configuration_old_revision")
                if (
                    existing.container != container
                    or existing.context != context_bytes
                    or existing.identity_proof != proof
                    or existing.binding_digest != approved.digest
                ):
                    raise KeyBindingError("configuration_retry_conflict")
                accepted_history(session, installation, previous, catalog)
                return {"digest": existing.digest, "receipt_digest": existing.receipt_digest}
            fresh(context.requested_at, now)
            if context.predecessor_digest != previous:
                raise KeyBindingError("configuration_predecessor_conflict")
            history, bindings = accepted_history(session, installation, previous, catalog)
            if (
                len(history) >= 256
                or sum(len(item.payload) for item in history) + len(package.payload)
                > MAX_HISTORY_BYTES
            ):
                raise KeyBindingError("configuration_history_full")
            candidate = candidate_for(
                package, installation_id, scope, public_binding(approved), history, bindings
            )
            candidate.resolve(
                scope.release_version,
                catalog.releases[scope.release_version],
                mapping.to_domain(session, installation).managed_entity_ids,
                installation_id=installation_id,
            )
            document = read_object(package.payload)
            revision = document["revision_id"]
            if not isinstance(revision, str):
                raise KeyBindingError("configuration_revision_invalid")
            if session.scalar(
                select(ConfigurationImport.digest).where(
                    ConfigurationImport.installation_id == installation_id,
                    ConfigurationImport.revision_id == revision,
                )
            ):
                raise KeyBindingError("configuration_old_revision")
            row = ConfigurationImport(
                digest=package.digest,
                installation_id=installation_id,
                revision_id=revision,
                predecessor_digest=previous,
                container=container,
                context=context_bytes,
                identity_proof=proof,
                binding_version=approved.version,
                binding_digest=approved.digest,
                scope_digest=scope.digest,
                requested_by=actor,
                imported_at=now.astimezone(UTC),
            )
            row.receipt_digest = receipt_digest(row)
            session.add(row)
            session.flush()
            if head is None:
                session.add(
                    ConfigurationHead(
                        installation_id=installation_id,
                        accepted_digest=row.digest,
                        active_digest=None,
                        activated_by=None,
                        activated_at=None,
                    )
                )
            else:
                head.accepted_digest = row.digest
            return {"digest": row.digest, "receipt_digest": row.receipt_digest}

        return self._decide(installation_id, actor, now, "configuration.import.accepted", decide)

    def approve_change(
        self,
        installation_id: str,
        decision: ImportDecision,
        *,
        actor: str,
        now: datetime,
        catalog: ReleaseCatalog,
        recovery_authorization: DevelopmentRecoveryAuthorizationLike | None = None,
    ) -> dict[str, Any]:
        def decide(session: Session, installation: models.Installation) -> dict[str, Any]:
            row = self._current(session, installation, decision, catalog, now)
            if (
                actor == row.requested_by
                and not _single_owner_configuration_allowed(
                    session,
                    installation,
                    actor=actor,
                    now=now,
                    authorization=recovery_authorization,
                )
                or not row.imported_at <= now < row.imported_at + timedelta(minutes=10)
            ):
                raise KeyBindingError("configuration_change_approval_invalid")
            if session.get(ConfigurationChangeApproval, row.digest) is not None:
                raise KeyBindingError("configuration_change_approval_replayed")
            session.add(
                ConfigurationChangeApproval(
                    digest=row.digest,
                    receipt_digest=row.receipt_digest,
                    approved_by=actor,
                    approved_at=now,
                )
            )
            return {"digest": row.digest, "receipt_digest": row.receipt_digest}

        return self._decide(installation_id, actor, now, "configuration.change.approved", decide)

    def activate(
        self,
        installation_id: str,
        decision: ImportDecision,
        *,
        actor: str,
        now: datetime,
        catalog: ReleaseCatalog,
        recovery_authorization: DevelopmentRecoveryAuthorizationLike | None = None,
    ) -> dict[str, Any]:
        def decide(session: Session, installation: models.Installation) -> dict[str, Any]:
            row = self._current(session, installation, decision, catalog, now)
            approval = session.get(ConfigurationChangeApproval, row.digest)
            if (
                approval is None
                or approval.receipt_digest != row.receipt_digest
                or (
                    approval.approved_by == row.requested_by
                    and not _single_owner_configuration_allowed(
                        session,
                        installation,
                        actor=actor,
                        now=now,
                        authorization=recovery_authorization,
                    )
                )
                or not row.imported_at <= approval.approved_at <= now
                or now >= row.imported_at + timedelta(minutes=10)
            ):
                raise KeyBindingError("configuration_change_unapproved")
            require_audit(
                session,
                installation_id,
                "configuration.change.approved",
                row.receipt_digest,
                approval.approved_by,
                approval.approved_at,
            )
            head = session.get(ConfigurationHead, installation_id)
            if head is None:
                raise KeyBindingError("configuration_head_missing")
            if head.active_digest != row.digest:
                head.active_digest, head.activated_by, head.activated_at = row.digest, actor, now
            return {"digest": row.digest, "receipt_digest": row.receipt_digest}

        return self._decide(installation_id, actor, now, "configuration.activated", decide)

    @staticmethod
    def _current(
        session: Session,
        installation: models.Installation,
        decision: ImportDecision,
        catalog: ReleaseCatalog,
        now: datetime,
    ) -> ConfigurationImport:
        head = session.get(ConfigurationHead, installation.installation_id)
        row = session.get(ConfigurationImport, decision.digest)
        if (
            head is None
            or head.accepted_digest != decision.digest
            or row is None
            or row.installation_id != installation.installation_id
            or row.receipt_digest != decision.receipt_digest
        ):
            raise KeyBindingError("configuration_head_conflict")
        binding = resolve_binding(session, installation, row.binding_version, now)
        if binding.digest != row.binding_digest:
            raise KeyBindingError("configuration_binding_mismatch")
        accepted_history(session, installation, row.digest, catalog)
        scope_for(session, installation, row.scope_digest, catalog, now)
        return row

    def read(self, installation_id: str, digest: str | None = None) -> dict[str, Any]:
        from base64 import b64encode

        with self._sessions() as session:
            rows.get_installation(session, installation_id)
            head = session.get(ConfigurationHead, installation_id)
            if digest is None:
                return {
                    "accepted_digest": head.accepted_digest if head else None,
                    "active_digest": head.active_digest if head else None,
                }
            row = session.get(ConfigurationImport, digest)
            if row is None or row.installation_id != installation_id:
                raise KeyBindingError("configuration_revision_missing")
            return {
                "digest": row.digest,
                "receipt_digest": row.receipt_digest,
                "signed_container": b64encode(row.container).decode("ascii"),
            }

    def read_plan_artifact(
        self,
        installation_id: str,
        plan_id: str,
        active_digest: str,
        digest: str,
        catalog: ReleaseCatalog,
    ) -> dict[str, Any]:
        from base64 import b64encode

        with self._sessions() as session:
            installation = rows.get_installation(session, installation_id)
            retained = session.get(ConfigurationPlanImport, plan_id)
            active = session.get(ConfigurationImport, active_digest)
            if (
                retained is None
                or active is None
                or active.installation_id != installation_id
                or retained.import_digest != active.digest
                or retained.receipt_digest != active.receipt_digest
            ):
                raise KeyBindingError("configuration_plan_receipt_unprovable")
            history, _ = accepted_history(session, installation, active_digest, catalog)
            if digest not in {package.digest for package in history}:
                raise KeyBindingError("configuration_revision_missing")
            row = session.get(ConfigurationImport, digest)
            if row is None or row.installation_id != installation_id:
                raise KeyBindingError("configuration_revision_missing")
            return {
                "digest": row.digest,
                "receipt_digest": row.receipt_digest,
                "signed_container": b64encode(row.container).decode("ascii"),
            }

    def read_scope(self, installation_id: str, digest: str) -> dict[str, Any]:
        with self._sessions() as session:
            row = session.get(ConfigurationScopeRequest, digest)
            if row is None or row.installation_id != installation_id:
                raise KeyBindingError("configuration_scope_missing")
            return {
                "digest": row.digest,
                "request": ScopeRequest.model_validate_json(row.payload).model_dump(mode="json"),
            }


def _single_owner_configuration_allowed(
    session: Session,
    installation: models.Installation,
    *,
    actor: str,
    now: datetime,
    authorization: DevelopmentRecoveryAuthorizationLike | None,
) -> bool:
    if (
        authorization is None
        or not authorization.allow_single_owner_configuration_approval
        or not authorization.is_current(
            installation_id=installation.installation_id,
            operator_id=actor,
            now=now,
        )
        or installation_key_id(installation.installation_key)
        != authorization.replacement_identity_key_id
        or not single_owner_binding_audited(session, installation, actor)
    ):
        return False
    records = session.scalars(
        select(models.AuditRecord).where(
            models.AuditRecord.action == "configuration.identity.development-recovered",
            models.AuditRecord.installation_id == installation.installation_id,
        )
    ).all()
    return any(
        record.payload.get("actor") == actor
        and record.payload.get("scope") == authorization.scope
        and record.payload.get("previous_identity_key_id") == authorization.previous_identity_key_id
        and record.payload.get("replacement_identity_key_id")
        == authorization.replacement_identity_key_id
        for record in records
    )
