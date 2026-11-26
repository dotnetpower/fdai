"""Separate operator acceptance of installation-signed, actual native creation evidence."""

from __future__ import annotations

from datetime import datetime

from fdai_deployment_cli.lifecycle_native import NativeOwnershipAcceptance
from sqlalchemy import select

from fdai_lifecycle_hub import audit, mapping, models, rows, schemas
from fdai_lifecycle_hub.entity import OwnershipEvidence
from fdai_lifecycle_hub.execution_settings import settings_digest
from fdai_lifecycle_hub.migrations import require_schema
from fdai_lifecycle_hub.store import HubStore

NATIVE_ENTITY_KIND = "native-workload-scope"
_ACTION = "entity.native_creation_accepted"


class NativeOwnershipError(ValueError):
    """Stable denial reason, without private scope or proof values."""


class NativeOwnershipStore:
    def __init__(self, store: HubStore) -> None:
        self._store = store

    def accept(
        self,
        installation_id: str,
        command: NativeOwnershipAcceptance,
        *,
        operator: str,
        now: datetime,
    ) -> dict[str, object]:
        operator = schemas.actor_name.validate_python(operator)
        claim = command.proof.claim
        if claim.installation_id != installation_id:
            raise NativeOwnershipError("native_ownership_installation_mismatch")
        subject = "native-" + command.request_id.hex
        with self._store._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            require_schema(session.connection(), "lifecycle_hub")
            previous = session.scalars(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _ACTION,
                    models.AuditRecord.subject == subject,
                )
            ).one_or_none()
            if previous is not None:
                if (
                    previous.payload["request_digest"] != command.digest
                    or previous.payload["operator"] != operator
                ):
                    raise NativeOwnershipError("native_ownership_request_conflict")
                return {"changed": False, "claim_digest": previous.payload["claim_digest"]}
            installation = mapping.to_domain(session, row)
            if settings_digest(installation.settings) != command.expected_settings_digest:
                raise NativeOwnershipError("native_ownership_revision_conflict")
            if command.confirmation != command.required_confirmation:
                raise NativeOwnershipError("native_ownership_confirmation_mismatch")
            if installation.settings.product != claim.product:
                raise NativeOwnershipError("native_ownership_application_mismatch")
            if installation.open_plan is not None:
                raise NativeOwnershipError("native_ownership_plan_pending")
            if not command.proof.verify(row.installation_key):
                raise NativeOwnershipError("native_ownership_signature_invalid")
            entity = session.scalars(
                select(models.Entity).where(
                    models.Entity.installation_id == installation_id,
                    models.Entity.entity_id == claim.entity_id,
                )
            ).one_or_none()
            if entity is not None and (
                entity.kind != NATIVE_ENTITY_KIND
                or entity.ownership is not None
                or entity.settings is not None
            ):
                raise NativeOwnershipError("native_ownership_entity_already_bound")
            state = installation.reported.entities.get(claim.entity_id)
            if state is not None and state.release_id is not None:
                raise NativeOwnershipError("native_ownership_requires_uninstalled_entity")
            if entity is None:
                entity = models.Entity(
                    installation_id=installation_id,
                    entity_id=claim.entity_id,
                    kind=NATIVE_ENTITY_KIND,
                    recorded_at=now,
                )
                session.add(entity)
            entity.ownership = schemas.ownership_json.dump_python(
                OwnershipEvidence(native_creation_receipt_digest=claim.digest), mode="json"
            )
            entity.recorded_at = now
            audit.append(
                session,
                now,
                _ACTION,
                installation_id,
                subject,
                {
                    "operator": operator,
                    "request_digest": command.digest,
                    "claim_digest": claim.digest,
                    "entity_id": claim.entity_id,
                    "proof": command.proof.model_dump(mode="json"),
                    "settings_digest": command.expected_settings_digest,
                    "reason": command.reason,
                },
            )
        return {"changed": True, "claim_digest": claim.digest}
