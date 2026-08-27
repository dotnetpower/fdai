"""Thor-owned direct adapter for applying an approved ActionType promotion receipt."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.rbac.roles import Role
from fdai.core.risk_gate import ActionModeRecord, PromotionMetrics
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceApproval,
    GovernanceChangeClass,
    GovernancePrincipal,
    GovernanceReviewRequest,
    validate_governance_review,
)
from fdai.shared.contracts.models import Mode, OntologyActionType
from fdai.shared.providers.direct_api import (
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
)
from fdai.shared.providers.state_store import StateStore

PROMOTION_ACTION_TYPE = "governance.promote-action-type"


@dataclass(frozen=True, slots=True)
class GovernancePromotionAttestation:
    """Authenticated review result bound to one exact promotion request."""

    review: GovernanceReviewRequest
    action_type_id: str
    fdai_revision: str
    scenario_set_version: str
    evidence_digest: str
    idempotency_key: str
    nonce: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.action_type_id,
                self.fdai_revision,
                self.scenario_set_version,
                self.evidence_digest,
                self.idempotency_key,
                self.nonce,
                self.request_fingerprint,
            )
        ):
            raise ValueError("promotion attestation identity MUST be non-empty")

    def as_json(self) -> dict[str, object]:
        """Serialize the validated review attestation for durable one-time use."""
        return {
            "action_type_id": self.action_type_id,
            "fdai_revision": self.fdai_revision,
            "scenario_set_version": self.scenario_set_version,
            "evidence_digest": self.evidence_digest,
            "idempotency_key": self.idempotency_key,
            "nonce": self.nonce,
            "request_fingerprint": self.request_fingerprint,
            "review": {
                "change_class": self.review.change_class.value,
                "author": {
                    "oid": self.review.author.oid,
                    "roles": [role.value for role in self.review.author.roles],
                },
                "head_revision": self.review.head_revision,
                "head_committed_at": self.review.head_committed_at.isoformat(),
                "approvals": [
                    {
                        "approver": {
                            "oid": approval.approver.oid,
                            "roles": [role.value for role in approval.approver.roles],
                        },
                        "reviewed_revision": approval.reviewed_revision,
                        "approved_at": approval.approved_at.isoformat(),
                        "phishing_resistant": approval.phishing_resistant,
                        "dismissed": approval.dismissed,
                    }
                    for approval in self.review.approvals
                ],
                "co_author_oids": list(self.review.co_author_oids),
                "committer_oids": list(self.review.committer_oids),
            },
        }


class OperationalPromotionReceiptReader(Protocol):
    async def load(
        self,
        *,
        action_type_name: str,
        fdai_revision: str,
        scenario_set_version: str,
        evidence_digest: str,
    ) -> OperationalPromotionReceipt | None: ...


class PersistedActionPromotionRegistry(Protocol):
    def consider_promotion(
        self,
        *,
        action_type: OntologyActionType,
        metrics: PromotionMetrics,
        receipt: OperationalPromotionReceipt | None = None,
    ) -> ActionModeRecord: ...

    async def persist(self, action_type: str) -> None: ...


class PromotionAttestationStore(Protocol):
    """Durable one-time store for authenticated promotion attestations."""

    async def save(self, attestation: GovernancePromotionAttestation) -> None: ...

    async def consume(
        self, idempotency_key: str, request_fingerprint: str
    ) -> GovernancePromotionAttestation | None: ...


class StateStorePromotionAttestationStore:
    """Persist and atomically consume one promotion review nonce."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def save(self, attestation: GovernancePromotionAttestation) -> None:
        key = f"governance-promotion-attestation:{attestation.idempotency_key}"
        created = await self._store.write_state_with_audit_if_absent(
            key,
            {
                "schema_version": "1.0.0",
                "state": "pending",
                "revision": 0,
                "attestation": attestation.as_json(),
            },
            {
                "actor": "fdai.delivery.promotion",
                "action_kind": "promotion_attestation.recorded",
                "idempotency_key": attestation.idempotency_key,
                "nonce": attestation.nonce,
                "mode": Mode.SHADOW.value,
            },
        )
        if not created:
            raise DirectApiPreconditionError("promotion attestation nonce is already registered")

    async def consume(
        self, idempotency_key: str, request_fingerprint: str
    ) -> GovernancePromotionAttestation | None:
        key = f"governance-promotion-attestation:{idempotency_key}"
        raw = await self._store.read_state(key)
        if raw is None or raw.get("state") != "pending":
            return None
        revision = raw.get("revision")
        value = raw.get("attestation")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or not isinstance(value, Mapping)
        ):
            raise DirectApiPreconditionError("promotion attestation state is malformed")
        attestation = _attestation_from_json(value)
        if attestation.request_fingerprint != request_fingerprint:
            return None
        applied = await self._store.compare_and_set_state_with_audit(
            key,
            {
                "schema_version": "1.0.0",
                "state": "consumed",
                "revision": revision + 1,
                "attestation": attestation.as_json(),
            },
            expected_revision=revision,
            audit_entry={
                "actor": "fdai.delivery.promotion",
                "action_kind": "promotion_attestation.consumed",
                "idempotency_key": attestation.idempotency_key,
                "nonce": attestation.nonce,
                "mode": Mode.ENFORCE.value,
            },
        )
        return attestation if applied else None


