"""Default persisted configuration consumption, without granting same-Release execution."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import models
from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.configuration_import_models import (
    ConfigurationChangeApproval,
    ConfigurationHead,
    ConfigurationImport,
    ConfigurationPlanImport,
)
from fdai_lifecycle_hub.configuration_import_trust import (
    accepted_history,
    candidate_for,
    public_binding,
    require_audit,
    scope_for,
)
from fdai_lifecycle_hub.configuration_key_store import resolve_binding
from fdai_lifecycle_hub.configuration_keys import KeyBindingError


def persisted_candidate(
    session: Session,
    installation: models.Installation,
    catalog: ReleaseCatalog | None,
    now: datetime,
) -> tuple[ConfigurationRevisionCandidate, int] | None:
    """Resolve original accepted bytes and current permission under the caller's owner lock."""
    head = session.get(ConfigurationHead, installation.installation_id)
    if head is None:
        retained_plan = session.scalar(
            select(ConfigurationPlanImport.plan_id)
            .join(models.Plan, models.Plan.plan_id == ConfigurationPlanImport.plan_id)
            .where(models.Plan.installation_id == installation.installation_id)
            .limit(1)
        )
        if retained_plan or session.scalar(
            select(ConfigurationImport.digest)
            .where(ConfigurationImport.installation_id == installation.installation_id)
            .limit(1)
        ):
            raise KeyBindingError("configuration_head_missing")
        return None
    if head.active_digest is None:
        raise KeyBindingError("configuration_not_activated")
    active = session.get(ConfigurationImport, head.active_digest)
    if active is None or active.installation_id != installation.installation_id:
        raise KeyBindingError("configuration_active_revision_missing")
    packages, bindings = accepted_history(session, installation, head.accepted_digest, catalog)
    index = next((i for i, package in enumerate(packages) if package.digest == active.digest), None)
    if index is None:
        raise KeyBindingError("configuration_active_head_fork")
    approval = session.get(ConfigurationChangeApproval, active.digest)
    if (
        approval is None
        or approval.receipt_digest != active.receipt_digest
        or approval.approved_by == active.requested_by
        or not active.imported_at
        <= approval.approved_at
        < active.imported_at + timedelta(minutes=10)
        or head.activated_at is None
        or head.activated_by is None
        or not approval.approved_at <= head.activated_at <= now
        or head.activated_at >= active.imported_at + timedelta(minutes=10)
    ):
        raise KeyBindingError("configuration_activation_unprovable")
    require_audit(
        session,
        installation.installation_id,
        "configuration.change.approved",
        active.receipt_digest,
        approval.approved_by,
        approval.approved_at,
    )
    require_audit(
        session,
        installation.installation_id,
        "configuration.activated",
        active.receipt_digest,
        head.activated_by,
        head.activated_at,
    )
    current = resolve_binding(session, installation, active.binding_version, now)
    if current.digest != active.binding_digest:
        raise KeyBindingError("configuration_binding_mismatch")
    scope = scope_for(session, installation, active.scope_digest, catalog, now)
    return candidate_for(
        packages[index],
        installation.installation_id,
        scope,
        public_binding(current),
        packages[:index],
        bindings[:index],
    ), current.version
