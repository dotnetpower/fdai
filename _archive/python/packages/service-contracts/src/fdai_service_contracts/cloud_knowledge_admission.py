"""Read-time and pre-activation checks over independently supplied knowledge policy."""

from datetime import datetime, timedelta

from fdai_service_contracts.cloud_knowledge import SourceRegistryRevision
from fdai_service_contracts.cloud_knowledge_package import KnowledgeTrustPolicy
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseBinding


def validate_admitted_binding(
    binding: KnowledgeReleaseBinding,
    *,
    registry: SourceRegistryRevision,
    trust: KnowledgeTrustPolicy,
    now: datetime,
) -> None:
    """Recheck an already admitted record without treating this as a new signature or approval."""
    if now.utcoffset() is None or not binding.imported_at <= now < binding.admission_expires_at:
        raise ValueError("cloud knowledge admission is unavailable or expired")
    if registry.digest != binding.registry_digest or now >= registry.valid_until:
        raise ValueError("cloud knowledge source registry changed or expired")
    declared = {source.source_id: source for source in registry.sources}
    for evidence in binding.sources:
        source = declared.get(evidence.source_id)
        if (
            source is None
            or source.url != evidence.source_url
            or source.applicability != evidence.applicability
            or source.policy != evidence.policy
            or source.license_ref != evidence.license_ref
            or not source.storage_allowed
        ):
            raise ValueError("cloud knowledge source is no longer approved")
    if binding.verified_key_id == "connected-collector":
        if binding.intake_origin not in {"collector", "rollback"}:
            raise ValueError("cloud knowledge intake origin is inconsistent")
        return
    if binding.intake_origin == "collector":
        raise ValueError("collector cannot impersonate an external signing key")
    key = next((item for item in trust.keys if item.key_id == binding.verified_key_id), None)
    if (
        key is None
        or key.key_id in trust.revoked_key_ids
        or not trust.valid_from <= now < trust.valid_until
        or not key.valid_from <= now < key.valid_until
        or not trust.revocation_checked_at
        <= now
        < trust.revocation_checked_at
        + timedelta(
            seconds=trust.revocation_max_age_seconds,
        )
    ):
        raise ValueError("cloud knowledge signing trust is unavailable or revoked")
