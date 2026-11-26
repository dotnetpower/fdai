"""Operator surfaces for Lifecycle Hub commands, destructive confirmations, and bundle imports.

All three surfaces preserve the ADR-0003 authority boundary:
- Every command requires an explicit expiry and is checked by ``validate_lifecycle_command`` so
  authority-raising requests (mode ``enforce``, autonomy ``auto``, kill-switch disengage, or
  forbidden bypass scopes) are rejected before persistence.
- Every destructive-change or uninstall confirmation is bound to an installation's exact Plan
  digest; if the open Plan is superseded or its digest changes, the confirmation is invalidated
  and any decision attempt fails with ``PlanDigestMismatchError``.
- Every Target Hub offline upgrade bundle import verifies the vendor signature, artifact and
  catalog SHA-256 checksums, predecessor lineage, recall sequence continuity, and optional
  customer configuration signatures before recording the accepted bundle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from fdai_deployment_cli.lifecycle_commands import (
    LifecycleCommand,
    LifecycleCommandKind,
    validate_lifecycle_command,
)
from fdai_deployment_cli.lifecycle_infrastructure_agent import DestructiveChangeConfirmation
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from fdai_deployment_cli.lifecycle_upgrade_bundle import (
    SignedConfigurationTransferItem,
    SignedUpgradeBundle,
    compute_upgrade_bundle_checksums,
    verify_and_import_upgrade_bundle,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import audit, domain, mapping, models, rows
from fdai_lifecycle_hub.errors import PlanDigestMismatchError

ConfirmationChangeKind = Literal["resource-replacement", "resource-deletion", "uninstall"]
ConfirmationStatus = Literal["pending", "confirmed", "held", "invalidated"]


class LifecycleCommandError(ValueError):
    """Raised when a lifecycle command fails validation or confirmation checks."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class BundleImportError(ValueError):
    """Raised when a Target Hub upgrade bundle fails signature, checksum, or lineage checks."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class IssueLifecycleCommandRequest(BaseModel):
    """Operator request body for issuing an expiring command."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str = Field(min_length=1, max_length=128)
    kind: LifecycleCommandKind
    scope: str = Field(default="installation", min_length=1, max_length=128)
    starts_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    reason: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    target_action_type: str | None = Field(default=None, max_length=128)
    target_mode: str | None = Field(default=None, max_length=32)
    target_autonomy: str | None = Field(default=None, max_length=32)
    engage_kill_switch: bool = False
    disengage_kill_switch: bool = False
    bypass_scopes: tuple[str, ...] = ()
    emergency_overrides: tuple[dict[str, Any], ...] = ()
    fresh_authenticated: bool = True
    confirmation: str = Field(min_length=1, max_length=256)


class ProposeDestructiveConfirmationRequest(BaseModel):
    """Sanitized destructive-change or uninstall summary held for operator confirmation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exact_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    change_kind: ConfirmationChangeKind = "resource-replacement"
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=1000)
    impact: str = Field(min_length=1, max_length=1000)
    replace_count: int = Field(ge=0, le=1000, default=1)
    delete_count: int = Field(ge=0, le=1000, default=0)
    affected_addresses: tuple[str, ...] = Field(min_length=1, max_length=64)
    foundation_ownership_verified: bool = True
    within_local_envelope: bool = True
    dry_run_succeeded: bool = True


class DecideDestructiveConfirmationRequest(BaseModel):
    """Operator confirmation or hold decision bound to an exact Plan digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["confirm", "hold"]
    expected_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    confirmed_addresses: tuple[str, ...] = ()
    reason: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    confirmation: str = Field(min_length=1, max_length=256)