class OperationalPromotionDirectApiExecutor(DirectApiExecutor):
    """Apply one exact, measured receipt after the ordinary HIL gate."""

    def __init__(
        self,
        *,
        action_types: Mapping[str, OntologyActionType],
        receipts: OperationalPromotionReceiptReader,
        registry: PersistedActionPromotionRegistry,
    ) -> None:
        self._action_types = dict(action_types)
        self._receipts = receipts
        self._registry = registry

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name != PROMOTION_ACTION_TYPE:
            raise DirectApiPreconditionError("unsupported promotion action type")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError("promotion authority requires the enforce label")
        args = _promotion_arguments(request.arguments)
        target = self._action_types.get(args["action_type_id"])
        if target is None:
            raise DirectApiPreconditionError("promotion target ActionType is not registered")
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"shadow:promotion:{target.name}",
                detail="shadow: exact promotion receipt was not applied",
            )

        receipt = await self._receipts.load(
            action_type_name=target.name,
            fdai_revision=args["fdai_revision"],
            scenario_set_version=args["scenario_set_version"],
            evidence_digest=args["evidence_digest"],
        )
        if receipt is None:
            raise DirectApiPreconditionError("exact operational promotion receipt was not found")
        if (
            receipt.action_type_name != target.name
            or receipt.fdai_revision != args["fdai_revision"]
            or receipt.scenario_set_version != args["scenario_set_version"]
            or receipt.evidence_digest != args["evidence_digest"]
        ):
            raise DirectApiPreconditionError("operational promotion receipt identity mismatched")
        if not receipt.ready:
            raise DirectApiPreconditionError("operational promotion receipt is not ready")
        metrics = PromotionMetrics(
            action_type=target.name,
            shadow_days=receipt.live_observation_days,
            samples=receipt.sample_count,
            accuracy=receipt.accuracy,
            policy_escapes=receipt.policy_escapes,
        )
        record = self._registry.consider_promotion(
            action_type=target,
            metrics=metrics,
            receipt=receipt,
        )
        if record.mode is not Mode.ENFORCE:
            raise DirectApiPreconditionError("operational promotion receipt was rejected")
        await self._registry.persist(target.name)
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"promotion:{target.name}:{receipt.evidence_digest}",
            detail="verified operational promotion receipt applied",
        )


class GovernancePromotionDispatcher:
    """Require an approved, distinct-approver transition before promotion.

    The wrapped direct-API executor remains the mechanical promotion writer.
    This boundary validates the governance review first; a missing or
    insufficient review therefore cannot change the ActionType mode registry.
    """

    def __init__(
        self,
        executor: OperationalPromotionDirectApiExecutor,
        *,
        attestation_store: PromotionAttestationStore | None = None,
    ) -> None:
        self._executor = executor
        self._attestation_store = attestation_store

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        """Reject ungoverned direct routing; use :meth:`dispatch` after review."""
        if self._attestation_store is None:
            raise DirectApiPreconditionError(
                "promotion direct routing is inert until a governance review is supplied"
            )
        attestation = await self._attestation_store.consume(
            request.idempotency_key,
            promotion_request_fingerprint(request),
        )
        if attestation is None:
            raise DirectApiPreconditionError(
                "promotion direct routing requires an unused governance attestation"
            )
        return await self.dispatch(request, attestation=attestation)

    async def dispatch(
        self,
        request: DirectApiRequest,
        *,
        attestation: GovernancePromotionAttestation | None = None,
    ) -> DirectApiReceipt:
        """Dispatch only after the exact enforce-promotion review is allowed."""
        if not isinstance(attestation, GovernancePromotionAttestation):
            raise DirectApiPreconditionError(
                "promotion requires an authenticated distinct-approver "
                "governance review attestation"
            )
        args = _promotion_arguments(request.arguments)
        if (
            args["action_type_id"] != attestation.action_type_id
            or args["fdai_revision"] != attestation.fdai_revision
            or args["scenario_set_version"] != attestation.scenario_set_version
            or args["evidence_digest"] != attestation.evidence_digest
            or request.idempotency_key != attestation.idempotency_key
            or promotion_request_fingerprint(request) != attestation.request_fingerprint
            or attestation.review.head_revision != attestation.fdai_revision
        ):
            raise DirectApiPreconditionError(
                "promotion review attestation does not match the exact request"
            )
        decision = validate_governance_review(attestation.review)
        if (
            decision.change_class is not GovernanceChangeClass.ENFORCE_PROMOTION
            or not decision.allowed
            or decision.satisfied_quorum < decision.required_quorum
            or len(decision.counted_approver_oids) < 2
        ):
            raise DirectApiPreconditionError(
                "promotion requires an approved distinct-approver governance transition"
            )
        return await self._executor.execute(request)


