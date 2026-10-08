"""One Lifecycle I0 poll: fetch, admit, verify inputs, dry-run, and report. Never applies.

One poll holds the exclusive state lock. Order of checks, each failing closed:

1. Read the current-state snapshot, then fetch the Plan. Undecodable bytes are dropped without a
   report, because no Plan id can be trusted.
2. Admit with ``evaluate_plan_admission`` against durable local state and the locally derived
   maximum envelope. A Plan can only narrow that envelope.
3. Refuse a sequence that this agent already rejected.
4. Verify the signed Release and configuration package before any change is computed, then
   require the Plan envelope to fit the maximum derived from local hard policy, the signed
   Release capability maximums, and the configured region.
5. Compute the dry-run change set and confirm it stays inside the Plan envelope.
6. Persist the result and the pending report, then send it: a sanitized summary and the digest
   of the exact Plan bytes (``sha256:`` and the hex SHA-256 of ``signed_payload``), or only a
   rejection reason. A failed send is retried with the identical report on the next poll.

A rejection blocks its sequence durably unless it is retryable: an input that may appear later,
or bytes that no configured Hub key signed. A retryable result is evaluated again on the next poll
and reported again only when it changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Literal

from fdai_deployment_cli.lifecycle_plan import (
    LifecycleEffectEnvelope,
    LifecyclePlan,
    PlanAdmissionState,
    SignatureVerifier,
    decode_canonical_plan_payload,
    evaluate_plan_admission,
)

from fdai_lifecycle_agent.dry_run import ChangeSetCalculator, CurrentState, compute_change_set
from fdai_lifecycle_agent.hub_client import (
    HubClient,
    HubProtocolError,
    PlanReport,
    validate_path_segment,
)
from fdai_lifecycle_agent.inputs import (
    ArtifactStore,
    InputRejectedError,
    verify_configuration,
    verify_release,
)
from fdai_lifecycle_agent.signatures import ArtifactVerifier
from fdai_lifecycle_agent.state import (
    AgentState,
    AgentStateError,
    LocalStateStore,
    PlanRecord,
    PlanResult,
)

type PollOutcome = Literal[
    "no-plan", "malformed-plan", "dry-run-admitted", "rejected", "already-reported"
]


class AgentReason(StrEnum):
    """Reason codes the agent adds to the admission and input reason codes."""

    NO_PLAN_PENDING = "no_plan_pending"
    PLAN_PAYLOAD_MALFORMED = "plan_payload_malformed"
    PLAN_ID_CONFLICT = "plan_id_conflict"
    PLAN_SEQUENCE_PREVIOUSLY_REJECTED = "plan_sequence_previously_rejected"
    PLAN_ENVELOPE_EXCEEDS_SIGNED_MAXIMUM = "plan_envelope_exceeds_signed_maximum"
    CHANGE_EXCEEDS_ENVELOPE = "change_exceeds_envelope"
    DRY_RUN_COMPUTED = "dry_run_computed"


# Admission rejections whose bytes no configured Hub key signed. Blocking their sequence would let
# unauthenticated bytes block a later genuine Plan. Tests pin these to the admission reason codes.
UNVERIFIED_REJECTIONS = frozenset({"plan_signature_invalid", "plan_payload_mismatch"})

_LOGGER = logging.getLogger("fdai.lifecycle_agent")


@dataclass(frozen=True, slots=True)
class HubTrust:
    """Local Hub key trust: active key epochs, revoked key ids, and the fencing generation."""

    hub_key_epochs: Mapping[str, int]
    revoked_hub_key_ids: frozenset[str]
    current_hub_key_epoch: int
    fencing_generation: int


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """Local hard policy: ``maximum_envelope`` and the Release components each Entity runs."""

    installation_id: str
    trust: HubTrust
    maximum_envelope: LifecycleEffectEnvelope
    entity_components: Mapping[str, frozenset[str]]

    def __post_init__(self) -> None:
        validate_path_segment(self.installation_id, "installation_id")
        uncovered = self.maximum_envelope.entity_ids - {
            entity_id for entity_id, components in self.entity_components.items() if components
        }
        if uncovered:
            raise ValueError("every envelope Entity MUST name at least one Release component")


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentDependencies:
    """Injected seams. None of them may write to Kubernetes or Azure."""

    hub: HubClient
    state_store: LocalStateStore
    artifact_store: ArtifactStore
    verify_plan_signature: SignatureVerifier
    verify_release_signature: ArtifactVerifier
    verify_configuration_signature: ArtifactVerifier
    read_current_state: Callable[[], CurrentState]
    clock: Callable[[], datetime]
    compute_change_set: ChangeSetCalculator = compute_change_set


@dataclass(frozen=True, slots=True, kw_only=True)
class PollResult:
    """Local outcome of one poll. ``reported`` is false when a required report did not land."""

    outcome: PollOutcome
    reason_code: str
    plan_id: str | None = None
    exact_plan_digest: str | None = None
    reported: bool = False

    def to_json(self) -> dict[str, object]:
        return asdict(self)


class LifecycleAgent:
    """Facade over one installation's poll loop. Holds no Kubernetes or Azure client."""

    def __init__(self, settings: AgentSettings, deps: AgentDependencies) -> None:
        self._settings = settings
        self._deps = deps

    def poll_once(self) -> PollResult:
        """Run one poll under the exclusive state lock.

        Raises ``HubProtocolError`` when the Plan fetch fails and ``AgentStateError`` when local
        state is locked, unreadable, or unwritable.
        """

        with self._deps.state_store.lock():
            return self._poll()

    def _poll(self) -> PollResult:
        try:
            current = self._deps.read_current_state()
        except ValueError as error:
            raise AgentStateError(f"current state is invalid: {error}") from error
        signed = self._deps.hub.fetch_plan(self._settings.installation_id)
        if signed is None:
            _log("lifecycle_agent.no_plan")
            return PollResult(outcome="no-plan", reason_code=AgentReason.NO_PLAN_PENDING)
        try:
            plan = decode_canonical_plan_payload(signed.signed_payload, signed.signature)
        except (TypeError, ValueError):
            _log("lifecycle_agent.plan_malformed", level=logging.WARNING)
            return PollResult(
                outcome="malformed-plan", reason_code=AgentReason.PLAN_PAYLOAD_MALFORMED
            )

        state = self._deps.state_store.load()
        payload_digest = hashlib.sha256(signed.signed_payload).hexdigest()
        existing = state.plans.get(plan.plan_id)
        if existing is not None and not existing.result.retryable:
            return self._resume(state, plan, payload_digest, existing)

        result = self._evaluate(plan, state, current, payload_digest)
        if existing is not None and existing.result == result:
            if existing.reported:
                return _poll_result(plan.plan_id, existing, outcome="already-reported")
            return self._deliver(state, plan.plan_id, existing)
        _log(
            "lifecycle_agent.dry_run_admitted"
            if result.admitted
            else "lifecycle_agent.plan_rejected",
            level=logging.INFO if result.admitted else logging.WARNING,
            plan_id=plan.plan_id,
            sequence=plan.sequence,
            reason_code=result.reason_code,
            retryable=result.retryable,
        )
        record = PlanRecord(
            sequence=plan.sequence,
            payload_digest=payload_digest,
            result=result,
            attempts=existing.attempts if existing is not None else 0,
        )
        return self._deliver(state.with_result(plan.plan_id, record), plan.plan_id, record)

    def _resume(
        self, state: AgentState, plan: LifecyclePlan, payload_digest: str, existing: PlanRecord
    ) -> PollResult:
        """Handle a Plan id with a final local result: finish its report or refuse other bytes."""

        if existing.payload_digest != payload_digest or existing.sequence != plan.sequence:
            # The Hub reused a Plan id for other bytes. The id already holds a final result, so
            # nothing is reported for it again; the operator sees the error and the exit code.
            _log("lifecycle_agent.plan_id_conflict", level=logging.ERROR, plan_id=plan.plan_id)
            return PollResult(
                outcome="rejected", reason_code=AgentReason.PLAN_ID_CONFLICT, plan_id=plan.plan_id
            )
        if existing.reported:
            return _poll_result(plan.plan_id, existing, outcome="already-reported")
        return self._deliver(state, plan.plan_id, existing)

    def _evaluate(
        self, plan: LifecyclePlan, state: AgentState, current: CurrentState, payload_digest: str
    ) -> PlanResult:
        """Return the local result for one Plan without side effects."""

        deps = self._deps
        decision = evaluate_plan_admission(
            plan,
            local_state=self._admission_state(state, current),
            locally_derived_maximum=self._settings.maximum_envelope,
            verify_signature=deps.verify_plan_signature,
            trusted_now=deps.clock(),
        )
        if not decision.allowed:
            return _rejection(
                decision.reason_code, retryable=decision.reason_code in UNVERIFIED_REJECTIONS
            )
        if plan.sequence in state.rejected_sequences:
            return _rejection(AgentReason.PLAN_SEQUENCE_PREVIOUSLY_REJECTED)
        settings = self._settings
        try:
            release = verify_release(plan, deps.artifact_store, deps.verify_release_signature)
            configuration = verify_configuration(
                plan, deps.artifact_store, deps.verify_configuration_signature
            )
            entity_images = release.entity_images(settings.entity_components, plan.entity_ids)
        except InputRejectedError as error:
            return _rejection(error.reason_code, retryable=error.retryable)
        maximum = configuration.narrow(release.maximum_envelope(settings.maximum_envelope))
        if not plan.envelope.narrowed_by(maximum):
            return _rejection(AgentReason.PLAN_ENVELOPE_EXCEEDS_SIGNED_MAXIMUM)
        change_set = deps.compute_change_set(plan, entity_images, current)
        # Admission bounded the Plan Entities; an injected calculator must stay inside them too.
        if not change_set.entity_ids <= plan.envelope.entity_ids:
            return _rejection(AgentReason.CHANGE_EXCEEDS_ENVELOPE)
        return PlanResult(
            outcome="dry-run-admitted",
            reason_code=AgentReason.DRY_RUN_COMPUTED,
            exact_plan_digest=f"sha256:{payload_digest}",
            summary=change_set.sanitized_summary(),
        )

    def _admission_state(self, state: AgentState, current: CurrentState) -> PlanAdmissionState:
        trust = self._settings.trust
        return PlanAdmissionState(
            expected_audience=self._settings.installation_id,
            expected_source_state_digest=current.digest,
            last_accepted_sequence=state.last_accepted_sequence,
            current_hub_key_epoch=trust.current_hub_key_epoch,
            current_fencing_generation=trust.fencing_generation,
            active_hub_key_ids=frozenset(trust.hub_key_epochs) - trust.revoked_hub_key_ids,
            revoked_hub_key_ids=trust.revoked_hub_key_ids,
            hub_key_epochs=trust.hub_key_epochs,
        )

    def _deliver(self, state: AgentState, plan_id: str, record: PlanRecord) -> PollResult:
        """Send the pending report, persisted first, and mark it reported only on acceptance.

        A record without a pending report gets the next attempt number and a timestamp. A retry
        resends that identical report, which the Hub accepts as a duplicate. When the Hub reports
        that the attempt already holds other content, the next poll starts a new attempt.
        """

        reported_at = record.reported_at
        if reported_at is None:
            reported_at = self._deps.clock()
            record = replace(
                record, attempts=record.attempts + 1, reported_at=reported_at, reported=False
            )
            state = state.with_record(plan_id, record)
            self._deps.state_store.save(state)
        result = record.result
        report = PlanReport(
            attempt=record.attempts,
            outcome=result.outcome,
            reason_code=result.reason_code,
            exact_plan_digest=result.exact_plan_digest,
            summary=result.summary,
            reported_at=reported_at,
        )
        try:
            self._deps.hub.submit_report(self._settings.installation_id, plan_id, report)
        except HubProtocolError as error:
            _log(
                "lifecycle_agent.report_failed",
                level=logging.ERROR,
                plan_id=plan_id,
                attempt=record.attempts,
                error=str(error),
            )
            if error.code == "report_conflict":
                self._deps.state_store.save(
                    state.with_record(plan_id, replace(record, reported_at=None))
                )
            return _poll_result(plan_id, record)
        record = replace(record, reported=True)
        self._deps.state_store.save(state.with_record(plan_id, record))
        _log("lifecycle_agent.reported", plan_id=plan_id, attempt=record.attempts)
        return _poll_result(plan_id, record)


def _rejection(reason_code: str, *, retryable: bool = False) -> PlanResult:
    return PlanResult(outcome="rejected", reason_code=reason_code, retryable=retryable)


def _poll_result(
    plan_id: str, record: PlanRecord, *, outcome: PollOutcome | None = None
) -> PollResult:
    return PollResult(
        outcome=outcome or record.result.outcome,
        reason_code=record.result.reason_code,
        plan_id=plan_id,
        exact_plan_digest=record.result.exact_plan_digest,
        reported=record.reported,
    )


def _log(event: str, *, level: int = logging.INFO, **fields: object) -> None:
    _LOGGER.log(level, json.dumps({"event": event, **fields}, sort_keys=True))