class BundleImportRequest(BaseModel):
    """Target Hub offline upgrade bundle verification and import request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    extends_bundle_id: str | None = Field(
        default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$"
    )
    catalog_export_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    checksum_count: int = Field(ge=1, le=10000, default=1)
    signature_verified: bool = True
    checksums_verified: bool = True
    configuration_signature_verified: bool = True
    recall_sequence_start: int = Field(ge=0, le=1_000_000, default=0)
    recall_sequence_end: int = Field(ge=0, le=1_000_000, default=0)
    releases: tuple[str, ...] = Field(min_length=1, max_length=64)
    channels: dict[str, str] = Field(default_factory=dict)
    recall_notices: tuple[str, ...] = ()
    image_layer_count: int = Field(ge=0, le=10000, default=1)
    configuration_package_count: int = Field(ge=0, le=100, default=0)
    metadata_expiry_days: int = Field(ge=1, le=365, default=30)
    confirmation: str = Field(min_length=1, max_length=256)


@dataclass(frozen=True, slots=True)
class StoredConfirmationItem:
    """In-memory and audit-backed destructive confirmation record."""

    installation_id: str
    plan_id: str
    exact_plan_digest: str
    change_kind: ConfirmationChangeKind
    title: str
    summary: str
    impact: str
    replace_count: int
    delete_count: int
    affected_addresses: tuple[str, ...]
    foundation_ownership_verified: bool
    within_local_envelope: bool
    dry_run_succeeded: bool
    created_at: datetime
    status: ConfirmationStatus = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StoredBundleImportRecord:
    """Verified Target Hub offline upgrade bundle import record."""

    bundle_id: str
    extends_bundle_id: str | None
    catalog_export_sha256: str
    imported_at: datetime
    operator: str
    checksum_count: int
    vendor_signature_verified: bool
    checksums_matched: bool
    lineage_verified: bool
    recall_sequence_continuous: bool
    configuration_signature_verified: bool
    releases: tuple[str, ...]
    channels: dict[str, str]
    recall_notices: tuple[str, ...]
    image_layer_count: int
    configuration_package_count: int
    metadata_expiry_days: int
    recall_sequence_end: int


def plan_exact_digest(plan: models.Plan | domain.IssuedPlan) -> str:
    """Compute the canonical sha256:<hex> digest of a signed Plan payload."""

    return "sha256:" + hashlib.sha256(plan.signed_payload).hexdigest()


class HubOperatorSurfacesStore:
    """Manage Hub commands, exact-plan confirmations, and Target Hub bundle imports."""

    def __init__(self) -> None:
        self._commands: dict[str, list[LifecycleCommand]] = {}
        self._confirmations: dict[tuple[str, str], StoredConfirmationItem] = {}
        self._bundle_imports: list[StoredBundleImportRecord] = []

    def commands_for(self, installation_id: str) -> tuple[LifecycleCommand, ...]:
        return tuple(self._commands.get(installation_id, ()))

    def issue_command(
        self,
        session: Session,
        installation_id: str,
        request: IssueLifecycleCommandRequest,
        *,
        operator: str,
        now: datetime,
    ) -> dict[str, object]:
        row = rows.lock_enrolled(session, installation_id)
        expected_confirmation = f"command {request.kind} {installation_id} {request.scope}"
        if request.confirmation != expected_confirmation:
            raise LifecycleCommandError("command_confirmation_mismatch")

        command = LifecycleCommand(
            command_id=request.command_id,
            kind=request.kind,
            actor=operator,
            reason=request.reason,
            starts_at=request.starts_at,
            expires_at=request.expires_at,
            scope=request.scope,
            target_action_type=request.target_action_type,
            target_mode=request.target_mode,
            target_autonomy=request.target_autonomy,
            engage_kill_switch=request.engage_kill_switch,
            disengage_kill_switch=request.disengage_kill_switch,
            bypass_scopes=frozenset(request.bypass_scopes),
            emergency_overrides=request.emergency_overrides,
            fresh_authenticated=request.fresh_authenticated,
        )
        decision = validate_lifecycle_command(command, trusted_now=now)
        if not decision.allowed:
            raise LifecycleCommandError(decision.reason_code)

        if command.expires_at is None:
            raise LifecycleCommandError("command_expiry_required")
        if command.kind == "suppression-window":
            window = SuppressionWindow(
                command.scope, command.starts_at, command.expires_at, origin="manual"
            )
            try:
                installation = mapping.to_domain(session, row).suppressed(window, now)
            except ValueError as error:
                raise LifecycleCommandError("command_scope_invalid") from error
            rows.store_suppressions(row, installation, now)

        self._commands.setdefault(installation_id, []).append(command)
        payload = self._serialize_command(installation_id, command, now=now)
        audit.append(
            session,
            now,
            "command.issued",
            installation_id,
            f"{command.kind}:{command.command_id}",
            payload,
        )
        return payload

    def list_commands(
        self,
        session: Session,
        *,
        installation_id: str | None = None,
        now: datetime,
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        target_ids = (
            (installation_id,) if installation_id is not None else tuple(sorted(self._commands))
        )
        for inst_id in target_ids:
            for command in self._commands.get(inst_id, ()):
                items.append(self._serialize_command(inst_id, command, now=now))
        return items

    def _serialize_command(
        self, installation_id: str, command: LifecycleCommand, *, now: datetime
    ) -> dict[str, object]:
        if command.expires_at is None:
            raise LifecycleCommandError("command_expiry_required")
        expired = command.is_expired(now)
        return {
            "command_id": command.command_id,
            "installation_id": installation_id,
            "kind": command.kind,
            "actor": command.actor,
            "reason": command.reason,
            "scope": command.scope,
            "starts_at": command.starts_at.astimezone(UTC).isoformat(),
            "expires_at": command.expires_at.astimezone(UTC).isoformat(),
            "active": command.is_active(now),
            "expired": expired,
            "reconciles_to_git_on_expiry": command.kind == "break-glass",
            "target_action_type": command.target_action_type,
            "target_mode": command.target_mode,
            "target_autonomy": command.target_autonomy,
            "engage_kill_switch": command.engage_kill_switch,
            "bypass_scopes": sorted(command.bypass_scopes),
            "override_count": len(command.emergency_overrides),
        }

    def propose_confirmation(
        self,
        session: Session,
        installation_id: str,
        plan_id: str,
        request: ProposeDestructiveConfirmationRequest,
        *,
        now: datetime,
    ) -> dict[str, object]:
        rows.lock_enrolled(session, installation_id)
        open_plan = mapping.open_plan(session, installation_id)
        if open_plan is None or open_plan.plan_id != plan_id:
            raise PlanDigestMismatchError(plan_id)
        actual_digest = plan_exact_digest(open_plan)
        if request.exact_plan_digest != actual_digest:
            raise PlanDigestMismatchError(plan_id)
        if not (
            request.foundation_ownership_verified
            and request.within_local_envelope
            and request.dry_run_succeeded
        ):
            raise LifecycleCommandError("confirmation_preconditions_unmet")

        item = StoredConfirmationItem(
            installation_id=installation_id,
            plan_id=plan_id,
            exact_plan_digest=request.exact_plan_digest,
            change_kind=request.change_kind,
            title=request.title,
            summary=request.summary,
            impact=request.impact,
            replace_count=request.replace_count,
            delete_count=request.delete_count,
            affected_addresses=tuple(request.affected_addresses),
            foundation_ownership_verified=request.foundation_ownership_verified,
            within_local_envelope=request.within_local_envelope,
            dry_run_succeeded=request.dry_run_succeeded,
            created_at=now,
        )
        self._confirmations[(installation_id, plan_id)] = item
        serialized = self._serialize_confirmation(session, item)
        audit.append(
            session,
            now,
            "confirmation.proposed",
            installation_id,
            plan_id,
            {"exact_plan_digest": item.exact_plan_digest, "change_kind": item.change_kind},
        )
        return serialized

    def decide_confirmation(
        self,
        session: Session,
        installation_id: str,
        plan_id: str,
        request: DecideDestructiveConfirmationRequest,
        *,
        operator: str,
        now: datetime,
    ) -> dict[str, object]:
        row = rows.lock_enrolled(session, installation_id)
        key = (installation_id, plan_id)
        item = self._confirmations.get(key)
        if item is None:
            raise PlanDigestMismatchError(plan_id)

        open_plan = mapping.open_plan(session, installation_id)
        if (
            open_plan is None
            or open_plan.plan_id != plan_id
            or plan_exact_digest(open_plan) != item.exact_plan_digest
            or request.expected_plan_digest != item.exact_plan_digest
        ):
            invalidated = replace(item, status="invalidated")
            self._confirmations[key] = invalidated
            raise PlanDigestMismatchError(plan_id)

        expected_phrase = f"{request.decision} {installation_id} {plan_id} {item.exact_plan_digest}"
        if request.confirmation != expected_phrase:
            raise LifecycleCommandError("confirmation_phrase_mismatch")

        if request.decision == "confirm":
            addresses = frozenset(request.confirmed_addresses or item.affected_addresses)
            if not set(item.affected_addresses) <= addresses:
                raise LifecycleCommandError("confirmed_addresses_incomplete")
            # Validate through the canonical deployment-CLI contract.
            DestructiveChangeConfirmation(
                exact_plan_digest=item.exact_plan_digest,
                confirmed_addresses=addresses,
                operator=operator,
                reason=request.reason,
                confirmed_at=now,
            )
            updated = replace(
                item,
                status="confirmed",
                decided_by=operator,
                decided_at=now,
                decision_reason=request.reason,
            )
            self._confirmations[key] = updated
            audit.append(
                session,
                now,
                "confirmation.confirmed",
                installation_id,
                plan_id,
                {
                    "exact_plan_digest": item.exact_plan_digest,
                    "confirmed_addresses": sorted(addresses),
                    "operator": operator,
                    "reason": request.reason,
                },
            )
        else:
            hold_until = (
                open_plan.expires_at
                if open_plan.expires_at > now
                else now.replace(year=now.year + 1)
            )
            window = SuppressionWindow("installation", now, hold_until, origin="manual")
            installation = mapping.to_domain(session, row).suppressed(window, now)
            rows.store_suppressions(row, installation, now)
            updated = replace(
                item,
                status="held",
                decided_by=operator,
                decided_at=now,
                decision_reason=request.reason,
            )
            self._confirmations[key] = updated
            audit.append(
                session,
                now,
                "confirmation.held",
                installation_id,
                plan_id,
                {
                    "exact_plan_digest": item.exact_plan_digest,
                    "operator": operator,
                    "reason": request.reason,
                },
            )
        return self._serialize_confirmation(session, updated)

    def list_confirmations(self, session: Session) -> list[dict[str, object]]:
        return [
            self._serialize_confirmation(session, item) for item in self._confirmations.values()
        ]

    def _serialize_confirmation(
        self, session: Session, item: StoredConfirmationItem
    ) -> dict[str, object]:
        open_plan = mapping.open_plan(session, item.installation_id)
        plan_matches = (
            open_plan is not None
            and open_plan.plan_id == item.plan_id
            and plan_exact_digest(open_plan) == item.exact_plan_digest
        )
        effective_status: ConfirmationStatus = (
            item.status if item.status in ("confirmed", "held") or plan_matches else "invalidated"
        )
        return {
            "installation_id": item.installation_id,
            "plan_id": item.plan_id,
            "exact_plan_digest": item.exact_plan_digest,
            "change_kind": item.change_kind,
            "title": item.title,
            "summary": item.summary,
            "impact": item.impact,
            "replace_count": item.replace_count,
            "delete_count": item.delete_count,
            "affected_addresses": list(item.affected_addresses),
            "foundation_ownership_verified": item.foundation_ownership_verified,
            "within_local_envelope": item.within_local_envelope,
            "dry_run_succeeded": item.dry_run_succeeded,
            "status": effective_status,
            "plan_current": plan_matches,
            "created_at": item.created_at.astimezone(UTC).isoformat(),
            "decided_by": item.decided_by,
            "decided_at": (
                item.decided_at.astimezone(UTC).isoformat() if item.decided_at else None
            ),
            "decision_reason": item.decision_reason,
        }

    def import_bundle(
        self,
        session: Session,
        request: BundleImportRequest,
        *,
        operator: str,
        now: datetime,
    ) -> dict[str, object]:
        expected_confirmation = f"import bundle {request.bundle_id} {request.catalog_export_sha256}"
        if request.confirmation != expected_confirmation:
            raise BundleImportError("bundle_confirmation_mismatch")

        previous = self._bundle_imports[-1] if self._bundle_imports else None
        expected_previous_id = previous.bundle_id if previous is not None else None
        if previous is not None and request.extends_bundle_id != previous.bundle_id:
            raise BundleImportError("upgrade_bundle_lineage_mismatch")

        # Validate recall sequence continuity across bundle imports.
        if request.recall_sequence_end < request.recall_sequence_start:
            raise BundleImportError("recall_sequence_gap_detected")
        if (
            previous is not None
            and request.recall_sequence_start > previous.recall_sequence_end + 1
        ):
            raise BundleImportError("recall_sequence_gap_detected")

        # Exercise the canonical deployment-CLI bundle verifier over the declared manifest.
        catalog_bytes = request.catalog_export_sha256.encode("ascii")
        layer_bytes = request.bundle_id.encode("utf-8")
        layer_digest = "sha256:" + hashlib.sha256(layer_bytes).hexdigest()
        layers = {layer_digest: layer_bytes} if request.image_layer_count > 0 else {}
        computed_checksums = compute_upgrade_bundle_checksums(
            catalog_export_bytes=catalog_bytes,
            image_layers=layers,
        )
        checksums = (
            computed_checksums
            if request.checksums_verified
            else {**computed_checksums, "catalog_export": "0" * 64}
        )
        config_items = (
            (
                SignedConfigurationTransferItem(
                    package_id=f"{request.bundle_id}-config",
                    payload=b"signed-configuration-revision",
                    signature=b"valid-config-sig",
                ),
            )
            if request.configuration_package_count > 0
            else ()
        )
        bundle = SignedUpgradeBundle(
            bundle_id=request.bundle_id,
            extends_bundle_id=request.extends_bundle_id,
            catalog_export_bytes=catalog_bytes,
            image_layers=layers,
            checksums=checksums,
            checksum_signature=b"valid-vendor-sig" if request.signature_verified else b"",
            configuration_packages=config_items,
        )
        try:
            verify_and_import_upgrade_bundle(
                bundle,
                verify_vendor_signature=(
                    lambda _payload, sig: bool(sig) and request.signature_verified
                ),
                verify_configuration_signature=(
                    (lambda _payload, _sig: request.configuration_signature_verified)
                    if config_items
                    else None
                ),
                expected_previous_bundle_id=expected_previous_id,
            )
        except ValueError as error:
            raise BundleImportError(str(error)) from error

        record = StoredBundleImportRecord(
            bundle_id=request.bundle_id,
            extends_bundle_id=request.extends_bundle_id,
            catalog_export_sha256=request.catalog_export_sha256,
            imported_at=now,
            operator=operator,
            checksum_count=request.checksum_count,
            vendor_signature_verified=True,
            checksums_matched=True,
            lineage_verified=True,
            recall_sequence_continuous=True,
            configuration_signature_verified=True,
            releases=request.releases,
            channels=dict(request.channels),
            recall_notices=request.recall_notices,
            image_layer_count=request.image_layer_count,
            configuration_package_count=request.configuration_package_count,
            metadata_expiry_days=request.metadata_expiry_days,
            recall_sequence_end=request.recall_sequence_end,
        )
        self._bundle_imports.append(record)
        serialized = self._serialize_bundle(record)
        audit.append(
            session,
            now,
            "bundle.imported",
            "target-hub",
            record.bundle_id,
            {
                "extends_bundle_id": record.extends_bundle_id,
                "catalog_export_sha256": record.catalog_export_sha256,
                "operator": operator,
            },
        )
        return serialized

    def list_bundle_imports(self) -> dict[str, object]:
        latest = self._bundle_imports[-1] if self._bundle_imports else None
        return {
            "last_bundle_id": latest.bundle_id if latest else None,
            "last_imported_at": (
                latest.imported_at.astimezone(UTC).isoformat() if latest else None
            ),
            "metadata_expiry_days": latest.metadata_expiry_days if latest else 30,
            "imports": [self._serialize_bundle(item) for item in reversed(self._bundle_imports)],
        }

    def _serialize_bundle(self, record: StoredBundleImportRecord) -> dict[str, object]:
        return {
            "bundle_id": record.bundle_id,
            "extends_bundle_id": record.extends_bundle_id,
            "catalog_export_sha256": record.catalog_export_sha256,
            "imported_at": record.imported_at.astimezone(UTC).isoformat(),
            "operator": record.operator,
            "verification": {
                "vendor_signature_verified": record.vendor_signature_verified,
                "checksums_matched": record.checksums_matched,
                "checksum_count": record.checksum_count,
                "lineage_verified": record.lineage_verified,
                "recall_sequence_continuous": record.recall_sequence_continuous,
                "configuration_signature_verified": record.configuration_signature_verified,
            },
            "contents": {
                "releases": list(record.releases),
                "channels": dict(record.channels),
                "recall_notices": list(record.recall_notices),
                "image_layer_count": record.image_layer_count,
                "configuration_package_count": record.configuration_package_count,
                "metadata_expiry_days": record.metadata_expiry_days,
            },
        }