def _promotion_arguments(arguments: Mapping[str, object]) -> dict[str, str]:
    required = (
        "action_type_id",
        "fdai_revision",
        "scenario_set_version",
        "evidence_digest",
    )
    values: dict[str, str] = {}
    for name in required:
        value = arguments.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DirectApiPreconditionError(f"promotion argument {name} is required")
        values[name] = value
    if arguments.get("target_mode") != Mode.ENFORCE.value:
        raise DirectApiPreconditionError("promotion target_mode MUST be enforce")
    return values


def _attestation_from_json(raw: Mapping[str, Any]) -> GovernancePromotionAttestation:
    review_raw = _mapping(raw.get("review"), "review")
    author_raw = _mapping(review_raw.get("author"), "author")
    approvals: list[GovernanceApproval] = []
    raw_approvals = review_raw.get("approvals")
    if not isinstance(raw_approvals, list):
        raise DirectApiPreconditionError("promotion attestation approvals are malformed")
    for item in raw_approvals:
        approval_raw = _mapping(item, "approval")
        principal_raw = _mapping(approval_raw.get("approver"), "approver")
        approvals.append(
            GovernanceApproval(
                approver=GovernancePrincipal(
                    oid=_text(principal_raw, "oid"),
                    roles=_roles(principal_raw.get("roles")),
                ),
                reviewed_revision=_text(approval_raw, "reviewed_revision"),
                approved_at=_timestamp(approval_raw, "approved_at"),
                phishing_resistant=_bool(approval_raw, "phishing_resistant"),
                dismissed=_bool(approval_raw, "dismissed"),
            )
        )
    return GovernancePromotionAttestation(
        review=GovernanceReviewRequest(
            change_class=GovernanceChangeClass(_text(review_raw, "change_class")),
            author=GovernancePrincipal(
                oid=_text(author_raw, "oid"),
                roles=_roles(author_raw.get("roles")),
            ),
            head_revision=_text(review_raw, "head_revision"),
            head_committed_at=_timestamp(review_raw, "head_committed_at"),
            approvals=tuple(approvals),
            co_author_oids=frozenset(_strings(review_raw.get("co_author_oids"))),
            committer_oids=frozenset(_strings(review_raw.get("committer_oids"))),
        ),
        action_type_id=_text(raw, "action_type_id"),
        fdai_revision=_text(raw, "fdai_revision"),
        scenario_set_version=_text(raw, "scenario_set_version"),
        evidence_digest=_text(raw, "evidence_digest"),
        idempotency_key=_text(raw, "idempotency_key"),
        nonce=_text(raw, "nonce"),
        request_fingerprint=_text(raw, "request_fingerprint"),
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DirectApiPreconditionError(f"promotion attestation {name} is malformed")
    return value


def _text(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DirectApiPreconditionError(f"promotion attestation {name} is malformed")
    return value


def _bool(raw: Mapping[str, Any], name: str) -> bool:
    value = raw.get(name)
    if not isinstance(value, bool):
        raise DirectApiPreconditionError(f"promotion attestation {name} is malformed")
    return value


def _timestamp(raw: Mapping[str, Any], name: str) -> datetime:
    value = _text(raw, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DirectApiPreconditionError(f"promotion attestation {name} is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DirectApiPreconditionError(f"promotion attestation {name} is not timezone-aware")
    return parsed


def _roles(value: object) -> frozenset[Role]:
    return frozenset(Role(item) for item in _strings(value))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DirectApiPreconditionError("promotion attestation string list is malformed")
    return tuple(value)


def promotion_request_fingerprint(request: DirectApiRequest) -> str:
    """Hash every request field that can affect promotion semantics."""
    payload = {
        "action_id": str(request.action_id),
        "arguments": dict(request.arguments),
        "action_type_name": request.action_type_name,
        "idempotency_key": request.idempotency_key,
        "labels": list(request.labels),
        "metadata": dict(request.metadata),
        "mode": request.mode.value,
        "resource_ref": request.resource_ref,
        "rule_ids": list(request.rule_ids),
        "stop_conditions": [item.model_dump(mode="json") for item in request.stop_conditions],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = [
    "OperationalPromotionDirectApiExecutor",
    "GovernancePromotionDispatcher",
    "GovernancePromotionAttestation",
    "PromotionAttestationStore",
    "StateStorePromotionAttestationStore",
    "promotion_request_fingerprint",
    "OperationalPromotionReceiptReader",
    "PROMOTION_ACTION_TYPE",
    "PersistedActionPromotionRegistry",
]
