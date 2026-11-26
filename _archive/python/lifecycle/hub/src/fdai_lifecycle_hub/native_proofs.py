"""Immutable installation-signed proof transport, without ownership or execution authority."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from fdai_deployment_cli.lifecycle_native import SignedNativeScope
from sqlalchemy import select

from fdai_lifecycle_hub import audit, models, rows, schemas
from fdai_lifecycle_hub.migrations import require_schema
from fdai_lifecycle_hub.native_ownership import NativeOwnershipError
from fdai_lifecycle_hub.store import HubStore

_ACTION = "entity.native_proof_submitted"


class NativeProofStore:
    def __init__(self, store: HubStore) -> None:
        self._store = store

    def submit(
        self,
        installation_id: str,
        proof: SignedNativeScope,
        *,
        principal: str,
        now: datetime,
    ) -> bool:
        principal = schemas.actor_name.validate_python(principal)
        claim = proof.claim
        if claim.installation_id != installation_id:
            raise NativeOwnershipError("native_proof_installation_mismatch")
        subject = "proof-" + hashlib.sha256(claim.entity_id.encode("ascii")).hexdigest()
        with self._store._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            require_schema(session.connection(), "lifecycle_hub")
            if not proof.verify(row.installation_key):
                raise NativeOwnershipError("native_proof_signature_invalid")
            settings = schemas.settings_json.validate_python(row.settings)
            if settings.product != claim.product:
                raise NativeOwnershipError("native_proof_application_mismatch")
            previous = session.scalars(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _ACTION,
                    models.AuditRecord.subject == subject,
                )
            ).one_or_none()
            if previous is not None:
                if previous.payload["proof"] != proof.model_dump(mode="json"):
                    raise NativeOwnershipError("native_proof_claim_conflict")
                return False
            audit.append(
                session,
                now,
                _ACTION,
                installation_id,
                subject,
                {
                    "principal": principal,
                    "claim_digest": claim.digest,
                    "proof": proof.model_dump(mode="json"),
                },
            )
        return True

    def load(self, installation_id: str, claim_digest: str) -> SignedNativeScope:
        """Trusted-host lookup only; acceptance independently revalidates the selected proof."""
        if re.fullmatch(r"sha256:[0-9a-f]{64}", claim_digest, flags=re.ASCII) is None:
            raise NativeOwnershipError("native_proof_digest_invalid")
        with self._store._sessions.begin() as session:
            rows.lock_enrolled(session, installation_id)
            require_schema(session.connection(), "lifecycle_hub")
            records = session.scalars(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _ACTION,
                    models.AuditRecord.payload["claim_digest"].as_string() == claim_digest,
                )
            ).all()
            if len(records) != 1:
                raise NativeOwnershipError("native_proof_not_found")
            proof = SignedNativeScope.model_validate_json(json.dumps(records[0].payload["proof"]))
            if proof.claim.installation_id != installation_id or proof.claim.digest != claim_digest:
                raise NativeOwnershipError("native_proof_record_invalid")
            return proof
