"""One poll: fetch, admit, verify inputs, dry-run, report, and in apply mode apply the Plan.

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

In apply mode (``AgentDependencies.apply``), step 6 first renders the workload, runs the
preflight in ``Workload.preflight``, and journals the rollback target, then reports
``apply-started``. Only after the Hub accepts that report does the agent apply, verify the
rollout, and roll back on failure. It reports ``applied`` or ``rolled-back`` with the next
attempt, then the new state snapshot. The journal in ``journal.py`` makes each step resumable
without applying a Plan twice. A failed rollback halts every later apply.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_plan import (
    LifecycleEffectEnvelope,
    LifecyclePlan,
    PlanAdmissionState,
    SignatureVerifier,
    decode_canonical_plan_payload,
    evaluate_plan_admission,
)
from fdai_deployment_cli.lifecycle_release import is_product_id

from fdai_lifecycle_agent.configuration_rendering import (
    prepare_workload,
    validate_entity_configuration,
)
from fdai_lifecycle_agent.configuration_revision import FullRevisionBinding
from fdai_lifecycle_agent.dry_run import (
    ChangeSetCalculator,
    CurrentState,
    EntityState,
    Health,
    compute_change_set,
    snapshot_document,
)
from fdai_lifecycle_agent.hub_client import (
    HubClient,
    HubProtocolError,
    PlanReport,
    validate_path_segment,
)
from fdai_lifecycle_agent.inputs import (
    ArtifactStore,
    InputRejectedError,
    VerifiedConfiguration,
    VerifiedRelease,
    verify_configuration,
    verify_release,
)
from fdai_lifecycle_agent.journal import ApplyJournal, WorkloadState, WorkloadStore
from fdai_lifecycle_agent.native_cluster import NativeCluster
from fdai_lifecycle_agent.native_state import NativeStateStore
from fdai_lifecycle_agent.signatures import ArtifactVerifier
from fdai_lifecycle_agent.state import (
    AgentState,
    AgentStateError,
    LocalStateStore,
    PlanRecord,
    PlanResult,
)
from fdai_lifecycle_agent.workload import Workload, WorkloadError, object_key

type PollOutcome = Literal[
    "no-plan",
    "malformed-plan",
    "dry-run-admitted",
    "rejected",
    "already-reported",
    "apply-started",
    "applied",
    "rolled-back",
    "halted",
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
    APPLY_STARTED = "apply_started"
    APPLIED = "applied"
    HEALTH_CHECK_FAILED = "health_check_failed"
    APPLY_FAILED = "apply_failed"
    ROLLBACK_FAILED = "rollback_failed"
    PLAN_EXPIRED = "plan_expired"
    WORKLOAD_RENDER_FAILED = "workload_render_failed"


# Admission rejections whose bytes no configured Hub key signed. Blocking their sequence would let
# unauthenticated bytes block a later genuine Plan. Tests pin these to the admission reason codes.
UNVERIFIED_REJECTIONS = frozenset({"plan_signature_invalid", "plan_payload_mismatch"})

_LOGGER = logging.getLogger("fdai.lifecycle_agent")
# The Hub accepts a state snapshot only when its observed_at is newer than the last one.
_MIN_STATE_STEP = timedelta(milliseconds=1)


@dataclass(frozen=True, slots=True)
class HubTrust:
    """Local Hub key trust: active key epochs, revoked key ids, and the fencing generation."""

    hub_key_epochs: Mapping[str, int]
    revoked_hub_key_ids: frozenset[str]
    current_hub_key_epoch: int
    fencing_generation: int


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """Local hard policy: ``maximum_envelope``, the Release components each Entity runs, and,
    for apply mode, the image repository of each component."""

    installation_id: str
    trust: HubTrust
    maximum_envelope: LifecycleEffectEnvelope
    entity_components: Mapping[str, frozenset[str]]
    component_repositories: Mapping[str, str] = field(default_factory=dict)
    product: str | None = None
    native_scope_digest: str | None = None

    def __post_init__(self) -> None:
        validate_path_segment(self.installation_id, "installation_id")
        uncovered = self.maximum_envelope.entity_ids - {
            entity_id for entity_id, components in self.entity_components.items() if components
        }
        if uncovered:
            raise ValueError("every envelope Entity MUST name at least one Release component")
        if self.product is not None and not is_product_id(self.product):
            raise ValueError("local policy product must be an application identifier")
        if self.native_scope_digest is not None and (
            self.product is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.native_scope_digest) is None
        ):
            raise ValueError("native local policy requires a product and exact scope digest")


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplyMode:
    """Apply-mode seams. Only ``workload`` writes to Kubernetes, inside its one namespace."""

    workload: Workload
    store: WorkloadStore
    write_current_state: Callable[[Mapping[str, object]], None]


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentDependencies:
    """Injected seams. Without ``apply``, none of them writes to Kubernetes or Azure."""

    hub: HubClient
    state_store: LocalStateStore
    artifact_store: ArtifactStore
    verify_plan_signature: SignatureVerifier
    verify_release_signature: ArtifactVerifier
    verify_configuration_signature: ArtifactVerifier
    read_current_state: Callable[[], CurrentState]
    clock: Callable[[], datetime]
    compute_change_set: ChangeSetCalculator = compute_change_set
    apply: ApplyMode | None = None
    configuration_binding: FullRevisionBinding | None = field(default=None, repr=False)


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
    """Facade over one installation's poll loop. Only apply mode holds a Kubernetes client."""

    def __init__(self, settings: AgentSettings, deps: AgentDependencies) -> None:
        self._settings = settings
        self._deps = deps

    def poll_once(self) -> PollResult:
        """Run one poll under the exclusive state lock.

        Raises ``HubProtocolError`` when the Plan fetch fails and ``AgentStateError`` when local
        state is locked, unreadable, or unwritable.
        """

        with self._deps.state_store.lock():
            if (apply := self._deps.apply) is not None:
                path = NativeStateStore(self._deps.state_store.path.parent).path
                pinned = self._settings.native_scope_digest is not None
                if pinned != isinstance(apply.workload.cluster, NativeCluster) or (
                    not pinned and (path.exists() or path.is_symlink())
                ):
                    raise WorkloadError("native_scope_poll_mode_changed")
            return self._poll()

    def _poll(self) -> PollResult:
        current = self._read_current_state()
        if (apply := self._deps.apply) is not None:
            workload_state = apply.store.load()
            journal = workload_state.journal
            # Work that may have touched the cluster finishes before anything else.
            if journal is not None and journal.phase != "prepared":
                return self._continue(apply, workload_state, journal)
            if (halted_plan_id := apply.store.halted_plan_id()) is not None:
                _log("lifecycle_agent.halted", level=logging.ERROR, plan_id=halted_plan_id)
                return PollResult(
                    outcome="halted",
                    reason_code=AgentReason.ROLLBACK_FAILED,
                    plan_id=halted_plan_id,
                )
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
            _ADMITTED_EVENTS.get(result.outcome, "lifecycle_agent.plan_rejected"),
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
        return self._deliver_then_apply(
            state.with_result(plan.plan_id, record), plan.plan_id, record
        )

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
            if existing.result.outcome == "apply-started" and self._deps.apply is not None:
                # Reported, then interrupted before the apply began; the journal decides.
                return self._apply(self._deps.apply, plan.plan_id)
            return _poll_result(plan.plan_id, existing, outcome="already-reported")
        return self._deliver_then_apply(state, plan.plan_id, existing)

    def _evaluate(
        self, plan: LifecyclePlan, state: AgentState, current: CurrentState, payload_digest: str
    ) -> PlanResult:
        """Return the local result for one Plan. Only apply mode writes, and only its journal."""

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
            release = verify_release(
                plan, deps.artifact_store, deps.verify_release_signature, product=settings.product
            )
            configuration = verify_configuration(
                plan,
                deps.artifact_store,
                deps.verify_configuration_signature,
                full_revision=deps.configuration_binding,
                release=release,
                managed_entities=settings.maximum_envelope.entity_ids,
            )
            entity_images = release.entity_images(settings.entity_components, plan.entity_ids)
        except InputRejectedError as error:
            return _rejection(error.reason_code, retryable=error.retryable)
        maximum = configuration.narrow(release.maximum_envelope(settings.maximum_envelope))
        if not plan.envelope.narrowed_by(maximum):
            return _rejection(AgentReason.PLAN_ENVELOPE_EXCEEDS_SIGNED_MAXIMUM)
        try:
            validate_entity_configuration(
                configuration,
                settings.entity_components,
                current_schema=current.schema_revision,
                release=release,
                plan=plan,
            )
        except WorkloadError as error:
            return _rejection(error.reason_code)
        change_set = deps.compute_change_set(plan, entity_images, current)
        # Admission bounded the Plan Entities; an injected calculator must stay inside them too.
        if not change_set.entity_ids <= plan.envelope.entity_ids:
            return _rejection(AgentReason.CHANGE_EXCEEDS_ENVELOPE)
        result = PlanResult(
            outcome="dry-run-admitted",
            reason_code=AgentReason.DRY_RUN_COMPUTED,
            exact_plan_digest=f"sha256:{payload_digest}",
            summary=change_set.sanitized_summary(),
        )
        if deps.apply is None:
            return result
        return self._prepare(deps.apply, plan, release, configuration, entity_images, result)

    def _prepare(
        self,
        apply: ApplyMode,
        plan: LifecyclePlan,
        release: VerifiedRelease,
        configuration: VerifiedConfiguration,
        entity_images: Mapping[str, frozenset[str]],
        admitted: PlanResult,
    ) -> PlanResult:
        """Render, preflight, and journal the rollback target; return ``apply-started``."""

        settings = self._settings
        try:
            desired, previous = prepare_workload(
                plan,
                release,
                configuration,
                entity_components=settings.entity_components,
                component_repositories=settings.component_repositories,
                workload=apply.workload,
                store=apply.store,
            )
        except WorkloadError as error:
            return _rejection(error.reason_code, retryable=error.retryable)
        workload_state = apply.store.load()
        journal = ApplyJournal(
            plan_id=plan.plan_id,
            phase="prepared",
            expires_at=plan.expires_at,
            target_release_id=plan.target_release_id,
            entity_images=entity_images,
            desired=desired,
            previous=previous,
        )
        apply.store.save(replace(workload_state, journal=journal))
        return replace(admitted, outcome="apply-started", reason_code=AgentReason.APPLY_STARTED)

    def _deliver_then_apply(
        self, state: AgentState, plan_id: str, record: PlanRecord
    ) -> PollResult:
        """Deliver the pending report; apply only once the Hub accepted ``apply-started``."""

        result = self._deliver(state, plan_id, record)
        if result.outcome == "apply-started" and result.reported and self._deps.apply is not None:
            return self._apply(self._deps.apply, plan_id)
        return result

    def _apply(self, apply: ApplyMode, plan_id: str) -> PollResult:
        """Apply a ``prepared`` journal once, verify the rollout, and roll back on failure."""

        workload_state = apply.store.load()
        journal = workload_state.journal
        if journal is None or journal.plan_id != plan_id or journal.phase != "prepared":
            # A later Plan replaced the journal; this one never touched the cluster.
            record = self._record(self._deps.state_store.load(), plan_id)
            return _poll_result(plan_id, record, outcome="already-reported")
        if self._deps.clock() >= journal.expires_at:
            _log("lifecycle_agent.plan_expired", level=logging.WARNING, plan_id=plan_id)
            apply.store.save(replace(workload_state, journal=None))
            return self._replace_result(plan_id, _rejection(AgentReason.PLAN_EXPIRED))
        journal = replace(journal, phase="applying")
        apply.store.save(replace(workload_state, journal=journal))
        _log("lifecycle_agent.apply_begun", plan_id=plan_id)
        try:
            healthy = apply.workload.apply(
                journal.desired,
                can_continue=lambda: self._deps.clock() < journal.expires_at,
            )
        except WorkloadError as error:
            _log(
                "lifecycle_agent.apply_failed",
                level=logging.ERROR,
                plan_id=plan_id,
                error=error.reason_code,
            )
            return self._complete(apply, workload_state, journal, AgentReason.APPLY_FAILED)
        failure = None if healthy else AgentReason.HEALTH_CHECK_FAILED
        return self._complete(apply, workload_state, journal, failure)

    def _continue(
        self, apply: ApplyMode, workload_state: WorkloadState, journal: ApplyJournal
    ) -> PollResult:
        if journal.phase == "applying":
            # The agent stopped mid-apply; never apply again, restore the rollback target.
            _log("lifecycle_agent.apply_interrupted", level=logging.ERROR, plan_id=journal.plan_id)
            return self._complete(apply, workload_state, journal, AgentReason.APPLY_FAILED)
        return self._finish(apply, workload_state, journal)

    def _complete(
        self,
        apply: ApplyMode,
        workload_state: WorkloadState,
        journal: ApplyJournal,
        failure: AgentReason | None,
    ) -> PollResult:
        """Roll back on ``failure``, then commit the outcome and the new snapshot in one write."""

        started = self._record(self._deps.state_store.load(), journal.plan_id).result
        current = self._read_current_state()
        entities = dict(current.entities)
        healthy = workload_state.healthy
        if failure is None:
            result = replace(started, outcome="applied", reason_code=AgentReason.APPLIED)
            entities |= {
                entity_id: EntityState(journal.target_release_id, images, Health.HEALTHY)
                for entity_id, images in journal.entity_images.items()
            }
            replaced = {object_key(manifest) for manifest in journal.desired}
            healthy = (
                *(item for item in healthy if object_key(item) not in replaced),
                *(item for item in journal.desired if item["kind"] != "Job"),
            )
        else:
            restored = self._roll_back(apply, journal)
            result = replace(
                started,
                outcome="rolled-back",
                reason_code=failure,
                summary=_with_rollback(started.summary, verified=restored),
            )
            if not restored:
                apply.store.halt(journal.plan_id)
                entities |= {
                    entity_id: replace(entities[entity_id], health=Health.UNHEALTHY)
                    for entity_id in journal.entity_images
                    if entity_id in entities
                }
        snapshot = snapshot_document(
            entities,
            schema_revision=current.schema_revision,
            observed_at=max(self._deps.clock(), current.observed_at + _MIN_STATE_STEP),
            available_artifact_digests=current.available_artifact_digests,
        )
        done = replace(journal, phase="done", result=result, snapshot=snapshot)
        workload_state = WorkloadState(healthy=tuple(healthy), journal=done)
        apply.store.save(workload_state)
        _log(
            "lifecycle_agent.apply_completed",
            level=logging.INFO if failure is None else logging.ERROR,
            plan_id=journal.plan_id,
            outcome=result.outcome,
            reason_code=result.reason_code,
        )
        return self._finish(apply, workload_state, done)

    def _roll_back(self, apply: ApplyMode, journal: ApplyJournal) -> bool:
        if apply.store.halted_plan_id() == journal.plan_id:
            # This Plan's rollback already failed before a restart; never retry it automatically.
            return False
        try:
            restored = apply.workload.roll_back(journal.desired, journal.previous)
        except WorkloadError as error:
            _log(
                "lifecycle_agent.rollback_failed",
                level=logging.ERROR,
                plan_id=journal.plan_id,
                error=error.reason_code,
            )
            return False
        if not restored:
            _log(
                "lifecycle_agent.rollback_unverified", level=logging.ERROR, plan_id=journal.plan_id
            )
        return restored

    def _finish(
        self, apply: ApplyMode, workload_state: WorkloadState, journal: ApplyJournal
    ) -> PollResult:
        """Write the committed snapshot, deliver the final report and the snapshot, and only
        then drop the journal. Each step repeats safely on the next poll."""

        if journal.result is None or journal.snapshot is None:
            raise AgentStateError("a done apply journal MUST hold its result and snapshot")
        try:
            apply.write_current_state(journal.snapshot)
        except OSError as error:
            raise AgentStateError(
                f"current state is not writable: {type(error).__name__}"
            ) from error
        result = self._replace_result(journal.plan_id, journal.result)
        if not result.reported:
            return result
        try:
            self._deps.hub.submit_state(self._settings.installation_id, journal.snapshot)
        except HubProtocolError as error:
            if error.code != "stale_state":
                _log("lifecycle_agent.state_report_failed", level=logging.ERROR, error=str(error))
                return replace(result, reported=False)
            # The Hub already holds a newer snapshot; this one can never land.
            _log("lifecycle_agent.state_report_stale", level=logging.WARNING)
        apply.store.save(replace(workload_state, journal=None))
        _log("lifecycle_agent.state_reported", plan_id=journal.plan_id)
        return result

    def _replace_result(self, plan_id: str, result: PlanResult) -> PollResult:
        """Make ``result`` the Plan's result, reported with the next attempt, and deliver it."""

        state = self._deps.state_store.load()
        record = self._record(state, plan_id)
        if record.result != result:
            record = replace(record, result=result, reported_at=None, reported=False)
            state = state.with_record(plan_id, record)
        if record.reported:
            return _poll_result(plan_id, record)
        return self._deliver(state, plan_id, record)

    @staticmethod
    def _record(state: AgentState, plan_id: str) -> PlanRecord:
        try:
            return state.plans[plan_id]
        except KeyError as error:
            raise AgentStateError("the apply journal names a Plan without a record") from error

    def _read_current_state(self) -> CurrentState:
        try:
            return self._deps.read_current_state()
        except ValueError as error:
            raise AgentStateError(f"current state is invalid: {error}") from error

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


_ADMITTED_EVENTS = {
    "dry-run-admitted": "lifecycle_agent.dry_run_admitted",
    "apply-started": "lifecycle_agent.apply_prepared",
}


def _with_rollback(summary: str, *, verified: bool) -> str:
    """Add whether the rollback was verified to the counts-only summary."""

    document = json.loads(summary) if summary else {}
    document["rollback"] = "verified" if verified else "failed"
    return canonical_bytes(document).decode("ascii")


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
