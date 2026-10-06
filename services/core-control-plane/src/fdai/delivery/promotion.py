"""Thor-owned direct adapter for applying an approved ActionType promotion receipt."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from fdai_service_contracts.approval_profile import ApprovalProfileRevision

from fdai.core.executor.lock import ResourceLockManager
from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.risk_gate import ActionModeRecord, PromotionMetrics
from fdai.delivery.promotion_attestation import (
    GovernancePromotionAttestation,
    attestation_from_json,
    direct_api_receipt_from_json,
    direct_api_receipt_json,
    optional_timestamp,
    promotion_attestation_digest,
)
from fdai.delivery.promotion_override import (
    OVERRIDE_PROMOTION_ACTION_TYPE,
    OperatorOverridePromotionDirectApiExecutor,
    override_promotion_arguments,
)
from fdai.delivery.promotion_review import (
    approval_profile_matches,
    attestation_matches_override_receipt,
)
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceChangeClass,
    ReviewAuthorityDecision,
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
    DirectApiRetryableError,
)
from fdai.shared.providers.state_store import StateStore

PROMOTION_ACTION_TYPE = "governance.promote-action-type"

# How long a claimed-but-not-yet-finalized attestation stays exclusively
# reserved before another `consume` may reclaim it. Bounds recovery when
# the same durable-store outage that failed the guarded apply also fails
# the compensating `restore` write - see `StateStorePromotionAttestationStore`.
_DEFAULT_RESERVATION_LEASE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class PromotionReservation:
    """One consumed attestation paired with the revision that claimed it.

    ``fencing_token`` is the state-store revision
    :meth:`PromotionAttestationStore.consume` wrote when it reserved the
    nonce. A caller MUST present it back unchanged to ``restore``/
    ``finalize``. If the bounded reservation lease later expires and a
    different caller reclaims the same nonce (see
    ``StateStorePromotionAttestationStore``), the record's revision moves
    past this token - so a stale holder's ``restore``/``finalize`` call,
    arriving after it already lost the reservation, becomes a safe no-op
    instead of unwinding or finalizing a reclaimer's still-active attempt.
    """

    attestation: GovernancePromotionAttestation
    fencing_token: int


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

    def record(self, action_type: str) -> ActionModeRecord | None: ...

    def read_model(self, action_type: str) -> dict[str, object]: ...

    def restore(self, action_type: str, record: ActionModeRecord | None) -> None: ...

    async def refresh_for_update(self, action_type: str) -> None: ...

    async def persist(self, action_type: str) -> None: ...


class PromotionAttestationStore(Protocol):
    """Durable one-time store for authenticated promotion attestations."""

    async def save(self, attestation: GovernancePromotionAttestation) -> None: ...

    async def consume(
        self, idempotency_key: str, request_fingerprint: str
    ) -> PromotionReservation | None: ...

    async def load_replay(
        self, idempotency_key: str, request_fingerprint: str
    ) -> DirectApiReceipt | None: ...

    async def restore(
        self,
        idempotency_key: str,
        attestation: GovernancePromotionAttestation,
        fencing_token: int,
    ) -> None: ...

    async def finalize(
        self,
        idempotency_key: str,
        attestation: GovernancePromotionAttestation,
        fencing_token: int,
        receipt: DirectApiReceipt,
    ) -> None: ...


class StateStorePromotionAttestationStore:
    """Persist and atomically consume one promotion review nonce.

    The nonce moves ``pending -> reserved -> consumed``. ``consume``
    claims it (``reserved``) *before* the guarded executor's durable
    apply is known to succeed, so a caller MUST NOT treat ``reserved`` as
    a spent approval. Only ``finalize`` (called after a confirmed durable
    success) reaches the terminal ``consumed`` state; ``restore`` reverts
    a failed attempt back to ``pending`` so the same approval backs a
    retry.

    ``reserved`` carries a bounded ``reserved_until`` lease. The fast path
    is an explicit ``restore`` after a failure, but that write can fail
    for the exact same reason the guarded apply did - a durable-store
    outage affects both calls identically, since they share one store.
    Without the lease, that would spend the human approval forever with
    no way back. Instead, ``consume`` also reclaims any ``reserved``
    record whose lease has already expired, so the approval recovers on
    its own, bounded by ``reservation_lease_seconds``, once the store is
    reachable again - no successful ``restore`` write is required.

    ``consume`` returns the claim as a :class:`PromotionReservation`
    carrying a ``fencing_token`` - the exact revision this call's reserve
    write produced. ``restore`` and ``finalize`` MUST be given that same
    token back, and only act while the record's current revision still
    matches it. Without this check, a holder whose lease already expired
    and was reclaimed by a fresh ``consume`` call (which bumps the
    revision) could otherwise still ``restore`` or ``finalize`` using
    whatever revision it re-reads from the store - unwinding or
    finalizing the *reclaimer's* still-active reservation instead of its
    own expired one.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        reservation_lease_seconds: int = _DEFAULT_RESERVATION_LEASE_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if reservation_lease_seconds < 1:
            raise ValueError("reservation_lease_seconds MUST be >= 1")
        self._store = store
        self._reservation_lease = timedelta(seconds=reservation_lease_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    async def save(self, attestation: GovernancePromotionAttestation) -> None:
        key = f"governance-promotion-attestation:{attestation.idempotency_key}"
        created = await self._store.write_state_with_audit_if_absent(
            key,
            {
                "schema_version": "1.0.0",
                "state": "pending",
                "revision": 0,
                "approval_receipt_digest": promotion_attestation_digest(attestation),
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
    ) -> PromotionReservation | None:
        key = f"governance-promotion-attestation:{idempotency_key}"
        raw = await self._store.read_state(key)
        if raw is None:
            return None
        state = raw.get("state")
        if state == "consumed":
            return None
        if state == "reserved":
            reserved_until = optional_timestamp(raw.get("reserved_until"))
            if reserved_until is None or reserved_until > self._clock():
                # Still legitimately claimed by an in-flight attempt (or a
                # record this store never reserved); do not double-claim.
                return None
            # The lease expired: the prior holder's `restore` could not
            # durably run (for example the same store outage that failed
            # its apply). Bounded recovery reclaims the nonce here so the
            # same governance approval can back a fresh attempt.
        elif state != "pending":
            return None
        revision = raw.get("revision")
        value = raw.get("attestation")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or not isinstance(value, Mapping)
        ):
            raise DirectApiPreconditionError("promotion attestation state is malformed")
        attestation = attestation_from_json(value)
        if attestation.request_fingerprint != request_fingerprint:
            return None
        reserved_until = self._clock() + self._reservation_lease
        new_revision = revision + 1
        applied = await self._store.compare_and_set_state_with_audit(
            key,
            {
                "schema_version": "1.0.0",
                "state": "reserved",
                "revision": new_revision,
                "approval_receipt_digest": promotion_attestation_digest(attestation),
                "attestation": attestation.as_json(),
                "reserved_until": reserved_until.isoformat(),
            },
            expected_revision=revision,
            audit_entry={
                "actor": "fdai.delivery.promotion",
                "action_kind": "promotion_attestation.reserved",
                "idempotency_key": attestation.idempotency_key,
                "nonce": attestation.nonce,
                "mode": Mode.ENFORCE.value,
            },
        )
        if not applied:
            return None
        return PromotionReservation(attestation=attestation, fencing_token=new_revision)

    async def load_replay(
        self,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> DirectApiReceipt | None:
        raw = await self._store.read_state(f"governance-promotion-attestation:{idempotency_key}")
        if raw is None or raw.get("state") != "consumed":
            return None
        value = raw.get("attestation")
        receipt = raw.get("receipt")
        if not isinstance(value, Mapping) or not isinstance(receipt, Mapping):
            return None
        attestation = attestation_from_json(value)
        if attestation.request_fingerprint != request_fingerprint:
            raise DirectApiPreconditionError(
                "promotion idempotency key was already used for another request"
            )
        return direct_api_receipt_from_json(receipt)

    async def restore(
        self,
        idempotency_key: str,
        attestation: GovernancePromotionAttestation,
        fencing_token: int,
    ) -> None:
        """Return a reserved attestation to pending after a failed durable apply.

        ``consume`` reserves the nonce before its promotion effect is known
        to be durable. When the guarded executor then fails to persist the
        promotion, the human approval MUST NOT be spent for nothing: this
        reverts the state back to ``pending`` (bumping the revision) so the
        exact same governance approval can be retried without demanding a
        brand-new distinct-approver review. A concurrent state change (the
        nonce was reserved again, finalized, or moved on by another caller)
        makes this a best-effort no-op rather than a hard failure - as does
        this write itself failing, since a later ``consume`` call recovers
        the same reservation once its lease expires (see the class
        docstring).

        ``fencing_token`` MUST be the exact value :meth:`consume` returned
        for this reservation. If the record's current revision no longer
        matches it, this reservation was already reclaimed by a later
        ``consume`` call (the caller's lease expired first) - restoring it
        here would unwind that reclaimer's still-active attempt instead of
        this caller's own expired one, so this is a no-op in that case too.
        """
        key = f"governance-promotion-attestation:{idempotency_key}"
        raw = await self._store.read_state(key)
        if raw is None or raw.get("state") != "reserved":
            return
        revision = raw.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            return
        if revision != fencing_token:
            return
        await self._store.compare_and_set_state_with_audit(
            key,
            {
                "schema_version": "1.0.0",
                "state": "pending",
                "revision": revision + 1,
                "approval_receipt_digest": promotion_attestation_digest(attestation),
                "attestation": attestation.as_json(),
            },
            expected_revision=revision,
            audit_entry={
                "actor": "fdai.delivery.promotion",
                "action_kind": "promotion_attestation.restored",
                "idempotency_key": idempotency_key,
                "nonce": attestation.nonce,
                "mode": Mode.SHADOW.value,
            },
        )

    async def finalize(
        self,
        idempotency_key: str,
        attestation: GovernancePromotionAttestation,
        fencing_token: int,
        receipt: DirectApiReceipt,
    ) -> None:
        """Spend the reservation permanently after a confirmed durable apply.

        Only a caller that already observed the guarded executor's success
        may call this - it is the sole path to the terminal ``consumed``
        state. A concurrent state change (the reservation lease already
        expired and was reclaimed, or the store is unreachable) makes this
        a best-effort no-op: the promotion itself already durably applied,
        so a stuck ``reserved`` record here is a bookkeeping gap, not a lost
        approval, and self-heals the same way an unrestored failure does.

        ``fencing_token`` MUST be the exact value :meth:`consume` returned
        for this reservation. If the record's current revision has since
        moved past it, this reservation was already reclaimed by a later
        ``consume`` call - finalizing it here would spend a reclaimer's
        still-active attempt instead of this caller's own expired one, so
        this is a no-op in that case too.
        """
        key = f"governance-promotion-attestation:{idempotency_key}"
        raw = await self._store.read_state(key)
        if raw is None or raw.get("state") != "reserved":
            return
        revision = raw.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            return
        if revision != fencing_token:
            return
        await self._store.compare_and_set_state_with_audit(
            key,
            {
                "schema_version": "1.0.0",
                "state": "consumed",
                "revision": revision + 1,
                "approval_receipt_digest": promotion_attestation_digest(attestation),
                "attestation": attestation.as_json(),
                "receipt": direct_api_receipt_json(receipt),
            },
            expected_revision=revision,
            audit_entry={
                "actor": "fdai.delivery.promotion",
                "action_kind": "promotion_attestation.consumed",
                "idempotency_key": idempotency_key,
                "nonce": attestation.nonce,
                "mode": Mode.ENFORCE.value,
            },
        )


class OperationalPromotionDirectApiExecutor(DirectApiExecutor):
    """Apply one exact, measured receipt after the ordinary HIL gate.
    A caller (``DirectApiShadowExecutor``) already serializes actions on
    the same ``resource_ref`` before reaching this executor, but that
    protection is external and easy to bypass (a direct unit test, a
    future caller, a second registry-mutating route). The registry itself
    is a plain in-process cache - ``consider_promotion`` mutates it
    optimistically so its verdict can be inspected before ``persist``, and
    a failed ``persist`` rolls that mutation back with ``restore``. Two
    concurrent promotion attempts for the *same* ActionType without an
    internal lock could interleave those steps: the second call's
    ``record()`` could capture the first call's unpersisted ENFORCE
    mutation as its own "prior" state, and a failed first call could then
    restore over the second call's already-durably-persisted result (or
    vice versa). A per-ActionType lock around the whole
    read-mutate-persist-restore sequence makes this executor safe on its
    own, independent of any external caller's locking.
    """

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
        self._locks = ResourceLockManager()

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
        if (
            receipt.decision_evidence_receipt_digest is None
            or receipt.decision_evidence_verification_bundle_digest is None
        ):
            raise DirectApiPreconditionError(
                "operational promotion receipt lacks independent decision evidence"
            )
        metrics = PromotionMetrics(
            action_type=target.name,
            shadow_days=receipt.live_observation_days,
            samples=receipt.sample_count,
            accuracy=receipt.accuracy,
            policy_escapes=receipt.policy_escapes,
        )
        # Serialize the whole read-mutate-persist(-restore) sequence per
        # ActionType. Without this, a concurrent attempt for the same
        # ActionType could capture this call's unpersisted optimistic
        # mutation as its own "prior" record, or a failed restore here
        # could clobber a concurrent call's already-durable persist.
        async with self._locks.acquire(target.name):
            await self._registry.refresh_for_update(target.name)
            prior_record = self._registry.record(target.name)
            if (
                prior_record is not None
                and prior_record.mode is Mode.ENFORCE
                and prior_record.promotion_evidence_digest == receipt.evidence_digest
                and prior_record.fdai_revision == receipt.fdai_revision
                and prior_record.scenario_set_version == receipt.scenario_set_version
                and prior_record.action_type_version == receipt.action_type_version
                and prior_record.action_type_digest == receipt.action_type_digest
            ):
                if self._registry.read_model(target.name).get("promotion_kind") != "gate_evidence":
                    raise DirectApiPreconditionError(
                        "persisted ActionType promotion attribution differs from this request"
                    )
                return DirectApiReceipt(
                    outcome=DirectApiOutcome.SUCCEEDED,
                    receipt_ref=f"promotion:{target.name}:{receipt.evidence_digest}",
                    detail="verified operational promotion receipt already applied",
                )
            if prior_record is not None and prior_record.mode is Mode.ENFORCE:
                raise DirectApiPreconditionError(
                    "persisted ActionType promotion attribution differs from this request"
                )
            record = self._registry.consider_promotion(
                action_type=target,
                metrics=metrics,
                receipt=receipt,
            )
            if record.mode is not Mode.ENFORCE:
                raise DirectApiPreconditionError("operational promotion receipt was rejected")
            try:
                await self._registry.persist(target.name)
            except BaseException:
                # `consider_promotion` mutates the in-memory cache optimistically
                # so its verdict can be inspected before persisting. A failed
                # durable write MUST NOT leave that unpersisted ENFORCE visible
                # to `mode_of`, so put the exact prior record back on failure.
                self._registry.restore(target.name, prior_record)
                raise
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"promotion:{target.name}:{receipt.evidence_digest}",
            detail="verified operational promotion receipt applied",
        )


class GovernancePromotionDispatcher:
    """Require an approved, distinct-approver transition before promotion.

    This boundary validates the governance review first; a missing or
    insufficient review therefore cannot change the ActionType mode registry.
    """

    def __init__(
        self,
        executor: DirectApiExecutor,
        *,
        attestation_store: PromotionAttestationStore | None = None,
        active_approval_profile: ApprovalProfileRevision | None = None,
    ) -> None:
        self._executor = executor
        self._attestation_store = attestation_store
        self._active_approval_profile = active_approval_profile
        self._confirmed: OrderedDict[str, tuple[str, DirectApiReceipt]] = OrderedDict()

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        """Reject ungoverned direct routing; use :meth:`dispatch` after review."""
        if self._attestation_store is None:
            raise DirectApiPreconditionError(
                "promotion direct routing is inert until a governance review is supplied"
            )
        idempotency_key = request.idempotency_key
        request_fingerprint = promotion_request_fingerprint(request)
        confirmed = self._confirmed.get(idempotency_key)
        if confirmed is not None:
            if confirmed[0] != request_fingerprint:
                raise DirectApiPreconditionError(
                    "promotion idempotency key was already used for another request"
                )
            self._confirmed.move_to_end(idempotency_key)
            return confirmed[1]
        replay = await self._attestation_store.load_replay(
            idempotency_key,
            request_fingerprint,
        )
        if replay is not None:
            return replay
        reservation = await self._attestation_store.consume(
            idempotency_key,
            request_fingerprint,
        )
        if reservation is None:
            raise DirectApiPreconditionError(
                "promotion direct routing requires an unused governance attestation"
            )
        attestation = reservation.attestation
        fencing_token = reservation.fencing_token
        try:
            receipt = await self.dispatch(request, attestation=attestation)
        except BaseException as exc:
            already_applied = await self._safe_already_applied_receipt(request, attestation)
            if already_applied is not None:
                await self._confirm_reserved_attestation(
                    idempotency_key,
                    request_fingerprint,
                    attestation,
                    fencing_token,
                    already_applied,
                )
                return already_applied
            try:
                await self._attestation_store.restore(idempotency_key, attestation, fencing_token)
            except BaseException:  # noqa: BLE001, S110 - best-effort, original failure wins
                pass
            raise DirectApiRetryableError(str(exc)) from exc
        await self._confirm_reserved_attestation(
            idempotency_key,
            request_fingerprint,
            attestation,
            fencing_token,
            receipt,
        )
        return receipt

    async def _confirm_reserved_attestation(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        attestation: GovernancePromotionAttestation,
        fencing_token: int,
        receipt: DirectApiReceipt,
    ) -> None:
        self._confirmed[idempotency_key] = (request_fingerprint, receipt)
        self._confirmed.move_to_end(idempotency_key)
        if len(self._confirmed) > 1024:
            self._confirmed.popitem(last=False)
        store = self._attestation_store
        if store is None:
            raise RuntimeError("promotion attestation store is unavailable")
        try:
            await store.finalize(
                idempotency_key,
                attestation,
                fencing_token,
                receipt,
            )
        except BaseException:  # noqa: BLE001, S110 - best-effort, the durable apply already won
            pass

    async def _safe_already_applied_receipt(
        self,
        request: DirectApiRequest,
        attestation: GovernancePromotionAttestation,
    ) -> DirectApiReceipt | None:
        if not attestation_matches_override_receipt(request, attestation):
            return None
        try:
            return await self._already_applied_receipt(request)
        except Exception:
            return None

    async def _already_applied_receipt(self, request: DirectApiRequest) -> DirectApiReceipt | None:
        method = getattr(self._executor, "already_applied_receipt", None)
        if not callable(method):
            return None
        return cast(DirectApiReceipt | None, await method(request))

    async def dispatch(
        self,
        request: DirectApiRequest,
        *,
        attestation: GovernancePromotionAttestation | None = None,
    ) -> DirectApiReceipt:
        """Dispatch only after the exact governance review is allowed."""
        if not isinstance(attestation, GovernancePromotionAttestation):
            raise DirectApiPreconditionError(
                "promotion requires an authenticated distinct-approver "
                "governance review attestation"
            )
        if request.action_type_name == OVERRIDE_PROMOTION_ACTION_TYPE:
            override_args = override_promotion_arguments(request.arguments)
            action_type_id = override_args["action_type_id"]
            fdai_revision = override_args["fdai_revision"]
            scenario_set_version = override_args["scenario_set_version"]
            evidence_digest = override_args["gate_evidence_digest"]
        else:
            promotion_args = _promotion_arguments(request.arguments)
            action_type_id = promotion_args["action_type_id"]
            fdai_revision = promotion_args["fdai_revision"]
            scenario_set_version = promotion_args["scenario_set_version"]
            evidence_digest = promotion_args["evidence_digest"]
        if (
            action_type_id != attestation.action_type_id
            or fdai_revision != attestation.fdai_revision
            or scenario_set_version != attestation.scenario_set_version
            or evidence_digest != attestation.evidence_digest
            or request.idempotency_key != attestation.idempotency_key
            or promotion_request_fingerprint(request) != attestation.request_fingerprint
            or attestation.review.head_revision != attestation.fdai_revision
        ):
            raise DirectApiPreconditionError(
                "promotion review attestation does not match the exact request"
            )
        override_request = request.action_type_name == OVERRIDE_PROMOTION_ACTION_TYPE
        if override_request and not approval_profile_matches(
            attestation.review.approval_profile,
            self._active_approval_profile,
        ):
            receipt = await self._safe_already_applied_receipt(request, attestation)
            if receipt is not None:
                return receipt
            raise DirectApiPreconditionError(
                "promotion review attestation approval profile does not match the active profile"
            )
        decision = validate_governance_review(attestation.review)
        if override_request:
            override_args = override_promotion_arguments(request.arguments)
            _validate_override_decision(
                decision,
                operator_principal=override_args["operator_principal"],
                approval_receipt_digest=override_args["approval_receipt_digest"],
                attestation=attestation,
            )
        else:
            _validate_gate_promotion_decision(decision)
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


def _validate_gate_promotion_decision(decision: ReviewAuthorityDecision) -> None:
    if (
        decision.change_class is not GovernanceChangeClass.ENFORCE_PROMOTION
        or not decision.allowed
        or decision.satisfied_quorum < decision.required_quorum
        or len(decision.counted_approver_oids) < 2
    ):
        raise DirectApiPreconditionError(
            "promotion requires an approved distinct-approver governance transition"
        )


def _validate_override_decision(
    decision: ReviewAuthorityDecision,
    *,
    operator_principal: object,
    approval_receipt_digest: object,
    attestation: GovernancePromotionAttestation,
) -> None:
    if (
        decision.change_class is not GovernanceChangeClass.OPERATOR_OVERRIDE_PROMOTION
        or not decision.allowed
        or decision.satisfied_quorum < decision.required_quorum
    ):
        raise DirectApiPreconditionError(
            "override promotion requires an approved governance override transition"
        )
    if not isinstance(operator_principal, str) or (
        operator_principal.casefold() not in decision.counted_approver_oids
        and operator_principal.casefold() != (decision.operator_principal or "").casefold()
    ):
        raise DirectApiPreconditionError(
            "override promotion operator MUST be a counted governance approver"
        )
    if approval_receipt_digest != promotion_attestation_digest(attestation):
        raise DirectApiPreconditionError(
            "override promotion approval receipt digest does not match the Var attestation"
        )


def promotion_request_fingerprint(request: DirectApiRequest) -> str:
    """Hash every request field that can affect promotion semantics."""
    arguments = dict(request.arguments)
    if request.action_type_name == OVERRIDE_PROMOTION_ACTION_TYPE:
        arguments.pop("approval_receipt_digest", None)
    payload = {
        "action_id": str(request.action_id),
        "arguments": arguments,
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
    "OperatorOverridePromotionDirectApiExecutor",
    "GovernancePromotionDispatcher",
    "GovernancePromotionAttestation",
    "PromotionAttestationStore",
    "PromotionReservation",
    "StateStorePromotionAttestationStore",
    "promotion_request_fingerprint",
    "OperationalPromotionReceiptReader",
    "PROMOTION_ACTION_TYPE",
    "OVERRIDE_PROMOTION_ACTION_TYPE",
    "PersistedActionPromotionRegistry",
]
