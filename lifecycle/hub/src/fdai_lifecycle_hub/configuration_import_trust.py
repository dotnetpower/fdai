"""Reconstruct import trust from original bytes, exact bindings and attributed receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_configuration_package import (
    ConfigurationHistoryBinding,
    SignedConfigurationPackage,
    verify_configuration_history,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import encryption_key_digest, read_object
from sqlalchemy import select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import audit, mapping, models
from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.configuration_import_contracts import (
    MAX_HISTORY_BYTES,
    ImportContext,
    ScopeRequest,
    read_container,
    verify_identity,
)
from fdai_lifecycle_hub.configuration_import_models import (
    ConfigurationImport,
    ConfigurationScopeApproval,
    ConfigurationScopeRequest,
)
from fdai_lifecycle_hub.configuration_key_store import (
    resolve_retained_binding,
    single_owner_binding_audited,
)
from fdai_lifecycle_hub.configuration_keys import ConfigurationKeyRequest, KeyBindingError


def public_binding(request: ConfigurationKeyRequest) -> ConfigurationHistoryBinding:
    return ConfigurationHistoryBinding(
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(request.configuration_signing_key)),
        encryption_key_digest(
            X25519PublicKey.from_public_bytes(bytes.fromhex(request.installation_encryption_key))
        ),
    )


def scope_for(
    session: Session,
    installation: models.Installation,
    digest: str,
    catalog: ReleaseCatalog | None,
    now: datetime,
    *,
    historical: bool = False,
) -> ScopeRequest:
    """Historical selection is only for ancestors with already verified acceptance receipts."""
    row = session.get(ConfigurationScopeRequest, digest)
    approval = session.get(ConfigurationScopeApproval, digest)
    if row is None or approval is None:
        raise KeyBindingError("configuration_scope_unapproved")
    scope = ScopeRequest.model_validate_json(row.payload)
    if (
        scope.digest != digest
        or scope.payload != row.payload
        or scope.installation_id != installation.installation_id
        or row.installation_id != installation.installation_id
        or approval.installation_id != installation.installation_id
        or row.requested_by != scope.requester
        or (
            row.requested_by == approval.approved_by
            and not single_owner_binding_audited(session, installation, approval.approved_by)
        )
        or approval.approved_at < row.recorded_at
        or approval.approved_at >= scope.approval_expires_at
        or now < approval.approved_at
        or now >= scope.expires_at
    ):
        raise KeyBindingError("configuration_scope_unavailable")
    verify_identity(row.payload, row.identity_proof, installation.installation_key)
    require_audit(
        session,
        installation.installation_id,
        "configuration.scope.approved",
        digest,
        approval.approved_by,
        approval.approved_at,
    )
    if (
        not historical
        and frozenset(scope.entity_bindings)
        != mapping.to_domain(session, installation).managed_entity_ids
    ):
        raise KeyBindingError("configuration_entity_scope_mismatch")
    if catalog is not None:
        if historical:
            _validate_release_scope(scope, catalog)
        else:
            validate_scope(session, installation, scope, catalog)
    return scope


def validate_scope(
    session: Session,
    installation: models.Installation,
    scope: ScopeRequest,
    catalog: ReleaseCatalog,
) -> None:
    selected = mapping.to_domain(session, installation).managed_entity_ids
    if (
        frozenset(scope.entity_bindings) != selected
        or scope.installation_id != installation.installation_id
    ):
        raise KeyBindingError("configuration_entity_scope_mismatch")
    _validate_release_scope(scope, catalog)


def _validate_release_scope(scope: ScopeRequest, catalog: ReleaseCatalog) -> None:
    release = catalog.releases.get(scope.release_version)
    if (
        release is None
        or release.digest != scope.release_digest
        or release.configuration_schema is None
        or release.configuration_schema.digest != scope.schema_digest
    ):
        raise KeyBindingError("configuration_release_scope_mismatch")


def candidate_for(
    package: SignedConfigurationPackage,
    installation_id: str,
    scope: ScopeRequest,
    binding: ConfigurationHistoryBinding,
    history: tuple[SignedConfigurationPackage, ...],
    history_bindings: tuple[ConfigurationHistoryBinding, ...],
) -> ConfigurationRevisionCandidate:
    return ConfigurationRevisionCandidate(
        package=package,
        installation_id=installation_id,
        entity_bindings=tuple(sorted(scope.entity_bindings.items())),
        configuration_key=binding.configuration_key,
        installation_key_digest=binding.installation_key_digest,
        sealed_keys=frozenset(scope.sealed_keys),
        expected_predecessor=history[-1].digest if history else None,
        history=history,
        history_bindings=history_bindings,
    )


def receipt_digest(row: ConfigurationImport) -> str:
    return canonical_digest(
        {
            "format": "fdai.configuration-acceptance.v1",
            "package_digest": row.digest,
            "installation_id": row.installation_id,
            "revision_id": row.revision_id,
            "predecessor_digest": row.predecessor_digest,
            "container_digest": sha256(row.container).hexdigest(),
            "context_digest": sha256(row.context).hexdigest(),
            "identity_proof_digest": sha256(row.identity_proof).hexdigest(),
            "binding_version": row.binding_version,
            "binding_digest": row.binding_digest,
            "scope_digest": row.scope_digest,
            "requested_by": row.requested_by,
            "imported_at": row.imported_at.astimezone(UTC).isoformat(),
        }
    )


def require_audit(
    session: Session,
    installation_id: str,
    action: str,
    subject: str,
    actor: str,
    at: datetime,
) -> None:
    record = session.scalar(
        select(models.AuditRecord).where(
            models.AuditRecord.installation_id == installation_id,
            models.AuditRecord.action == action,
            models.AuditRecord.subject == subject,
            models.AuditRecord.recorded_at == at,
        )
    )
    if (
        record is None
        or record.payload.get("actor") != actor
        or record.record_hash != audit.record_hash(record)
    ):
        raise KeyBindingError("configuration_receipt_unprovable")


def accepted_history(
    session: Session,
    installation: models.Installation,
    digest: str | None,
    catalog: ReleaseCatalog | None,
) -> tuple[tuple[SignedConfigurationPackage, ...], tuple[ConfigurationHistoryBinding, ...]]:
    """Walk the retained head, then verify every ancestor with its accepted role binding."""
    reverse: list[ConfigurationImport] = []
    seen: set[str] = set()
    while digest is not None:
        if digest in seen or len(reverse) >= 256:
            raise KeyBindingError("configuration_history_invalid")
        seen.add(digest)
        row = session.get(ConfigurationImport, digest)
        if row is None or row.installation_id != installation.installation_id:
            raise KeyBindingError("configuration_history_missing")
        reverse.append(row)
        digest = row.predecessor_digest
    packages: tuple[SignedConfigurationPackage, ...] = ()
    bindings: tuple[ConfigurationHistoryBinding, ...] = ()
    for row in reversed(reverse):
        if row.receipt_digest != receipt_digest(row):
            raise KeyBindingError("configuration_receipt_mismatch")
        require_audit(
            session,
            installation.installation_id,
            "configuration.import.accepted",
            row.receipt_digest,
            row.requested_by,
            row.imported_at,
        )
        context = ImportContext.model_validate_json(row.context)
        package = read_container(row.container)
        verify_identity(row.context, row.identity_proof, installation.installation_key)
        document = read_object(package.payload)
        if (
            context.payload != row.context
            or context.installation_id != installation.installation_id
            or context.requester != row.requested_by
            or context.package_digest != row.digest
            or package.digest != row.digest
            or context.container_digest != sha256(row.container).hexdigest()
            or context.scope_digest != row.scope_digest
            or context.binding_version != row.binding_version
            or context.predecessor_digest != row.predecessor_digest
            or document.get("revision_id") != row.revision_id
        ):
            raise KeyBindingError("configuration_receipt_mismatch")
        approved = resolve_retained_binding(
            session, installation, row.binding_version, row.imported_at
        )
        if approved.digest != row.binding_digest:
            raise KeyBindingError("configuration_history_binding_mismatch")
        scope = scope_for(
            session, installation, row.scope_digest, catalog, row.imported_at, historical=True
        )
        binding = public_binding(approved)
        if catalog is not None:
            candidate_for(
                package, installation.installation_id, scope, binding, packages, bindings
            ).resolve(
                scope.release_version,
                catalog.releases[scope.release_version],
                frozenset(scope.entity_bindings),
                installation_id=installation.installation_id,
            )
        packages += (package,)
        bindings += (binding,)
        if sum(len(item.payload) for item in packages) > MAX_HISTORY_BYTES:
            raise KeyBindingError("configuration_history_full")
    verify_configuration_history(packages, bindings=bindings)
    return packages, bindings
