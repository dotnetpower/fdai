"""Durable exact-artifact capability-bundle lifecycle lineage coordinator (#2315 / X01).

This module orchestrates and verifies the complete governed lifecycle for one
FDAI-owned, metadata-only, read-only ``skill_bundle`` artifact across:

1. Disabled-first installation with Ed25519 domain-separated signature verification;
2. Distinct reviewed enablement through the typed action path
   (``governance.capability-bundle-enable``) with independent disclosure readback;
3. Disablement and revocation with independent disclosure readback after each transition;
4. Post-revocation activation refusal preserving publisher, digest, revision, actor,
   idempotency, and Saga audit lineage; and
5. Cold runtime restart reconstruction from durable ``TrustedArtifactStore`` and
   ``SkillRevocationStore`` records without synthetic records or mutable-history rewrites.

No transition grants execution, approval, promotion, deployment, or managed-resource
authority.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.composition.wire_skill_disclosure import (
    SkillDisclosureStartupBinding,
    compose_runtime_skill_disclosure_startup,
)
from fdai.core.skills import (
    RuntimeSkillDisclosure,
    SkillBundleCatalog,
    SkillBundleLifecycle,
    SkillCatalog,
    parse_skill_bundle_manifest,
    parse_skill_markdown,
)
from fdai.core.supply_chain import (
    TrustedArtifactInstaller,
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    TrustedArtifactStore,
)
from fdai.core.supply_chain.skill_quarantine import (
    SkillRevocation,
    SkillRevocationStore,
)
from fdai.delivery.capability_bundle_lifecycle_models import (
    _DISPATCH_GUARD,
    BUNDLE_CAPABILITY_ID,
    BUNDLE_ENABLE_ACTION_TYPE_ID,
    CI_RECEIPT_SIGNATURE_DOMAIN,
    PINNED_CI_ATTESTATION_PUBLIC_KEY_HEX,
    PINNED_MAIN_2940_CI_RECEIPT,
    PINNED_MAIN_2940_CI_SIGNATURE_HEX,
    SKILL_BUNDLE_SIGNATURE_DOMAIN,
    SKILL_SIGNATURE_DOMAIN,
    Ed25519DomainSkillBundleVerifier,
    Ed25519DomainSkillVerifier,
    PinnedBundleArtifactSpec,
    ReviewedBundleEnableAction,
    RevokedCapabilityBundleError,
    TypedBundleEnableActionDispatcher,
    VerifiedSourceCiReceipt,
    _SagaAuditAdapter,
    _VerifiedEnableDispatchToken,
    build_disclosure_readback_snapshot,
    build_pinned_fdai_bundle_artifact,
    build_refused_enable_receipt_and_audit,
    build_restart_reconstruct_receipt_and_audit,
    build_transition_receipt_and_audit,
)
from fdai.shared.providers.state_store import StateStore

_STATE_KEY_PREFIX = "capability-bundle-lifecycle:v1:"


class GovernedSkillBundleLifecycleCoordinator:
    """Execute and retain exact-artifact lifecycle transitions with Saga audit lineage."""

    def __init__(
        self,
        *,
        spec: PinnedBundleArtifactSpec,
        artifact_store: TrustedArtifactStore,
        revocation_store: SkillRevocationStore,
        state_store: StateStore,
        available_tools: frozenset[str] = frozenset({"query_inventory"}),
        known_agents: frozenset[str] = frozenset({"Bragi", "Saga"}),
        clock: Callable[[], datetime] | None = None,
        owner_id: str | None = None,
        reservation_lease_seconds: int = 300,
    ) -> None:
        self._spec = spec
        self._artifact_store = artifact_store
        self._revocation_store = revocation_store
        self._state_store = state_store
        self._available_tools = available_tools
        self._known_agents = known_agents
        self._clock = clock or (lambda: datetime.now(UTC))
        self._owner_id = owner_id or f"coordinator-{uuid.uuid4().hex[:12]}"
        self._reservation_lease = timedelta(seconds=max(1, reservation_lease_seconds))
        self._audit_adapter = _SagaAuditAdapter(state_store=state_store, spec=spec)
        self._lifecycle = SkillBundleLifecycle(audit=self._audit_adapter)
        self._skill_catalog = SkillCatalog()
        self._bundle_catalog = SkillBundleCatalog()
        self._disclosure: RuntimeSkillDisclosure | None = None
        self._mutation_lock = asyncio.Lock()

    @property
    def spec(self) -> PinnedBundleArtifactSpec:
        return self._spec

    def _skill_verifier(self) -> Ed25519DomainSkillVerifier:
        return Ed25519DomainSkillVerifier(
            public_key=self._spec.public_key,
            expected_source=self._spec.publisher,
            signatures_by_digest={self._spec.member_content_sha256: self._spec.member_signature},
        )

    def _bundle_verifier(
        self, *, revoked_digests: frozenset[str] = frozenset()
    ) -> Ed25519DomainSkillBundleVerifier:
        return Ed25519DomainSkillBundleVerifier(
            public_key=self._spec.public_key,
            expected_source=self._spec.publisher,
            signatures_by_digest={self._spec.bundle_content_sha256: self._spec.bundle_signature},
            revoked_digests=revoked_digests,
        )

    async def _active_revoked_digests(self) -> frozenset[str]:
        revocations = await self._revocation_store.list(source_id=self._spec.publisher)
        return frozenset(item.artifact_digest for item in revocations)

    async def _startup_disclosure(
        self, *, enforce_revocations_in_verifier: bool = False
    ) -> SkillDisclosureStartupBinding:
        revoked = (
            await self._active_revoked_digests() if enforce_revocations_in_verifier else frozenset()
        )
        skill_verifier = self._skill_verifier()
        bundle_verifier = self._bundle_verifier(revoked_digests=revoked)
        return await compose_runtime_skill_disclosure_startup(
            store=self._artifact_store,
            skill_verifier_factory=lambda _record: skill_verifier,
            bundle_verifier_factory=lambda _record: bundle_verifier,
            skill_verifier=skill_verifier,
            bundle_verifier=bundle_verifier,
            available_tools=self._available_tools,
            known_agents=self._known_agents,
            agent="Bragi",
        )

    async def _refresh_disclosure(self) -> dict[str, Any]:
        binding = await self._startup_disclosure(enforce_revocations_in_verifier=False)
        disclosure = binding.require_ready_disclosure()
        self._disclosure = disclosure
        return self._readback_snapshot(disclosure, readiness_summary=binding)

    def _readback_snapshot(
        self,
        disclosure: RuntimeSkillDisclosure,
        *,
        readiness_summary: SkillDisclosureStartupBinding,
    ) -> dict[str, Any]:
        return build_disclosure_readback_snapshot(
            self._spec, disclosure, readiness_summary=readiness_summary
        )

    async def _reserve_or_replay_idempotency(
        self, *, transition: str, idempotency_key: str, request_digest: str
    ) -> tuple[dict[str, Any] | None, int]:
        lease_now = _aware_utc(self._clock())
        key = f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:idempotency:{idempotency_key}"
        lease_expires_at = (lease_now + self._reservation_lease).isoformat()
        reservation: dict[str, Any] = {
            "idempotency_key": idempotency_key,
            "lease_expires_at": lease_expires_at,
            "owner_id": self._owner_id,
            "receipt": None,
            "request_digest": request_digest,
            "revision": 1,
            "status": "reserved",
            "transition": transition,
        }
        if await self._state_store.write_state_if_absent(key, reservation):
            return None, 1
        existing = await self._state_store.read_state(key)
        if existing is None:
            raise RuntimeError("idempotency reservation disappeared before readback")
        if (
            existing.get("transition") != transition
            or existing.get("request_digest") != request_digest
        ):
            raise ValueError(
                f"idempotency_key {idempotency_key!r} conflicts with a different request"
            )
        status = str(existing.get("status", ""))
        if status in {"reserved", "recovering"}:
            raw_expiry = existing.get("lease_expires_at")
            if isinstance(raw_expiry, str) and raw_expiry:
                if lease_now < _aware_utc(datetime.fromisoformat(raw_expiry)):
                    raise RuntimeError(
                        f"idempotency_key {idempotency_key!r} is currently in-progress "
                        f"under active lease held by {existing.get('owner_id')!r}"
                    )
            expected_revision = int(existing.get("revision", 1))
            next_revision = expected_revision + 1
            takeover = {
                **reservation,
                "revision": next_revision,
                "status": "recovering",
            }
            if not await self._state_store.compare_and_set_state(
                key, takeover, expected_revision=expected_revision
            ):
                raise RuntimeError(
                    f"idempotency_key {idempotency_key!r} recovery was claimed by another "
                    "coordinator"
                )
            return None, next_revision
        if status == "refused":
            raise RevokedCapabilityBundleError(
                f"revoked capability bundle {self._spec.artifact_id!r} cannot be enabled"
            )
        receipt = existing.get("receipt")
        if not isinstance(receipt, Mapping):
            raise RuntimeError("retained idempotency record is missing its receipt")
        return dict(receipt), 0

    async def _sync_in_memory_catalogs_from_durable(self) -> None:
        parsed_skill = parse_skill_markdown(self._spec.member_raw_markdown)
        skill_record = await self._artifact_store.get(
            TrustedArtifactKind.SKILL, parsed_skill.manifest.name
        )
        if skill_record is not None:
            catalog = SkillCatalog().install(
                self._spec.member_raw_markdown, verifier=self._skill_verifier()
            )
            if skill_record.state is TrustedArtifactState.ENABLED:
                catalog = catalog.enable(
                    parsed_skill.manifest.name,
                    available_tools=self._available_tools,
                    known_agents=self._known_agents,
                )
            self._skill_catalog = catalog

        bundle_record = await self._artifact_store.get(
            TrustedArtifactKind.SKILL_BUNDLE, self._spec.artifact_id
        )
        if bundle_record is not None:
            b_cat = SkillBundleCatalog().install(
                self._spec.bundle_raw_manifest, verifier=self._bundle_verifier()
            )
            if bundle_record.state is TrustedArtifactState.ENABLED:
                b_cat = b_cat.enable(
                    self._spec.artifact_id,
                    skills=self._skill_catalog,
                    bundle_verifier=self._bundle_verifier(),
                    skill_verifier=self._skill_verifier(),
                    available_tools=self._available_tools,
                    known_agents=self._known_agents,
                )
            self._bundle_catalog = b_cat

    async def _reconcile_retained_receipt(
        self, *, transition_key: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        retained = await self._state_store.read_state(
            f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:{transition_key}"
        )
        if isinstance(retained, Mapping) and retained.get("idempotency_key") == idempotency_key:
            await self._sync_in_memory_catalogs_from_durable()
            return dict(retained)
        return None

    async def _record_idempotency(
        self,
        *,
        transition: str,
        idempotency_key: str,
        request_digest: str,
        receipt: Mapping[str, object],
        expected_revision: int,
        status: str = "completed",
    ) -> None:
        key = f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:idempotency:{idempotency_key}"
        payload = {
            "idempotency_key": idempotency_key,
            "owner_id": self._owner_id,
            "receipt": dict(receipt),
            "request_digest": request_digest,
            "revision": expected_revision + 1,
            "status": status,
            "transition": transition,
        }
        if not await self._state_store.compare_and_set_state(
            key, payload, expected_revision=expected_revision
        ):
            raise RuntimeError("failed to finalize reserved idempotency record")

    async def _begin_or_reconcile(
        self, *, transition: str, idempotency_key: str, request_digest: str
    ) -> tuple[dict[str, Any] | None, int]:
        replayed, reserved_rev = await self._reserve_or_replay_idempotency(
            transition=transition, idempotency_key=idempotency_key, request_digest=request_digest
        )
        if replayed is not None:
            return replayed, 0
        reconciled = await self._reconcile_retained_receipt(
            transition_key=transition, idempotency_key=idempotency_key
        )
        if reconciled is not None:
            await self._record_idempotency(
                transition=transition,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                receipt=reconciled,
                expected_revision=reserved_rev,
            )
            return reconciled, 0
        return None, reserved_rev

    async def _put_bundle_state(
        self, current: TrustedArtifactRecord, *, state: TrustedArtifactState, at: datetime
    ) -> TrustedArtifactRecord:
        from dataclasses import replace

        return await self._artifact_store.put(
            replace(current, state=state, revision=current.revision + 1, updated_at=at),
            expected_revision=current.revision,
        )

    async def _finalize_transition(
        self,
        *,
        transition: str,
        record: TrustedArtifactRecord,
        actor: str,
        idempotency_key: str,
        request_digest: str,
        reserved_rev: int,
        reason: str,
        at: datetime,
        reviewer_actor: str | None = None,
        action_type_id: str | None = None,
        review_decision_digest: str | None = None,
        revocation_id: str | None = None,
    ) -> dict[str, Any]:
        readback = await self._refresh_disclosure()
        receipt, audit = build_transition_receipt_and_audit(
            spec=self._spec,
            transition=transition,
            record=record,
            actor=actor,
            reviewer_actor=reviewer_actor,
            action_type_id=action_type_id,
            idempotency_key=idempotency_key,
            reason=reason,
            at=at,
            readback=readback,
            review_decision_digest=review_decision_digest,
            revocation_id=revocation_id,
        )
        state_key = f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:{transition}"
        if not await self._state_store.write_state_with_audit_if_absent(state_key, receipt, audit):
            existing = await self._state_store.read_state(state_key)
            if existing != receipt:
                raise RuntimeError(f"conflicting capability-bundle {transition} receipt")
        await self._record_idempotency(
            transition=transition,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            receipt=receipt,
            expected_revision=reserved_rev,
        )
        return receipt

    def _transition_request_digest(
        self, *, transition: str, actor: str, idempotency_key: str, reason: str | None = None
    ) -> str:
        payload: dict[str, Any] = {
            "actor": actor,
            "artifact_digest": self._spec.bundle_content_sha256,
            "idempotency_key": idempotency_key,
            "transition": transition,
        }
        if reason is not None:
            payload["reason"] = reason
        return content_digest(payload)

    async def install_bundle(
        self, *, actor: str, idempotency_key: str, reason: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Install the member skill (enabled) and capability bundle (disabled, revision 1)."""
        request_digest = self._transition_request_digest(
            transition="install", actor=actor, idempotency_key=idempotency_key, reason=reason
        )
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            existing_receipt, reserved_rev = await self._begin_or_reconcile(
                transition="install", idempotency_key=idempotency_key, request_digest=request_digest
            )
            if existing_receipt is not None:
                return existing_receipt

            installer = TrustedArtifactInstaller(store=self._artifact_store)
            skill_verifier = self._skill_verifier()
            bundle_verifier = self._bundle_verifier()
            parsed_skill = parse_skill_markdown(self._spec.member_raw_markdown)
            skill_record = await self._artifact_store.get(
                TrustedArtifactKind.SKILL, parsed_skill.manifest.name
            )
            if skill_record is None:
                self._skill_catalog = await installer.install_skill(
                    self._skill_catalog,
                    self._spec.member_raw_markdown,
                    signature=self._spec.member_signature,
                    verifier=skill_verifier,
                    now=at,
                )
                skill_record = await self._artifact_store.get(
                    TrustedArtifactKind.SKILL, parsed_skill.manifest.name
                )
            if skill_record is None:
                raise RuntimeError("member skill record was not persisted")
            if skill_record.state is not TrustedArtifactState.ENABLED:
                await self._artifact_store.put(
                    TrustedArtifactRecord(
                        kind=TrustedArtifactKind.SKILL,
                        artifact_id=skill_record.artifact_id,
                        version=skill_record.version,
                        source=skill_record.source,
                        content_sha256=skill_record.content_sha256,
                        artifact=skill_record.artifact,
                        signature=skill_record.signature,
                        state=TrustedArtifactState.ENABLED,
                        revision=skill_record.revision + 1,
                        created_at=skill_record.created_at,
                        updated_at=at,
                    ),
                    expected_revision=skill_record.revision,
                )
            await self._sync_in_memory_catalogs_from_durable()

            stored_bundle = await self._artifact_store.get(
                TrustedArtifactKind.SKILL_BUNDLE, self._spec.artifact_id
            )
            if stored_bundle is None:
                self._bundle_catalog = await self._lifecycle.install(
                    self._bundle_catalog,
                    self._spec.bundle_raw_manifest,
                    verifier=bundle_verifier,
                    actor=actor,
                    reason=reason,
                    at=at,
                )
                stored_bundle = await self._artifact_store.put(
                    TrustedArtifactRecord(
                        kind=TrustedArtifactKind.SKILL_BUNDLE,
                        artifact_id=self._spec.artifact_id,
                        version=self._spec.artifact_version,
                        source=self._spec.publisher,
                        content_sha256=self._spec.bundle_content_sha256,
                        artifact=self._spec.bundle_raw_manifest,
                        signature=self._spec.bundle_signature,
                        state=TrustedArtifactState.DISABLED,
                        revision=1,
                        created_at=at,
                        updated_at=at,
                    ),
                    expected_revision=0,
                )
            else:
                await self._sync_in_memory_catalogs_from_durable()

            return await self._finalize_transition(
                transition="install",
                record=stored_bundle,
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                reserved_rev=reserved_rev,
                reason=reason,
                at=at,
            )

    async def enable_bundle(
        self,
        action: ReviewedBundleEnableAction,
        *,
        dispatch_token: _VerifiedEnableDispatchToken | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Enable the installed bundle only through a verified typed-action dispatch token."""
        if (
            dispatch_token is None
            or dispatch_token.guard is not _DISPATCH_GUARD
            or dispatch_token.action_digest != action.request_digest()
            or dispatch_token.action_type_id != action.action_type_id
        ):
            raise PermissionError(
                "enable_bundle MUST be routed through TypedBundleEnableActionDispatcher"
            )
        request_digest = action.request_digest()
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            replayed, reserved_rev = await self._reserve_or_replay_idempotency(
                transition="enable",
                idempotency_key=action.idempotency_key,
                request_digest=request_digest,
            )
            if replayed is not None:
                return replayed
            reconciled_refusal = await self._reconcile_retained_receipt(
                transition_key="enable_refused_revoked", idempotency_key=action.idempotency_key
            )
            if reconciled_refusal is not None:
                await self._record_idempotency(
                    transition="enable",
                    idempotency_key=action.idempotency_key,
                    request_digest=request_digest,
                    receipt=reconciled_refusal,
                    expected_revision=reserved_rev,
                    status="refused",
                )
                raise RevokedCapabilityBundleError(
                    f"revoked capability bundle {self._spec.artifact_id!r} cannot be enabled"
                )
            reconciled_enable = await self._reconcile_retained_receipt(
                transition_key="enable", idempotency_key=action.idempotency_key
            )
            if reconciled_enable is not None:
                await self._record_idempotency(
                    transition="enable",
                    idempotency_key=action.idempotency_key,
                    request_digest=request_digest,
                    receipt=reconciled_enable,
                    expected_revision=reserved_rev,
                )
                return reconciled_enable

            current = await self._require_bundle_record()
            if await self._revocation_store.is_revoked(
                source_id=self._spec.publisher, artifact_digest=self._spec.bundle_content_sha256
            ):
                refused_receipt, refused_audit = build_refused_enable_receipt_and_audit(
                    spec=self._spec, current=current, action=action, at=at
                )
                await self._state_store.write_state_with_audit_if_absent(
                    f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:enable_refused_revoked",
                    refused_receipt,
                    refused_audit,
                )
                await self._record_idempotency(
                    transition="enable",
                    idempotency_key=action.idempotency_key,
                    request_digest=request_digest,
                    receipt=refused_receipt,
                    expected_revision=reserved_rev,
                    status="refused",
                )
                raise RevokedCapabilityBundleError(
                    f"revoked capability bundle {self._spec.artifact_id!r} cannot be enabled"
                )

            if current.state is not TrustedArtifactState.ENABLED:
                await self._sync_in_memory_catalogs_from_durable()
                self._bundle_catalog = await self._lifecycle.enable(
                    self._bundle_catalog,
                    self._spec.artifact_id,
                    skills=self._skill_catalog,
                    bundle_verifier=self._bundle_verifier(),
                    skill_verifier=self._skill_verifier(),
                    available_tools=self._available_tools,
                    known_agents=self._known_agents,
                    actor=action.requester_actor,
                    reason=action.reason,
                    at=at,
                )
                updated = await self._put_bundle_state(
                    current, state=TrustedArtifactState.ENABLED, at=at
                )
            else:
                updated = current
                await self._sync_in_memory_catalogs_from_durable()
            return await self._finalize_transition(
                transition="enable",
                record=updated,
                actor=action.requester_actor,
                reviewer_actor=action.reviewer_actor,
                action_type_id=action.action_type_id,
                idempotency_key=action.idempotency_key,
                request_digest=request_digest,
                reserved_rev=reserved_rev,
                reason=action.reason,
                at=at,
                review_decision_digest=action.review_decision_digest,
            )

    async def disable_bundle(
        self, *, actor: str, idempotency_key: str, reason: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Disable the bundle and verify independent disclosure readback."""
        request_digest = self._transition_request_digest(
            transition="disable", actor=actor, idempotency_key=idempotency_key, reason=reason
        )
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            existing_receipt, reserved_rev = await self._begin_or_reconcile(
                transition="disable", idempotency_key=idempotency_key, request_digest=request_digest
            )
            if existing_receipt is not None:
                return existing_receipt

            current = await self._require_bundle_record()
            if current.state is TrustedArtifactState.ENABLED:
                await self._sync_in_memory_catalogs_from_durable()
                self._bundle_catalog = await self._lifecycle.disable(
                    self._bundle_catalog, self._spec.artifact_id, actor=actor, reason=reason, at=at
                )
                updated = await self._put_bundle_state(
                    current, state=TrustedArtifactState.DISABLED, at=at
                )
            else:
                updated = current
                await self._sync_in_memory_catalogs_from_durable()
            return await self._finalize_transition(
                transition="disable",
                record=updated,
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                reserved_rev=reserved_rev,
                reason=reason,
                at=at,
            )

    async def revoke_bundle(
        self, *, actor: str, idempotency_key: str, reason: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Revoke the bundle artifact while preserving publisher, digest, and revision lineage."""
        request_digest = self._transition_request_digest(
            transition="revoke", actor=actor, idempotency_key=idempotency_key, reason=reason
        )
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            existing_receipt, reserved_rev = await self._begin_or_reconcile(
                transition="revoke", idempotency_key=idempotency_key, request_digest=request_digest
            )
            if existing_receipt is not None:
                return existing_receipt

            current = await self._require_bundle_record()
            revocation_id = (
                f"skill-revocation-{self._spec.publisher}-{self._spec.bundle_content_sha256[:16]}"
            )
            already_revoked = await self._revocation_store.is_revoked(
                source_id=self._spec.publisher, artifact_digest=self._spec.bundle_content_sha256
            )
            await self._revocation_store.put(
                SkillRevocation(
                    revocation_id=revocation_id,
                    source_id=self._spec.publisher,
                    artifact_digest=self._spec.bundle_content_sha256,
                    reason=reason,
                    revoked_at=at,
                )
            )
            if not already_revoked or current.state is not TrustedArtifactState.DISABLED:
                updated = await self._put_bundle_state(
                    current, state=TrustedArtifactState.DISABLED, at=at
                )
            else:
                updated = current
            await self._sync_in_memory_catalogs_from_durable()
            return await self._finalize_transition(
                transition="revoke",
                record=updated,
                actor=actor,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                reserved_rev=reserved_rev,
                reason=reason,
                at=at,
                revocation_id=revocation_id,
            )

    async def reconstruct_after_restart(
        self, *, actor: str, idempotency_key: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Cold-reconstruct disclosure from durable stores without synthetic rows or rewrites."""
        request_digest = self._transition_request_digest(
            transition="restart_reconstruct", actor=actor, idempotency_key=idempotency_key
        )
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            existing_receipt, reserved_rev = await self._begin_or_reconcile(
                transition="restart_reconstruct",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if existing_receipt is not None:
                return existing_receipt

            durable_record = await self._require_bundle_record()
            is_revoked = await self._revocation_store.is_revoked(
                source_id=self._spec.publisher, artifact_digest=self._spec.bundle_content_sha256
            )
            if not is_revoked or durable_record.state is not TrustedArtifactState.DISABLED:
                raise RuntimeError(
                    "restart reconstruction expected a revoked, disabled bundle record"
                )
            fresh_binding = await self._startup_disclosure(enforce_revocations_in_verifier=False)
            fresh_disclosure = fresh_binding.require_ready_disclosure()
            readback = self._readback_snapshot(fresh_disclosure, readiness_summary=fresh_binding)

            revoked_digests = await self._active_revoked_digests()
            revocation_verifier = self._bundle_verifier(revoked_digests=revoked_digests)
            parsed = parse_skill_bundle_manifest(durable_record.artifact)
            verifier_blocks_revoked = not revocation_verifier.verify(
                parsed, durable_record.artifact
            )
            if not verifier_blocks_revoked:
                raise RuntimeError("revocation-enforcing verifier failed to block revoked bundle")
            chain_verified = await self._state_store.verify_chain()
            if not chain_verified:
                raise RuntimeError("Saga audit hash chain failed verification after restart")

            receipt, audit = build_restart_reconstruct_receipt_and_audit(
                spec=self._spec,
                durable_record=durable_record,
                actor=actor,
                idempotency_key=idempotency_key,
                at=at,
                readback=readback,
                is_revoked=is_revoked,
                verifier_blocks_revoked=verifier_blocks_revoked,
                chain_verified=chain_verified,
            )
            await self._state_store.write_state_with_audit_if_absent(
                f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:restart_reconstruct", receipt, audit
            )
            await self._record_idempotency(
                transition="restart_reconstruct",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                receipt=receipt,
                expected_revision=reserved_rev,
            )
            return receipt

    async def _require_bundle_record(self) -> TrustedArtifactRecord:
        record = await self._artifact_store.get(
            TrustedArtifactKind.SKILL_BUNDLE, self._spec.artifact_id
        )
        if record is None:
            raise LookupError(f"trusted bundle {self._spec.artifact_id!r} is not installed")
        return record


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("capability bundle lifecycle timestamps MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "BUNDLE_CAPABILITY_ID",
    "BUNDLE_ENABLE_ACTION_TYPE_ID",
    "CI_RECEIPT_SIGNATURE_DOMAIN",
    "Ed25519DomainSkillBundleVerifier",
    "Ed25519DomainSkillVerifier",
    "GovernedSkillBundleLifecycleCoordinator",
    "PINNED_CI_ATTESTATION_PUBLIC_KEY_HEX",
    "PINNED_MAIN_2940_CI_RECEIPT",
    "PINNED_MAIN_2940_CI_SIGNATURE_HEX",
    "PinnedBundleArtifactSpec",
    "ReviewedBundleEnableAction",
    "RevokedCapabilityBundleError",
    "SKILL_BUNDLE_SIGNATURE_DOMAIN",
    "SKILL_SIGNATURE_DOMAIN",
    "TypedBundleEnableActionDispatcher",
    "VerifiedSourceCiReceipt",
    "build_pinned_fdai_bundle_artifact",
]
