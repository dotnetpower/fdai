"""Additive signed configuration storage; legacy raw configuration is unchanged."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, ForeignKeyConstraint, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fdai_lifecycle_hub.models import Base, ConfigurationKeyBinding, Digest, Identifier


class ConfigurationScopeRequest(Base):
    __tablename__ = "lifecycle_configuration_scope_request"

    digest: Mapped[str] = mapped_column(Digest, primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_installation.installation_id")
    )
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    identity_proof: Mapped[bytes] = mapped_column(LargeBinary)
    requested_by: Mapped[str] = mapped_column(Identifier)
    recorded_at: Mapped[datetime]


class ConfigurationScopeApproval(Base):
    __tablename__ = "lifecycle_configuration_scope_approval"

    digest: Mapped[str] = mapped_column(
        ForeignKey(ConfigurationScopeRequest.digest), primary_key=True
    )
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_installation.installation_id")
    )
    approved_by: Mapped[str] = mapped_column(Identifier)
    approved_at: Mapped[datetime]


class ConfigurationImport(Base):
    """Original ciphertext container and independently attributable acceptance receipt."""

    __tablename__ = "lifecycle_configuration_import"
    __table_args__ = (
        UniqueConstraint("installation_id", "revision_id"),
        ForeignKeyConstraint(
            ["installation_id", "binding_version"],
            [ConfigurationKeyBinding.installation_id, ConfigurationKeyBinding.version],
        ),
    )

    digest: Mapped[str] = mapped_column(Digest, primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_installation.installation_id")
    )
    revision_id: Mapped[str] = mapped_column(String(64))
    predecessor_digest: Mapped[str | None] = mapped_column(ForeignKey(f"{__tablename__}.digest"))
    container: Mapped[bytes] = mapped_column(LargeBinary)
    context: Mapped[bytes] = mapped_column(LargeBinary)
    identity_proof: Mapped[bytes] = mapped_column(LargeBinary)
    binding_version: Mapped[int]
    binding_digest: Mapped[str] = mapped_column(Digest)
    scope_digest: Mapped[str] = mapped_column(ForeignKey(ConfigurationScopeRequest.digest))
    receipt_digest: Mapped[str] = mapped_column(Digest)
    requested_by: Mapped[str] = mapped_column(Identifier)
    imported_at: Mapped[datetime]


class ConfigurationHead(Base):
    __tablename__ = "lifecycle_configuration_head"

    installation_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_installation.installation_id"), primary_key=True
    )
    accepted_digest: Mapped[str] = mapped_column(ForeignKey(ConfigurationImport.digest))
    active_digest: Mapped[str | None] = mapped_column(ForeignKey(ConfigurationImport.digest))
    activated_by: Mapped[str | None] = mapped_column(Identifier)
    activated_at: Mapped[datetime | None]


class ConfigurationChangeApproval(Base):
    __tablename__ = "lifecycle_configuration_change_approval"

    digest: Mapped[str] = mapped_column(ForeignKey(ConfigurationImport.digest), primary_key=True)
    receipt_digest: Mapped[str] = mapped_column(Digest)
    approved_by: Mapped[str] = mapped_column(Identifier)
    approved_at: Mapped[datetime]


class ConfigurationPlanImport(Base):
    """An issued Plan retains its exact accepted import even if a mutable head is lost."""

    __tablename__ = "lifecycle_configuration_plan_import"

    plan_id: Mapped[str] = mapped_column(ForeignKey("lifecycle_plan.plan_id"), primary_key=True)
    import_digest: Mapped[str] = mapped_column(ForeignKey(ConfigurationImport.digest))
    receipt_digest: Mapped[str] = mapped_column(Digest)
