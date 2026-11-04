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
import hashlib
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fdai_service_contracts.ontology_query import content_digest

from fdai.composition.wire_skill_disclosure import (
    SkillDisclosureStartupBinding,
    compose_runtime_skill_disclosure_startup,
)
from fdai.core.capability_catalog import (
    CapabilityReferences,
    build_capability_references,
)
from fdai.core.skills import (
    RuntimeSkill,
    RuntimeSkillBundle,
    RuntimeSkillDisclosure,
    SkillBundleCatalog,
    SkillBundleLifecycle,
    SkillBundleProposal,
    SkillBundleProposalState,
    SkillBundleResolutionError,
    SkillCatalog,
    encode_skill_bundle_manifest,
    parse_skill_bundle_manifest,
    parse_skill_markdown,
    skill_body_digest,
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
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.state_store import StateStore

SKILL_SIGNATURE_DOMAIN = b"fdai.skill-signature.v1\n"
SKILL_BUNDLE_SIGNATURE_DOMAIN = b"fdai.skill-bundle-signature.v1\n"
CI_RECEIPT_SIGNATURE_DOMAIN = b"fdai.ci-receipt-signature.v1\n"
BUNDLE_ENABLE_ACTION_TYPE_ID = "tool.run-investigation"
BUNDLE_CAPABILITY_ID = "fdai.inventory.evidence.investigation"
PINNED_CI_ATTESTATION_PUBLIC_KEY_HEX = (
    "767890e4dfba71a8ef099f38a3ab94ac018e19ea1bc6c0e08803206593a2bdac"
)
PINNED_MAIN_2940_CI_SIGNATURE_HEX = (
    "7e8b7440093e88372030ab50084800db8aa813c2d7fa918bc183fdf02a78ef7c"
    "97112f8f2f5d915bc11ebfd1b311eb2dc61d46e4c7c1eaa475d71ddab42e5300"
)
_PINNED_CI_ATTESTATION_PUBLIC_KEY = Ed25519PublicKey.from_public_bytes(
    bytes.fromhex(PINNED_CI_ATTESTATION_PUBLIC_KEY_HEX)
)
_STATE_KEY_PREFIX = "capability-bundle-lifecycle:v1:"
_GIT_SHA_RE = re.compile(r"^[a-f0-9]{40}$")


class RevokedCapabilityBundleError(RuntimeError):
    """A revoked capability bundle cannot be enabled or activated."""


class Ed25519DomainSkillVerifier:
    """Verify single-skill markdown under ``fdai.skill-signature.v1``."""

    def __init__(
        self,
        *,
        public_key: Ed25519PublicKey,
        expected_source: str,
        signatures_by_digest: Mapping[str, bytes],
    ) -> None:
        self._public_key = public_key
        self._expected_source = expected_source
        self._signatures = dict(signatures_by_digest)

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        if skill.manifest.source != self._expected_source:
            return False
        digest = hashlib.sha256(raw_markdown).hexdigest()
        signature = self._signatures.get(digest)
        if signature is None or len(signature) != 64:
            return False
        try:
            self._public_key.verify(signature, SKILL_SIGNATURE_DOMAIN + raw_markdown)
        except InvalidSignature:
            return False
        return True


class Ed25519DomainSkillBundleVerifier:
    """Verify governed skill-bundle manifests under ``fdai.skill-bundle-signature.v1``."""

    def __init__(
        self,
        *,
        public_key: Ed25519PublicKey,
        expected_source: str,
        signatures_by_digest: Mapping[str, bytes],
        revoked_digests: frozenset[str] = frozenset(),
    ) -> None:
        self._public_key = public_key
        self._expected_source = expected_source
        self._signatures = dict(signatures_by_digest)
        self._revoked_digests = revoked_digests

    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        if bundle.manifest.source != self._expected_source or bundle.raw_manifest != raw_manifest:
            return False
        digest = hashlib.sha256(raw_manifest).hexdigest()
        if digest in self._revoked_digests:
            return False
        signature = self._signatures.get(digest)
        if signature is None or len(signature) != 64:
            return False
        try:
            self._public_key.verify(signature, SKILL_BUNDLE_SIGNATURE_DOMAIN + raw_manifest)
        except InvalidSignature:
            return False
        return True


@dataclass(frozen=True, slots=True)
class VerifiedSourceCiReceipt:
    """Cryptographically attested green CI receipt verified against the pinned CI issuer key."""

    source_revision: str
    workflow_run_id: str
    check_conclusion: str
    verified_at: str
    signature: bytes

    def __post_init__(self) -> None:
        if _GIT_SHA_RE.fullmatch(self.source_revision) is None:
            raise ValueError("source_revision MUST be a 40-character lowercase hex Git SHA")
        if not self.workflow_run_id.strip():
            raise ValueError("workflow_run_id MUST be non-empty")
        if self.check_conclusion != "success":
            raise ValueError("pinned bundle source revision requires check_conclusion == 'success'")
        if not self.verified_at.strip():
            raise ValueError("verified_at MUST be non-empty")
        if len(self.signature) != 64:
            raise ValueError("CI receipt signature MUST be 64-byte Ed25519")
        try:
            _PINNED_CI_ATTESTATION_PUBLIC_KEY.verify(
                self.signature,
                CI_RECEIPT_SIGNATURE_DOMAIN + self.canonical_payload_bytes(),
            )
        except InvalidSignature as exc:
            raise ValueError(
                "CI receipt signature failed verification against pinned CI issuer key"
            ) from exc

    def canonical_payload_bytes(self) -> bytes:
        return (
            f"{self.source_revision}\n{self.workflow_run_id}\n"
            f"{self.check_conclusion}\n{self.verified_at}"
        ).encode()

    @property
    def receipt_digest(self) -> str:
        return content_digest(
            {
                "check_conclusion": self.check_conclusion,
                "issuer_public_key_hex": PINNED_CI_ATTESTATION_PUBLIC_KEY_HEX,
                "signature_sha256": hashlib.sha256(self.signature).hexdigest(),
                "source_revision": self.source_revision,
                "verified_at": self.verified_at,
                "workflow_run_id": self.workflow_run_id,
            }
        )


PINNED_MAIN_2940_CI_RECEIPT = VerifiedSourceCiReceipt(
    source_revision="b5b201f4d2bf0174ca65d926d5bad251188c261a",
    workflow_run_id="gh-actions-main-2940-b5b201f4d2",
    check_conclusion="success",
    verified_at="2026-11-04T09:10:20+00:00",
    signature=bytes.fromhex(PINNED_MAIN_2940_CI_SIGNATURE_HEX),
)


@dataclass(frozen=True, slots=True)
class PinnedBundleArtifactSpec:
    """Exact FDAI-owned, metadata-only, read-only capability bundle specification."""

    artifact_id: str
    artifact_version: str
    publisher: str
    source_revision: str
    release_version: str
    environment_id: str
    installation_id: str
    ci_status: str
    ci_receipt: VerifiedSourceCiReceipt
    member_skill_name: str
    member_skill_version: str
    member_raw_markdown: bytes
    member_content_sha256: str
    member_signature: bytes
    bundle_raw_manifest: bytes
    bundle_manifest_digest: str
    bundle_content_sha256: str
    bundle_signature: bytes
    public_key: Ed25519PublicKey

    def __post_init__(self) -> None:
        if self.ci_receipt.source_revision != self.source_revision or self.ci_status != "green":
            raise ValueError("pinned bundle spec requires a matching green VerifiedSourceCiReceipt")
        if hashlib.sha256(self.member_raw_markdown).hexdigest() != self.member_content_sha256:
            raise ValueError("member_content_sha256 does not match member_raw_markdown")
        if hashlib.sha256(self.bundle_raw_manifest).hexdigest() != self.bundle_content_sha256:
            raise ValueError("bundle_content_sha256 does not match bundle_raw_manifest")
        try:
            self.public_key.verify(
                self.member_signature,
                SKILL_SIGNATURE_DOMAIN + self.member_raw_markdown,
            )
            self.public_key.verify(
                self.bundle_signature,
                SKILL_BUNDLE_SIGNATURE_DOMAIN + self.bundle_raw_manifest,
            )
        except InvalidSignature as exc:
            raise ValueError("pinned bundle or member signature failed verification") from exc

    def to_pin_record(self) -> dict[str, object]:
        body: dict[str, object] = {
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "bundle_content_sha256": self.bundle_content_sha256,
            "bundle_manifest_digest": self.bundle_manifest_digest,
            "bundle_signature_sha256": hashlib.sha256(self.bundle_signature).hexdigest(),
            "ci_receipt_digest": self.ci_receipt.receipt_digest,
            "ci_status": self.ci_status,
            "ci_workflow_run_id": self.ci_receipt.workflow_run_id,
            "environment_id": self.environment_id,
            "execution_authority": False,
            "installation_id": self.installation_id,
            "member_content_sha256": self.member_content_sha256,
            "member_skill_name": self.member_skill_name,
            "member_skill_version": self.member_skill_version,
            "promotion_authority": False,
            "publisher": self.publisher,
            "release_version": self.release_version,
            "source_revision": self.source_revision,
        }
        return {**body, "pin_digest": content_digest(body)}


_DISPATCH_GUARD = object()


@dataclass(frozen=True, slots=True)
class _VerifiedEnableDispatchToken:
    guard: object
    action_digest: str
    action_type_id: str
    proposal_id: str


class TypedBundleEnableActionDispatcher:
    """Validate and route bundle enablement against ontology ActionTypes and SkillBundleWorkshop."""

    def __init__(self, *, references: CapabilityReferences | None = None) -> None:
        if references is None:
            catalog_root = repo_asset_root() / "rule-catalog"
            ontology = load_ontology_catalog(
                catalog_root,
                schema_registry=PackageResourceSchemaRegistry(),
                probes_root=catalog_root / "probes",
            )
            references = build_capability_references(
                action_types=ontology.action_types,
            )
        if BUNDLE_ENABLE_ACTION_TYPE_ID not in references.action_types:
            raise RuntimeError(
                f"required ontology ActionType {BUNDLE_ENABLE_ACTION_TYPE_ID!r} "
                "is missing from catalog"
            )
        self._references = references

    @property
    def references(self) -> CapabilityReferences:
        return self._references

    def verify_action(
        self,
        action: ReviewedBundleEnableAction,
        *,
        approved_proposal: SkillBundleProposal,
        expected_bundle_name: str,
        expected_content_sha256: str,
    ) -> _VerifiedEnableDispatchToken:
        if action.action_type_id not in self._references.action_types:
            raise ValueError(
                f"action_type {action.action_type_id!r} is not registered in the ontology catalog"
            )
        if action.action_type_id != BUNDLE_ENABLE_ACTION_TYPE_ID:
            raise ValueError(
                f"bundle enable dispatcher requires {BUNDLE_ENABLE_ACTION_TYPE_ID!r}, "
                f"got {action.action_type_id!r}"
            )
        if (
            approved_proposal.state is not SkillBundleProposalState.APPROVED
            or approved_proposal.bundle_name != expected_bundle_name
            or approved_proposal.content_hash != expected_content_sha256
            or approved_proposal.proposed_by_agent != action.requester_actor
            or approved_proposal.reviewed_by != action.reviewer_actor
        ):
            raise ValueError(
                "bundle enable requires a matching APPROVED SkillBundleProposal "
                "from a distinct reviewer"
            )
        return _VerifiedEnableDispatchToken(
            guard=_DISPATCH_GUARD,
            action_digest=action.request_digest(),
            action_type_id=action.action_type_id,
            proposal_id=approved_proposal.proposal_id,
        )

    async def dispatch(
        self,
        coordinator: GovernedSkillBundleLifecycleCoordinator,
        action: ReviewedBundleEnableAction,
        *,
        approved_proposal: SkillBundleProposal,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        token = self.verify_action(
            action,
            approved_proposal=approved_proposal,
            expected_bundle_name=coordinator.spec.artifact_id,
            expected_content_sha256=coordinator.spec.bundle_content_sha256,
        )
        return await coordinator.enable_bundle(action, dispatch_token=token, now=now)


@dataclass(frozen=True, slots=True)
class ReviewedBundleEnableAction:
    """Typed action envelope for distinct-reviewer bundle enablement."""

    action_type_id: str
    requester_actor: str
    reviewer_actor: str
    review_decision_digest: str
    idempotency_key: str
    reason: str
    mode: str = "shadow"
    execution_authority: bool = False
    promotion_authority: bool = False

    def __post_init__(self) -> None:
        if not self.action_type_id.strip():
            raise ValueError("bundle enable action requires a non-empty action_type_id")
        if self.action_type_id != BUNDLE_ENABLE_ACTION_TYPE_ID:
            raise ValueError(f"bundle enable action MUST use {BUNDLE_ENABLE_ACTION_TYPE_ID!r}")
        if not self.requester_actor.strip() or not self.reviewer_actor.strip():
            raise ValueError("bundle enable requires non-empty requester and reviewer actors")
        if self.requester_actor.strip() == self.reviewer_actor.strip():
            raise ValueError("bundle enable requires a distinct reviewer actor")
        if not self.review_decision_digest.strip().startswith("sha256:"):
            raise ValueError("bundle enable requires a sha256 review_decision_digest")
        if not self.idempotency_key.strip() or not self.reason.strip():
            raise ValueError("bundle enable requires non-empty idempotency_key and reason")
        if self.mode != "shadow":
            raise ValueError("bundle enable action MUST stay in shadow mode")
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise ValueError("bundle enable action cannot grant execution or promotion authority")

    def request_digest(self) -> str:
        return content_digest(
            {
                "action_type_id": self.action_type_id,
                "execution_authority": self.execution_authority,
                "idempotency_key": self.idempotency_key,
                "mode": self.mode,
                "promotion_authority": self.promotion_authority,
                "reason": self.reason,
                "requester_actor": self.requester_actor,
                "review_decision_digest": self.review_decision_digest,
                "reviewer_actor": self.reviewer_actor,
            }
        )


class _SagaAuditAdapter:
    """Bridge :class:`SkillBundleLifecycleAudit` onto the shared :class:`StateStore`."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        spec: PinnedBundleArtifactSpec,
    ) -> None:
        self._state_store = state_store
        self._spec = spec
        self.events: list[dict[str, Any]] = []

    async def append(self, event: Mapping[str, Any]) -> None:
        payload = {
            **dict(event),
            "kind": f"capability-bundle.{event['action_kind']}",
            "publisher": self._spec.publisher,
            "content_sha256": self._spec.bundle_content_sha256,
            "release_version": self._spec.release_version,
            "source_revision": self._spec.source_revision,
            "environment_id": self._spec.environment_id,
            "installation_id": self._spec.installation_id,
            "execution_authority": False,
            "promotion_authority": False,
        }
        self.events.append(payload)


def build_pinned_fdai_bundle_artifact(
    *,
    ci_receipt: VerifiedSourceCiReceipt,
    seed: bytes = b"fdai-x01-exact-artifact-bundle-seed-v1",
    source_revision: str = "b5b201f4d2bf0174ca65d926d5bad251188c261a",
    release_version: str = "1.1.1",
    environment_id: str = "local-isolated-validation",
    installation_id: str = "installation-fdai-dev-wus3",
) -> PinnedBundleArtifactSpec:
    """Build the deterministic FDAI-owned metadata-only capability bundle artifact."""

    resolved_ci = ci_receipt
    if len(seed) != 32:
        seed = hashlib.sha256(seed).digest()
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key = private_key.public_key()
    publisher = "fdai.upstream.capability-bundles"
    member_name = "inventory-evidence"
    member_version = "1.0.0"
    member_body = (
        "Read-only inventory evidence inspection procedure. "
        "Summarizes observed resource state facts without mutating cloud state."
    )
    member_raw = (
        "---\n"
        f"name: {member_name}\n"
        f"version: {member_version}\n"
        "description: Read-only inventory evidence procedure.\n"
        f"source: {publisher}\n"
        f'body_sha256: "{skill_body_digest(member_body)}"\n'
        "required_tools: [query_inventory]\n"
        "allowed_agents: [Bragi]\n"
        "---\n"
        f"{member_body}\n"
    ).encode()
    member_sha256 = hashlib.sha256(member_raw).hexdigest()
    member_sig = private_key.sign(SKILL_SIGNATURE_DOMAIN + member_raw)

    artifact_id = "fdai-inventory-evidence-bundle"
    artifact_version = "1.0.0"
    bundle_raw = encode_skill_bundle_manifest(
        {
            "name": artifact_id,
            "version": artifact_version,
            "description": "FDAI-owned read-only inventory evidence capability bundle.",
            "source": publisher,
            "members": [{"name": member_name, "version": f"=={member_version}"}],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory"],
            "instruction": (
                "Follow read-only inventory evidence checks and report observed gaps only."
            ),
        }
    )
    parsed_bundle = parse_skill_bundle_manifest(bundle_raw)
    bundle_sha256 = hashlib.sha256(bundle_raw).hexdigest()
    bundle_sig = private_key.sign(SKILL_BUNDLE_SIGNATURE_DOMAIN + bundle_raw)

    return PinnedBundleArtifactSpec(
        artifact_id=artifact_id,
        artifact_version=artifact_version,
        publisher=publisher,
        source_revision=source_revision,
        release_version=release_version,
        environment_id=environment_id,
        installation_id=installation_id,
        ci_status="green",
        ci_receipt=resolved_ci,
        member_skill_name=member_name,
        member_skill_version=member_version,
        member_raw_markdown=member_raw,
        member_content_sha256=member_sha256,
        member_signature=member_sig,
        bundle_raw_manifest=bundle_raw,
        bundle_manifest_digest=parsed_bundle.manifest.digest,
        bundle_content_sha256=bundle_sha256,
        bundle_signature=bundle_sig,
        public_key=public_key,
    )


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
        self,
        *,
        revoked_digests: frozenset[str] = frozenset(),
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
        self,
        *,
        enforce_revocations_in_verifier: bool = False,
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
        listed = disclosure.list_bundles(query=self._spec.artifact_id, limit=10)
        described = disclosure.describe_bundle(self._spec.artifact_id)["bundle"]
        inspected = disclosure.inspect()
        load_status = "resolved"
        load_rejection_reason: str | None = None
        resolved_replay_digest: str | None = None
        try:
            loaded = disclosure.load_bundle(self._spec.artifact_id)
            resolved_replay_digest = str(loaded["digest"])
        except SkillBundleResolutionError as exc:
            load_status = "rejected"
            load_rejection_reason = exc.reason.value
        body: dict[str, object] = {
            "artifact_id": self._spec.artifact_id,
            "bundle_count": readiness_summary.readiness.bundle_count,
            "described_compatible": bool(described["compatible"]),
            "described_eligible": bool(described["eligible"]),
            "described_enabled": bool(described["enabled"]),
            "described_trust_status": str(described["trust_status"]),
            "enabled_bundle_count": readiness_summary.readiness.enabled_bundle_count,
            "enabled_skill_count": readiness_summary.readiness.enabled_skill_count,
            "execution_authority": False,
            "inspected_eligible_bundle_count": int(inspected["eligible_bundle_count"]),
            "inspected_installed_bundle_count": int(inspected["installed_bundle_count"]),
            "listed_returned_count": int(listed["returned_count"]),
            "load_rejection_reason": load_rejection_reason,
            "load_status": load_status,
            "mutation_controls": bool(inspected["mutation_controls"]),
            "resolved_replay_digest": resolved_replay_digest,
            "skill_count": readiness_summary.readiness.skill_count,
        }
        return {**body, "readback_digest": content_digest(body)}

    async def _reserve_or_replay_idempotency(
        self,
        *,
        transition: str,
        idempotency_key: str,
        request_digest: str,
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
        created = await self._state_store.write_state_if_absent(key, reservation)
        if created:
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
                expires_at = _aware_utc(datetime.fromisoformat(raw_expiry))
                if lease_now < expires_at:
                    raise RuntimeError(
                        f"idempotency_key {idempotency_key!r} is currently in-progress "
                        f"under active lease held by {existing.get('owner_id')!r}"
                    )
            expected_revision = int(existing.get("revision", 1))
            next_revision = expected_revision + 1
            takeover: dict[str, Any] = {
                "idempotency_key": idempotency_key,
                "lease_expires_at": lease_expires_at,
                "owner_id": self._owner_id,
                "receipt": None,
                "request_digest": request_digest,
                "revision": next_revision,
                "status": "recovering",
                "transition": transition,
            }
            claimed = await self._state_store.compare_and_set_state(
                key,
                takeover,
                expected_revision=expected_revision,
            )
            if not claimed:
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
            TrustedArtifactKind.SKILL,
            parsed_skill.manifest.name,
        )
        if skill_record is not None:
            catalog = SkillCatalog()
            catalog = catalog.install(
                self._spec.member_raw_markdown,
                verifier=self._skill_verifier(),
            )
            if skill_record.state is TrustedArtifactState.ENABLED:
                catalog = catalog.enable(
                    parsed_skill.manifest.name,
                    available_tools=self._available_tools,
                    known_agents=self._known_agents,
                )
            self._skill_catalog = catalog

        bundle_record = await self._artifact_store.get(
            TrustedArtifactKind.SKILL_BUNDLE,
            self._spec.artifact_id,
        )
        if bundle_record is not None:
            b_cat = SkillBundleCatalog()
            b_cat = b_cat.install(
                self._spec.bundle_raw_manifest,
                verifier=self._bundle_verifier(),
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
        self,
        *,
        transition_key: str,
        idempotency_key: str,
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
        finalized = await self._state_store.compare_and_set_state(
            key,
            {
                "idempotency_key": idempotency_key,
                "owner_id": self._owner_id,
                "receipt": dict(receipt),
                "request_digest": request_digest,
                "revision": expected_revision + 1,
                "status": status,
                "transition": transition,
            },
            expected_revision=expected_revision,
        )
        if not finalized:
            raise RuntimeError("failed to finalize reserved idempotency record")

    async def install_bundle(
        self,
        *,
        actor: str,
        idempotency_key: str,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Install the member skill (enabled) and capability bundle (disabled, revision 1)."""

        request_digest = content_digest(
            {
                "actor": actor,
                "artifact_digest": self._spec.bundle_content_sha256,
                "idempotency_key": idempotency_key,
                "reason": reason,
                "transition": "install",
            }
        )
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            replayed, reserved_rev = await self._reserve_or_replay_idempotency(
                transition="install",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replayed is not None:
                return replayed
            reconciled = await self._reconcile_retained_receipt(
                transition_key="install",
                idempotency_key=idempotency_key,
            )
            if reconciled is not None:
                await self._record_idempotency(
                    transition="install",
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    receipt=reconciled,
                    expected_revision=reserved_rev,
                )
                return reconciled

            installer = TrustedArtifactInstaller(store=self._artifact_store)
            skill_verifier = self._skill_verifier()
            bundle_verifier = self._bundle_verifier()
            parsed_skill = parse_skill_markdown(self._spec.member_raw_markdown)
            skill_record = await self._artifact_store.get(
                TrustedArtifactKind.SKILL,
                parsed_skill.manifest.name,
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
                    TrustedArtifactKind.SKILL,
                    parsed_skill.manifest.name,
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
                TrustedArtifactKind.SKILL_BUNDLE,
                self._spec.artifact_id,
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

            readback = await self._refresh_disclosure()
            receipt = await self._retain_transition_receipt(
                transition="install",
                record=stored_bundle,
                actor=actor,
                reviewer_actor=None,
                action_type_id=None,
                idempotency_key=idempotency_key,
                reason=reason,
                at=at,
                readback=readback,
            )
            await self._record_idempotency(
                transition="install",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                receipt=receipt,
                expected_revision=reserved_rev,
            )
            return receipt

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
                transition_key="enable_refused_revoked",
                idempotency_key=action.idempotency_key,
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
                transition_key="enable",
                idempotency_key=action.idempotency_key,
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
                source_id=self._spec.publisher,
                artifact_digest=self._spec.bundle_content_sha256,
            ):
                refused_body: dict[str, object] = {
                    "action_type_id": action.action_type_id,
                    "actor": action.requester_actor,
                    "artifact_digest": current.content_sha256,
                    "artifact_id": current.artifact_id,
                    "artifact_revision": current.revision,
                    "artifact_state": current.state.value,
                    "artifact_version": current.version,
                    "environment_id": self._spec.environment_id,
                    "execution_authority": False,
                    "idempotency_key": action.idempotency_key,
                    "installation_id": self._spec.installation_id,
                    "mode": "shadow",
                    "outcome": "blocked_by_revocation",
                    "promotion_authority": False,
                    "publisher": current.source,
                    "reason": action.reason,
                    "release_version": self._spec.release_version,
                    "review_decision_digest": action.review_decision_digest,
                    "reviewer_actor": action.reviewer_actor,
                    "source_revision": self._spec.source_revision,
                    "timestamp": at.isoformat(),
                    "transition": "enable_refused_revoked",
                }
                refused_receipt = {
                    **refused_body,
                    "receipt_digest": content_digest(refused_body),
                }
                await self._state_store.write_state_with_audit_if_absent(
                    f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:enable_refused_revoked",
                    refused_receipt,
                    {
                        "kind": "capability-bundle.enable_refused_revoked",
                        "event_id": refused_receipt["receipt_digest"],
                        "idempotency_key": action.idempotency_key,
                        "actor_identity": action.requester_actor,
                        "reviewer_identity": action.reviewer_actor,
                        "action_type_id": action.action_type_id,
                        "artifact_id": current.artifact_id,
                        "artifact_version": current.version,
                        "publisher": current.source,
                        "artifact_digest": current.content_sha256,
                        "artifact_revision": current.revision,
                        "release_version": self._spec.release_version,
                        "source_revision": self._spec.source_revision,
                        "environment_id": self._spec.environment_id,
                        "timestamp": at.isoformat(),
                        "decision": "denied",
                        "outcome": "blocked_by_revocation",
                        "mode": "shadow",
                        "receipt_digest": refused_receipt["receipt_digest"],
                        "execution_authority": False,
                        "promotion_authority": False,
                    },
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
                updated = await self._artifact_store.put(
                    TrustedArtifactRecord(
                        kind=TrustedArtifactKind.SKILL_BUNDLE,
                        artifact_id=current.artifact_id,
                        version=current.version,
                        source=current.source,
                        content_sha256=current.content_sha256,
                        artifact=current.artifact,
                        signature=current.signature,
                        state=TrustedArtifactState.ENABLED,
                        revision=current.revision + 1,
                        created_at=current.created_at,
                        updated_at=at,
                    ),
                    expected_revision=current.revision,
                )
            else:
                updated = current
                await self._sync_in_memory_catalogs_from_durable()
            readback = await self._refresh_disclosure()
            receipt = await self._retain_transition_receipt(
                transition="enable",
                record=updated,
                actor=action.requester_actor,
                reviewer_actor=action.reviewer_actor,
                action_type_id=action.action_type_id,
                idempotency_key=action.idempotency_key,
                reason=action.reason,
                at=at,
                readback=readback,
                review_decision_digest=action.review_decision_digest,
            )
            await self._record_idempotency(
                transition="enable",
                idempotency_key=action.idempotency_key,
                request_digest=request_digest,
                receipt=receipt,
                expected_revision=reserved_rev,
            )
            return receipt

    async def disable_bundle(
        self,
        *,
        actor: str,
        idempotency_key: str,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Disable the bundle and verify independent disclosure readback."""

        request_digest = content_digest(
            {
                "actor": actor,
                "artifact_digest": self._spec.bundle_content_sha256,
                "idempotency_key": idempotency_key,
                "reason": reason,
                "transition": "disable",
            }
        )
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            replayed, reserved_rev = await self._reserve_or_replay_idempotency(
                transition="disable",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replayed is not None:
                return replayed
            reconciled = await self._reconcile_retained_receipt(
                transition_key="disable",
                idempotency_key=idempotency_key,
            )
            if reconciled is not None:
                await self._record_idempotency(
                    transition="disable",
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    receipt=reconciled,
                    expected_revision=reserved_rev,
                )
                return reconciled

            current = await self._require_bundle_record()
            if current.state is TrustedArtifactState.ENABLED:
                await self._sync_in_memory_catalogs_from_durable()
                self._bundle_catalog = await self._lifecycle.disable(
                    self._bundle_catalog,
                    self._spec.artifact_id,
                    actor=actor,
                    reason=reason,
                    at=at,
                )
                updated = await self._artifact_store.put(
                    TrustedArtifactRecord(
                        kind=TrustedArtifactKind.SKILL_BUNDLE,
                        artifact_id=current.artifact_id,
                        version=current.version,
                        source=current.source,
                        content_sha256=current.content_sha256,
                        artifact=current.artifact,
                        signature=current.signature,
                        state=TrustedArtifactState.DISABLED,
                        revision=current.revision + 1,
                        created_at=current.created_at,
                        updated_at=at,
                    ),
                    expected_revision=current.revision,
                )
            else:
                updated = current
                await self._sync_in_memory_catalogs_from_durable()
            readback = await self._refresh_disclosure()
            receipt = await self._retain_transition_receipt(
                transition="disable",
                record=updated,
                actor=actor,
                reviewer_actor=None,
                action_type_id=None,
                idempotency_key=idempotency_key,
                reason=reason,
                at=at,
                readback=readback,
            )
            await self._record_idempotency(
                transition="disable",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                receipt=receipt,
                expected_revision=reserved_rev,
            )
            return receipt

    async def revoke_bundle(
        self,
        *,
        actor: str,
        idempotency_key: str,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Revoke the bundle artifact while preserving publisher, digest, and revision lineage."""

        request_digest = content_digest(
            {
                "actor": actor,
                "artifact_digest": self._spec.bundle_content_sha256,
                "idempotency_key": idempotency_key,
                "reason": reason,
                "transition": "revoke",
            }
        )
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            replayed, reserved_rev = await self._reserve_or_replay_idempotency(
                transition="revoke",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replayed is not None:
                return replayed
            reconciled = await self._reconcile_retained_receipt(
                transition_key="revoke",
                idempotency_key=idempotency_key,
            )
            if reconciled is not None:
                await self._record_idempotency(
                    transition="revoke",
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    receipt=reconciled,
                    expected_revision=reserved_rev,
                )
                return reconciled

            current = await self._require_bundle_record()
            revocation_id = (
                f"skill-revocation-{self._spec.publisher}-{self._spec.bundle_content_sha256[:16]}"
            )
            already_revoked = await self._revocation_store.is_revoked(
                source_id=self._spec.publisher,
                artifact_digest=self._spec.bundle_content_sha256,
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
                updated = await self._artifact_store.put(
                    TrustedArtifactRecord(
                        kind=TrustedArtifactKind.SKILL_BUNDLE,
                        artifact_id=current.artifact_id,
                        version=current.version,
                        source=current.source,
                        content_sha256=current.content_sha256,
                        artifact=current.artifact,
                        signature=current.signature,
                        state=TrustedArtifactState.DISABLED,
                        revision=current.revision + 1,
                        created_at=current.created_at,
                        updated_at=at,
                    ),
                    expected_revision=current.revision,
                )
            else:
                updated = current
            await self._sync_in_memory_catalogs_from_durable()
            readback = await self._refresh_disclosure()
            receipt = await self._retain_transition_receipt(
                transition="revoke",
                record=updated,
                actor=actor,
                reviewer_actor=None,
                action_type_id=None,
                idempotency_key=idempotency_key,
                reason=reason,
                at=at,
                readback=readback,
                revocation_id=revocation_id,
            )
            await self._record_idempotency(
                transition="revoke",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                receipt=receipt,
                expected_revision=reserved_rev,
            )
            return receipt

    async def reconstruct_after_restart(
        self,
        *,
        actor: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Cold-reconstruct disclosure from durable stores without synthetic rows or rewrites."""

        request_digest = content_digest(
            {
                "actor": actor,
                "artifact_digest": self._spec.bundle_content_sha256,
                "idempotency_key": idempotency_key,
                "transition": "restart_reconstruct",
            }
        )
        at = _aware_utc(now or self._clock())
        async with self._mutation_lock:
            replayed, reserved_rev = await self._reserve_or_replay_idempotency(
                transition="restart_reconstruct",
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replayed is not None:
                return replayed
            reconciled = await self._reconcile_retained_receipt(
                transition_key="restart_reconstruct",
                idempotency_key=idempotency_key,
            )
            if reconciled is not None:
                await self._record_idempotency(
                    transition="restart_reconstruct",
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    receipt=reconciled,
                    expected_revision=reserved_rev,
                )
                return reconciled

            durable_record = await self._require_bundle_record()
            is_revoked = await self._revocation_store.is_revoked(
                source_id=self._spec.publisher,
                artifact_digest=self._spec.bundle_content_sha256,
            )
            if not is_revoked or durable_record.state is not TrustedArtifactState.DISABLED:
                raise RuntimeError(
                    "restart reconstruction expected a revoked, disabled bundle record"
                )

            # Reconstruct from durable stores using a fresh RuntimeSkillDisclosure instance.
            fresh_binding = await self._startup_disclosure(enforce_revocations_in_verifier=False)
            fresh_disclosure = fresh_binding.require_ready_disclosure()
            readback = self._readback_snapshot(fresh_disclosure, readiness_summary=fresh_binding)

            # Also prove that revocation-enforcing verifier blocks any attempt to enable on reload.
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

            body: dict[str, object] = {
                "actor": actor,
                "artifact_digest": durable_record.content_sha256,
                "artifact_id": durable_record.artifact_id,
                "artifact_revision": durable_record.revision,
                "artifact_state": durable_record.state.value,
                "artifact_version": durable_record.version,
                "chain_verified": chain_verified,
                "environment_id": self._spec.environment_id,
                "execution_authority": False,
                "idempotency_key": idempotency_key,
                "installation_id": self._spec.installation_id,
                "is_revoked": is_revoked,
                "mode": "shadow",
                "mutable_history_rewritten": False,
                "promotion_authority": False,
                "publisher": durable_record.source,
                "readback": readback,
                "release_version": self._spec.release_version,
                "source_revision": self._spec.source_revision,
                "synthetic_records_created": 0,
                "timestamp": at.isoformat(),
                "transition": "restart_reconstruct",
                "verifier_blocks_revoked": verifier_blocks_revoked,
            }
            receipt = {**body, "receipt_digest": content_digest(body)}
            await self._state_store.write_state_with_audit_if_absent(
                f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:restart_reconstruct",
                receipt,
                {
                    "kind": "capability-bundle.restart_reconstruct",
                    "event_id": receipt["receipt_digest"],
                    "idempotency_key": idempotency_key,
                    "actor_identity": actor,
                    "artifact_id": durable_record.artifact_id,
                    "artifact_version": durable_record.version,
                    "publisher": durable_record.source,
                    "artifact_digest": durable_record.content_sha256,
                    "artifact_revision": durable_record.revision,
                    "release_version": self._spec.release_version,
                    "source_revision": self._spec.source_revision,
                    "environment_id": self._spec.environment_id,
                    "timestamp": at.isoformat(),
                    "decision": "verified",
                    "outcome": "reconstructed_revoked_state",
                    "mode": "shadow",
                    "receipt_digest": receipt["receipt_digest"],
                    "readback_digest": readback["readback_digest"],
                    "execution_authority": False,
                    "promotion_authority": False,
                },
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
            TrustedArtifactKind.SKILL_BUNDLE,
            self._spec.artifact_id,
        )
        if record is None:
            raise LookupError(f"trusted bundle {self._spec.artifact_id!r} is not installed")
        return record

    async def _retain_transition_receipt(
        self,
        *,
        transition: str,
        record: TrustedArtifactRecord,
        actor: str,
        reviewer_actor: str | None,
        action_type_id: str | None,
        idempotency_key: str,
        reason: str,
        at: datetime,
        readback: Mapping[str, object],
        review_decision_digest: str | None = None,
        revocation_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, object] = {
            "action_type_id": action_type_id,
            "actor": actor,
            "artifact_digest": record.content_sha256,
            "artifact_id": record.artifact_id,
            "artifact_revision": record.revision,
            "artifact_state": record.state.value,
            "artifact_version": record.version,
            "bundle_manifest_digest": self._spec.bundle_manifest_digest,
            "environment_id": self._spec.environment_id,
            "execution_authority": False,
            "idempotency_key": idempotency_key,
            "installation_id": self._spec.installation_id,
            "mode": "shadow",
            "promotion_authority": False,
            "publisher": record.source,
            "readback": dict(readback),
            "reason": reason,
            "release_version": self._spec.release_version,
            "review_decision_digest": review_decision_digest,
            "reviewer_actor": reviewer_actor,
            "revocation_id": revocation_id,
            "source_revision": self._spec.source_revision,
            "timestamp": at.isoformat(),
            "transition": transition,
        }
        receipt = {**body, "receipt_digest": content_digest(body)}
        created = await self._state_store.write_state_with_audit_if_absent(
            f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:{transition}",
            receipt,
            {
                "kind": f"capability-bundle.{transition}",
                "event_id": receipt["receipt_digest"],
                "idempotency_key": idempotency_key,
                "actor_identity": actor,
                "reviewer_identity": reviewer_actor,
                "action_type_id": action_type_id,
                "artifact_id": record.artifact_id,
                "artifact_version": record.version,
                "publisher": record.source,
                "artifact_digest": record.content_sha256,
                "artifact_revision": record.revision,
                "artifact_state": record.state.value,
                "release_version": self._spec.release_version,
                "source_revision": self._spec.source_revision,
                "environment_id": self._spec.environment_id,
                "timestamp": at.isoformat(),
                "decision": "accepted",
                "outcome": transition,
                "mode": "shadow",
                "receipt_digest": receipt["receipt_digest"],
                "readback_digest": readback["readback_digest"],
                "execution_authority": False,
                "promotion_authority": False,
            },
        )
        if not created:
            existing = await self._state_store.read_state(
                f"{_STATE_KEY_PREFIX}{self._spec.artifact_id}:{transition}"
            )
            if existing != receipt:
                raise RuntimeError(f"conflicting capability-bundle {transition} receipt")
        return receipt


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
