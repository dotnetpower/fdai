"""Tests for the inert process-local provider acceptance ordering model."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from fdai.core.standing_authority.lease import (
    EffectStatus,
    LeaseOutcome,
    ProviderCommitFenceRequest,
    ProviderCommitFenceResult,
)
from fdai.core.standing_authority.lifecycle_codec import AuthorizationLifecycleError
from fdai.core.standing_authority.provider_acceptance import (
    ProviderAcceptanceAmbiguityReason,
    ProviderAcceptanceIdentity,
    ProviderAcceptanceRecord,
    ProviderAcceptanceState,
    ProviderNonAcceptanceEvidenceKind,
    ProviderSubmissionResult,
    acceptance_effect_status,
    complete_provider_acceptance,
    prepare_provider_acceptance,
    quarantine_orphaned_provider_acceptance,
    validate_provider_acceptance_transition,
)
from fdai.core.standing_authority.provider_acceptance_coordinator import (
    ProviderAcceptanceCoordinator,
    ProviderAcceptancePersistenceError,
    ProviderAcceptanceReentrancyError,
)
from fdai.core.standing_authority.provider_acceptance_store import (
    PROCESS_LOCAL_LINEARIZATION,
    ProviderAcceptanceAcquireDecision,
    ProviderAcceptanceAcquireResult,
    ProviderAcceptanceTransitionReceipt,
    ProviderSubmissionPermit,
    classify_provider_acceptance,
    provider_submission_blocked,
)
from fdai.shared.providers.standing_authority import StandingAuthorizationStoreError

NOW = datetime(2026, 9, 12, 7, 0, tzinfo=UTC)
DIGESTS = {name: "sha256:" + char * 64 for name, char in zip("abcdefgh", "01234567", strict=True)}
SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"


def _identity(**changes: object) -> ProviderAcceptanceIdentity:
    values: dict[str, object] = {
        "target_fence_digest": DIGESTS["a"],
        "family_id": "family:example",
        "authorization_revision_id": DIGESTS["b"],
        "fencing_generation": 3,
        "transition_digest": DIGESTS["c"],
        "lease_id": DIGESTS["d"],
        "lease_generation": 2,
        "lease_valid_until": NOW + timedelta(minutes=5),
        "action_digest": DIGESTS["e"],
        "target_digest": DIGESTS["f"],
        "provider_api_version": "2024-07-01",
        "provider_endpoint_digest": DIGESTS["g"],
        "provider_resource_digest": DIGESTS["h"],
        "provider_body_digest": "sha256:" + "1" * 64,
        "source_revision_id": "2" * 40,
        "safeguard_bundle_digest": "sha256:" + "3" * 64,
        "reservation_identity_digest": "sha256:" + "4" * 64,
        "target_fence_generation": 5,
        "acceptance_generation": 1,
    }
    values.update(changes)
    return ProviderAcceptanceIdentity.create(**values)  # type: ignore[arg-type]


class _Store:
    linearization_scope: Literal["process_local"] = PROCESS_LOCAL_LINEARIZATION

    def __init__(self) -> None:
        self.records: dict[str, ProviderAcceptanceRecord] = {}
        self.lock = asyncio.Lock()
        self.fail_acquire = False
        self.fail_readback = False
        self.fail_transition = False
        self.stamped_prepared_at: datetime | None = None
        self.substitute_identity: ProviderAcceptanceIdentity | None = None
        self.substitute_terminal_state: ProviderAcceptanceState | None = None

    async def acquire_prepared(
        self,
        record: ProviderAcceptanceRecord,
    ) -> ProviderAcceptanceAcquireResult:
        async with self.lock:
            if self.fail_acquire:
                raise OSError("simulated preparation failure")
            if self.substitute_identity is not None:
                record = prepare_provider_acceptance(
                    self.substitute_identity,
                    prepared_at=record.state_changed_at,
                )
            key = record.identity.target_fence_digest
            existing = self.records.get(key)
            if existing is not None:
                return ProviderAcceptanceAcquireResult(
                    candidate_identity=record.identity,
                    decision=classify_provider_acceptance(
                        existing,
                        record.identity,
                    ),
                    observed_record=existing,
                    permit=None,
                )
            stored = (
                prepare_provider_acceptance(
                    record.identity,
                    prepared_at=self.stamped_prepared_at,
                )
                if self.stamped_prepared_at is not None
                else record
            )
            self.records[key] = stored
            return ProviderAcceptanceAcquireResult(
                candidate_identity=record.identity,
                decision=ProviderAcceptanceAcquireDecision.PERMITTED,
                observed_record=stored,
                permit=ProviderSubmissionPermit.create(stored),
            )

    async def compare_and_transition(
        self,
        *,
        prior_record_digest: str,
        expected_revision: int,
        record: ProviderAcceptanceRecord,
    ) -> ProviderAcceptanceTransitionReceipt:
        async with self.lock:
            if self.fail_transition:
                raise OSError("simulated transition failure")
            key = record.identity.target_fence_digest
            existing = self.records.get(key)
            if (
                existing is None
                or existing.record_digest != prior_record_digest
                or existing.revision != expected_revision
            ):
                raise AuthorizationLifecycleError("provider acceptance compare-and-set conflict")
            if self.substitute_terminal_state is not None:
                replacement_result = (
                    _result(
                        ProviderAcceptanceState.NOT_ACCEPTED,
                        kind=(
                            ProviderNonAcceptanceEvidenceKind.PROVIDER_REJECTED_BEFORE_ACCEPTANCE
                        ),
                    )
                    if self.substitute_terminal_state is ProviderAcceptanceState.NOT_ACCEPTED
                    else _result(self.substitute_terminal_state)
                )
                record = complete_provider_acceptance(
                    existing,
                    result=replacement_result,
                    completed_at=record.state_changed_at,
                )
            validate_provider_acceptance_transition(existing, record)
            self.records[key] = record
            return ProviderAcceptanceTransitionReceipt.create(
                prior_record_digest=prior_record_digest,
                record=record,
            )

    async def read(
        self,
        target_fence_digest: str,
    ) -> ProviderAcceptanceRecord | None:
        if self.fail_readback:
            return None
        return self.records.get(target_fence_digest)


class _LeaseStore:
    def __init__(
        self,
        result: ProviderCommitFenceResult | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self.result = result or ProviderCommitFenceResult(
            allowed=True,
            outcome=LeaseOutcome.ACQUIRED,
        )
        self.fail = fail
        self.requests: list[ProviderCommitFenceRequest] = []

    async def check_commit_fence(
        self,
        request: ProviderCommitFenceRequest,
    ) -> ProviderCommitFenceResult:
        self.requests.append(request)
        if self.fail:
            raise StandingAuthorizationStoreError("simulated lease store failure")
        return self.result


class _Submitter:
    def __init__(
        self,
        result: ProviderSubmissionResult | None = None,
        *,
        error: BaseException | None = None,
        block: bool = False,
    ) -> None:
        self.result = result or _result(ProviderAcceptanceState.ACCEPTED)
        self.error = error
        self.calls: list[tuple[ProviderAcceptanceIdentity, ProviderSubmissionPermit]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def submit(
        self,
        *,
        identity: ProviderAcceptanceIdentity,
        permit: ProviderSubmissionPermit,
    ) -> ProviderSubmissionResult:
        self.calls.append((identity, permit))
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.result


def _result(
    state: ProviderAcceptanceState,
    *,
    kind: ProviderNonAcceptanceEvidenceKind | None = None,
    ambiguity: ProviderAcceptanceAmbiguityReason | None = None,
) -> ProviderSubmissionResult:
    return ProviderSubmissionResult.create(
        state=state,
        evidence_digest="sha256:" + "9" * 64,
        non_acceptance_kind=kind,
        ambiguity_reason=ambiguity,
    )


def _coordinator(
    store: _Store | None = None,
    lease_store: _LeaseStore | None = None,
) -> tuple[ProviderAcceptanceCoordinator, _Store, _LeaseStore]:
    provider_store = store or _Store()
    standing_store = lease_store or _LeaseStore()
    return (
        ProviderAcceptanceCoordinator(
            store=provider_store,
            lease_store=standing_store,  # type: ignore[arg-type]
        ),
        provider_store,
        standing_store,
    )


async def test_acceptance_submission_is_one_shot_and_duplicate_safe() -> None:
    coordinator, store, lease_store = _coordinator()
    submitter = _Submitter()
    identity = _identity()

    first = await coordinator.submit_once(
        identity=identity,
        submitter=submitter,
        prepared_at=NOW,
        completed_at=NOW,
    )
    duplicate = await coordinator.submit_once(
        identity=identity,
        submitter=submitter,
        prepared_at=NOW,
        completed_at=NOW,
    )

    assert first.submitted is True
    assert first.record.state is ProviderAcceptanceState.ACCEPTED
    assert duplicate.decision is ProviderAcceptanceAcquireDecision.DUPLICATE_SAME
    assert duplicate.submitted is False
    assert duplicate.record == first.record
    assert len(submitter.calls) == 1
    assert len(lease_store.requests) == 1
    assert store.records[identity.target_fence_digest] == first.record
    assert first.record.result is not None
    assert first.record.result.effect_verified is False


async def test_concurrent_callers_produce_exactly_one_submission() -> None:
    coordinator, _store, _lease_store = _coordinator()
    submitter = _Submitter(block=True)
    identity = _identity()
    first = asyncio.create_task(
        coordinator.submit_once(
            identity=identity,
            submitter=submitter,
            prepared_at=NOW,
            completed_at=NOW,
        )
    )
    await submitter.started.wait()
    second = asyncio.create_task(
        coordinator.submit_once(
            identity=identity,
            submitter=submitter,
            prepared_at=NOW,
            completed_at=NOW,
        )
    )
    await asyncio.sleep(0)
    submitter.release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert len(submitter.calls) == 1
    assert {first_result.submitted, second_result.submitted} == {True, False}


async def test_different_identity_on_same_target_is_blocked() -> None:
    coordinator, _store, _lease_store = _coordinator()
    submitter = _Submitter()

    await coordinator.submit_once(
        identity=_identity(),
        submitter=submitter,
        prepared_at=NOW,
        completed_at=NOW,
    )
    blocked = await coordinator.submit_once(
        identity=_identity(provider_body_digest="sha256:" + "5" * 64),
        submitter=submitter,
        prepared_at=NOW,
        completed_at=NOW,
    )

    assert blocked.decision is ProviderAcceptanceAcquireDecision.BLOCKED
    assert blocked.submitted is False
    assert len(submitter.calls) == 1


@pytest.mark.parametrize(
    "lease_store",
    [
        _LeaseStore(
            ProviderCommitFenceResult(
                allowed=False,
                outcome=LeaseOutcome.STALE_GENERATION,
            )
        ),
        _LeaseStore(fail=True),
    ],
)
async def test_pre_submit_fence_failure_never_invokes_provider(
    lease_store: _LeaseStore,
) -> None:
    coordinator, _store, _ = _coordinator(lease_store=lease_store)
    submitter = _Submitter()

    attempt = await coordinator.submit_once(
        identity=_identity(),
        submitter=submitter,
        prepared_at=NOW,
        completed_at=NOW,
    )

    assert attempt.submitted is False
    assert attempt.record.state is ProviderAcceptanceState.NOT_ACCEPTED
    assert submitter.calls == []


async def test_expired_lease_denies_before_store_or_provider_access() -> None:
    coordinator, _store, lease_store = _coordinator()
    submitter = _Submitter()

    attempt = await coordinator.submit_once(
        identity=_identity(lease_valid_until=NOW),
        submitter=submitter,
        prepared_at=NOW,
        completed_at=NOW,
    )

    assert attempt.record.state is ProviderAcceptanceState.NOT_ACCEPTED
    assert attempt.submitted is False
    assert lease_store.requests == []
    assert submitter.calls == []


@pytest.mark.parametrize(
    "result",
    [
        _result(
            ProviderAcceptanceState.NOT_ACCEPTED,
            kind=(ProviderNonAcceptanceEvidenceKind.PROVIDER_REJECTED_BEFORE_ACCEPTANCE),
        ),
        _result(
            ProviderAcceptanceState.UNKNOWN,
            ambiguity=ProviderAcceptanceAmbiguityReason.PROVIDER_RESULT_UNKNOWN,
        ),
    ],
)
async def test_provider_terminal_results_are_recorded_without_effect_success(
    result: ProviderSubmissionResult,
) -> None:
    coordinator, _store, _lease_store = _coordinator()
    submitter = _Submitter(result=result)

    attempt = await coordinator.submit_once(
        identity=_identity(),
        submitter=submitter,
        prepared_at=NOW,
        completed_at=NOW,
    )

    assert attempt.submitted is True
    assert attempt.record.state is result.state
    assert attempt.record.result == result
    assert attempt.record.result.effect_verified is False


async def test_submitter_cannot_forge_local_non_acceptance() -> None:
    coordinator, store, _lease_store = _coordinator()
    identity = _identity()
    forged = _result(
        ProviderAcceptanceState.NOT_ACCEPTED,
        kind=ProviderNonAcceptanceEvidenceKind.LOCAL_FENCE_DENIED,
    )

    with pytest.raises(AuthorizationLifecycleError, match="provider non-acceptance"):
        await coordinator.submit_once(
            identity=identity,
            submitter=_Submitter(result=forged),
            prepared_at=NOW,
            completed_at=NOW,
        )

    assert store.records[identity.target_fence_digest].state is (ProviderAcceptanceState.UNKNOWN)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (TimeoutError(), ProviderAcceptanceAmbiguityReason.SUBMISSION_TIMEOUT),
        (RuntimeError("synthetic"), ProviderAcceptanceAmbiguityReason.SUBMISSION_EXCEPTION),
        (asyncio.CancelledError(), ProviderAcceptanceAmbiguityReason.SUBMISSION_CANCELLED),
    ],
)
async def test_submission_failure_is_persisted_unknown_before_reraise(
    error: BaseException,
    reason: ProviderAcceptanceAmbiguityReason,
) -> None:
    coordinator, store, _lease_store = _coordinator()
    identity = _identity()

    with pytest.raises(type(error)):
        await coordinator.submit_once(
            identity=identity,
            submitter=_Submitter(error=error),
            prepared_at=NOW,
            completed_at=NOW,
        )

    record = store.records[identity.target_fence_digest]
    assert record.state is ProviderAcceptanceState.UNKNOWN
    assert record.result is not None
    assert record.result.ambiguity_reason is reason
    assert provider_submission_blocked(record)
    assert acceptance_effect_status(record) is EffectStatus.UNKNOWN


async def test_terminal_persist_failure_leaves_prepared_record_blocking() -> None:
    store = _Store()
    store.fail_transition = True
    coordinator, _store, _lease_store = _coordinator(store=store)
    identity = _identity()
    submitter = _Submitter()

    with pytest.raises(ProviderAcceptancePersistenceError):
        await coordinator.submit_once(
            identity=identity,
            submitter=submitter,
            prepared_at=NOW,
            completed_at=NOW,
        )

    assert len(submitter.calls) == 1
    assert store.records[identity.target_fence_digest].state is (ProviderAcceptanceState.PREPARED)
    duplicate = await coordinator.submit_once(
        identity=identity,
        submitter=submitter,
        prepared_at=NOW,
        completed_at=NOW,
    )
    assert duplicate.submitted is False
    assert len(submitter.calls) == 1


async def test_prepare_readback_failure_denies_submit() -> None:
    store = _Store()
    store.fail_readback = True
    coordinator, _store, _lease_store = _coordinator(store=store)
    submitter = _Submitter()

    with pytest.raises(ProviderAcceptancePersistenceError, match="readback"):
        await coordinator.submit_once(
            identity=_identity(),
            submitter=submitter,
            prepared_at=NOW,
            completed_at=NOW,
        )

    assert submitter.calls == []
    assert next(iter(store.records.values())).state is ProviderAcceptanceState.PREPARED


async def test_store_stamped_prepared_record_is_the_cas_predecessor() -> None:
    store = _Store()
    store.stamped_prepared_at = NOW + timedelta(seconds=1)
    coordinator, _store, _lease_store = _coordinator(store=store)

    attempt = await coordinator.submit_once(
        identity=_identity(),
        submitter=_Submitter(),
        prepared_at=NOW,
        completed_at=NOW,
    )

    assert attempt.record.state is ProviderAcceptanceState.ACCEPTED
    assert attempt.record.prior_record_digest is not None
    assert attempt.transition_receipt is not None
    assert attempt.transition_receipt.prior_record_digest == attempt.record.prior_record_digest
    assert attempt.record.state_changed_at == store.stamped_prepared_at


async def test_store_identity_substitution_is_rejected_before_submit() -> None:
    store = _Store()
    store.substitute_identity = _identity(provider_body_digest="sha256:" + "5" * 64)
    coordinator, _store, _lease_store = _coordinator(store=store)
    submitter = _Submitter()

    with pytest.raises(ProviderAcceptancePersistenceError, match="substituted"):
        await coordinator.submit_once(
            identity=_identity(),
            submitter=submitter,
            prepared_at=NOW,
            completed_at=NOW,
        )

    assert submitter.calls == []


async def test_terminal_state_substitution_is_rejected_after_submit() -> None:
    store = _Store()
    store.substitute_terminal_state = ProviderAcceptanceState.NOT_ACCEPTED
    coordinator, _store, _lease_store = _coordinator(store=store)
    submitter = _Submitter()

    with pytest.raises(ProviderAcceptancePersistenceError, match="readback mismatched"):
        await coordinator.submit_once(
            identity=_identity(),
            submitter=submitter,
            prepared_at=NOW,
            completed_at=NOW,
        )

    assert len(submitter.calls) == 1


async def test_prepare_failure_denies_submit_without_fabricating_state() -> None:
    store = _Store()
    store.fail_acquire = True
    coordinator, _store, _lease_store = _coordinator(store=store)
    submitter = _Submitter()

    with pytest.raises(OSError, match="preparation failure"):
        await coordinator.submit_once(
            identity=_identity(),
            submitter=submitter,
            prepared_at=NOW,
            completed_at=NOW,
        )

    assert submitter.calls == []
    assert store.records == {}


async def test_callback_reentrancy_fails_closed_and_quarantines_outer_attempt() -> None:
    coordinator, store, _lease_store = _coordinator()
    identity = _identity()

    class _ReentrantSubmitter:
        async def submit(
            self,
            *,
            identity: ProviderAcceptanceIdentity,
            permit: ProviderSubmissionPermit,
        ) -> ProviderSubmissionResult:
            del permit
            return (
                await coordinator.submit_once(
                    identity=identity,
                    submitter=self,
                    prepared_at=NOW,
                    completed_at=NOW,
                )
            ).record.result or _result(ProviderAcceptanceState.ACCEPTED)

    with pytest.raises(ProviderAcceptanceReentrancyError):
        await coordinator.submit_once(
            identity=identity,
            submitter=_ReentrantSubmitter(),
            prepared_at=NOW,
            completed_at=NOW,
        )

    assert store.records[identity.target_fence_digest].state is (ProviderAcceptanceState.UNKNOWN)


def test_orphan_prepared_moves_only_to_unknown() -> None:
    prepared = prepare_provider_acceptance(_identity(), prepared_at=NOW)
    unknown = quarantine_orphaned_provider_acceptance(
        prepared,
        quarantined_at=NOW,
        evidence_digest="sha256:" + "6" * 64,
    )

    validate_provider_acceptance_transition(prepared, unknown)
    assert unknown.state is ProviderAcceptanceState.UNKNOWN
    assert acceptance_effect_status(prepared) is EffectStatus.UNKNOWN
    assert acceptance_effect_status(unknown) is EffectStatus.UNKNOWN

    with pytest.raises(AuthorizationLifecycleError, match="initial prepared"):
        complete_provider_acceptance(
            unknown,
            result=_result(ProviderAcceptanceState.ACCEPTED),
            completed_at=NOW,
        )


def test_terminal_record_rejects_forged_result_subclass() -> None:
    class _ForgedResult(ProviderSubmissionResult):
        pass

    forged = object.__new__(_ForgedResult)
    object.__setattr__(forged, "state", ProviderAcceptanceState.ACCEPTED)
    object.__setattr__(forged, "evidence_digest", "sha256:" + "8" * 64)
    object.__setattr__(forged, "non_acceptance_kind", None)
    object.__setattr__(forged, "ambiguity_reason", None)
    object.__setattr__(forged, "effect_verified", True)
    object.__setattr__(forged, "execution_authority", True)
    object.__setattr__(forged, "result_digest", "sha256:" + "9" * 64)
    prepared = prepare_provider_acceptance(_identity(), prepared_at=NOW)

    with pytest.raises(AuthorizationLifecycleError, match="exact submission result"):
        complete_provider_acceptance(
            prepared,
            result=forged,
            completed_at=NOW,
        )


def test_every_existing_state_blocks_resubmission() -> None:
    prepared = prepare_provider_acceptance(_identity(), prepared_at=NOW)
    records = (
        prepared,
        complete_provider_acceptance(
            prepared,
            result=_result(ProviderAcceptanceState.ACCEPTED),
            completed_at=NOW,
        ),
        complete_provider_acceptance(
            prepared,
            result=_result(
                ProviderAcceptanceState.NOT_ACCEPTED,
                kind=(ProviderNonAcceptanceEvidenceKind.PROVIDER_REJECTED_BEFORE_ACCEPTANCE),
            ),
            completed_at=NOW,
        ),
        complete_provider_acceptance(
            prepared,
            result=_result(
                ProviderAcceptanceState.UNKNOWN,
                ambiguity=ProviderAcceptanceAmbiguityReason.PROVIDER_RESULT_UNKNOWN,
            ),
            completed_at=NOW,
        ),
    )

    assert set(ProviderAcceptanceState) == {record.state for record in records}
    assert all(provider_submission_blocked(record) for record in records)
    assert provider_submission_blocked(None) is False
    assert [acceptance_effect_status(record) for record in records] == [
        EffectStatus.UNKNOWN,
        EffectStatus.UNKNOWN,
        EffectStatus.NOT_COMMITTED,
        EffectStatus.UNKNOWN,
    ]


def test_non_acceptance_and_unknown_require_closed_evidence_shapes() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="non-acceptance evidence"):
        _result(ProviderAcceptanceState.NOT_ACCEPTED)
    with pytest.raises(AuthorizationLifecycleError, match="ambiguity reason"):
        _result(ProviderAcceptanceState.UNKNOWN)
    with pytest.raises(AuthorizationLifecycleError, match="denial or ambiguity"):
        _result(
            ProviderAcceptanceState.ACCEPTED,
            kind=ProviderNonAcceptanceEvidenceKind.LOCAL_FENCE_DENIED,
        )


def test_identity_is_content_addressed_and_client_id_is_generation_bound() -> None:
    first = _identity()
    replay = _identity()
    next_generation = _identity(acceptance_generation=2)

    assert first == replay
    assert first.identity_digest == replay.identity_digest
    assert first.client_request_id == replay.client_request_id
    assert first.client_request_id != next_generation.client_request_id
    assert first.production_eligible is False

    with pytest.raises(AuthorizationLifecycleError, match="digest mismatch"):
        replace(first, identity_digest="sha256:" + "0" * 64)


def test_permit_requires_initial_prepared_record() -> None:
    prepared = prepare_provider_acceptance(_identity(), prepared_at=NOW)
    accepted = complete_provider_acceptance(
        prepared,
        result=_result(ProviderAcceptanceState.ACCEPTED),
        completed_at=NOW,
    )

    with pytest.raises(AuthorizationLifecycleError, match="initial prepared"):
        ProviderSubmissionPermit.create(accepted)


def test_coordinator_rejects_non_process_local_store() -> None:
    store = _Store()
    store.linearization_scope = "distributed"  # type: ignore[assignment]

    with pytest.raises(ValueError, match="process-local"):
        ProviderAcceptanceCoordinator(
            store=store,
            lease_store=_LeaseStore(),  # type: ignore[arg-type]
        )


def test_provider_acceptance_modules_remain_unwired() -> None:
    forbidden = (
        "fdai.core.standing_authority.provider_acceptance",
        "fdai.core.standing_authority.provider_acceptance_coordinator",
        "fdai.core.standing_authority.provider_acceptance_store",
    )
    roots = (
        "agents",
        "composition",
        "core/control_loop",
        "core/executor",
        "core/hil_resume",
        "core/risk_gate",
        "core/workflow",
        "runtime",
    )
    violations: list[str] = []
    for root in roots:
        path = SOURCE_ROOT / root
        assert path.exists(), f"authority path is missing: {root}"
        candidates = (path,) if path.is_file() else path.rglob("*.py")
        for candidate in candidates:
            tree = ast.parse(candidate.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = (node.module,)
                else:
                    modules = ()
                if any(module.startswith(prefix) for module in modules for prefix in forbidden):
                    violations.append(str(candidate.relative_to(SOURCE_ROOT)))
    assert violations == []
