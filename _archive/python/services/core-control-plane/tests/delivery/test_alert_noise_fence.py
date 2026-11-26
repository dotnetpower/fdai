"""Unexecuted no-network fence mechanics using explicit in-memory lock and DE fixtures.

An admitted writer restriction here is simulated test data, NOT a deployed exclusive-writer
mechanism. These tests neither grant permissions nor demonstrate provider commit continuity.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.executor.safeguards import full_action_digest
from fdai.delivery.alert_noise_authority import (
    ALERT_DISPATCH_PURPOSE,
    ALERT_RECOVERY_DISPATCH_PURPOSE,
    alert_dispatch_binding,
)
from fdai.delivery.alert_noise_fence import (
    ALERT_WRITER_EXCLUSIVITY_PURPOSE,
    AlertLockTrust,
    StateStoreAlertAuthorityFence,
    alert_writer_binding,
)
from fdai.delivery.persistence.state_store_decision_evidence import decision_evidence_state_key
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    ResourceLockReleaseState,
)
from fdai_service_contracts.ontology_query import content_digest

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.delivery.test_alert_noise_authority import (
    EXECUTOR,
    _recovery_fixture,
)
from tests.delivery.test_alert_noise_authority import authority_case as authority_case
from tests.delivery.test_alert_noise_evidence import (
    ANCHOR,
    SCOPE_KEY,
    SOURCE,
    _install_record,
)
from tests.delivery.test_alert_noise_evidence import ledger as ledger

REPOSITORY = "repository:example"
REPOSITORY_REVISION = "commit:" + "b" * 40
LOCK_TRUST = AlertLockTrust(
    provider_id="fdai-in-memory-resource-lock",
    provider_version="1.0.0",
    verifier_id="fdai-in-memory-lock-readback",
    verifier_version="1.0.0",
    trust_anchor_id="fdai:local-test-only",
)


class _TrackingLock(ResourceLockManager):
    """Real local evidenced-lock mechanics with test-only acquisition visibility."""

    def __init__(self, clock):
        super().__init__(clock=clock, acquisition_id_factory=lambda: "fixture-alert")
        self.requests, self.handles = [], []

    @asynccontextmanager
    async def acquire_evidenced(self, request):
        self.requests.append(request)
        async with super().acquire_evidenced(request) as held:
            self.handles.append(held)
            yield held


async def _fence_case(h, *, recovery=None, install_writer=True, production=False):
    action, pr = (recovery.action, recovery.pr) if recovery is not None else (h.action, h.pr)
    reader = h.recovery_reader if recovery is not None else h.reader
    authority = (
        await reader.read(action=action, plan=h.plan)
        if recovery is not None
        else await reader.read(h.plan)
    )
    binding = alert_dispatch_binding(
        action=action,
        plan=h.plan,
        pr=pr,
        authority=authority,
        evidence_receipt_digest=None if recovery is not None else h.source_receipt.receipt_digest,
        evaluation_admission_digest=None,
    )
    dispatch_key = (
        "alert-noise:recovery-dispatch:" if recovery is not None else "alert-noise:dispatch:"
    ) + full_action_digest(action)
    dispatch_receipt, _ = await _install_record(
        h,
        key=dispatch_key,
        payload=binding,
        purpose=ALERT_RECOVERY_DISPATCH_PURPOSE if recovery is not None else ALERT_DISPATCH_PURPOSE,
    )
    until = (h.clock[0] + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    writer = dict(
        binding=alert_writer_binding(
            action=action,
            plan=h.plan,
            pr=pr,
            repository_ref=REPOSITORY,
            repository_revision=REPOSITORY_REVISION,
        ),
        writer_ref=EXECUTOR,
        mechanism_ref="mechanism:fixture",
        restriction_digest="sha256:" + "d" * 64,
        generation=1,
        exclusive_from=h.clock[0].isoformat().replace("+00:00", "Z"),
        exclusive_until=until,
        release_not_before=until,
        release_ref="release:fixture",
        released_at=None,
        dispatch_receipt_digest=dispatch_receipt.receipt_digest,
        execution_authority=False,
    )
    key = "alert-noise:writer-exclusivity:" + full_action_digest(action)
    if install_writer:
        await _install_record(h, key=key, payload=writer, purpose=ALERT_WRITER_EXCLUSIVITY_PURPOSE)
    lock = _TrackingLock(lambda: h.clock[0])
    options = dict(
        store=h.store,
        admissions=h.admissions,
        lock=lock,
        lock_trust=LOCK_TRUST,
        verification_trust_anchor_id=ANCHOR,
        authority=h.reader,
        recovery=h.recovery_reader,
        policy=h.policy,
        scope_ref=h.plan.scope_ref,
        tenant_ref=h.plan.tenant_ref,
        repository_ref=REPOSITORY,
        repository_revision=REPOSITORY_REVISION,
        writer_ref=EXECUTOR,
        source_revision=SOURCE,
        clock=lambda: h.clock[0],
        production=production,
    )
    return SimpleNamespace(
        fence=StateStoreAlertAuthorityFence(**options),
        lock=lock,
        options=options,
        writer=writer,
        key=key,
        dispatch_key=dispatch_key,
        dispatch_binding=binding,
        action=action,
        pr=pr,
        proof=recovery.receipt if recovery is not None else h.dispatch,
        approvals=() if recovery is not None else h.approvals,
    )


async def _current(h, case, lease):
    await lease.require_current(
        action=case.action,
        plan=h.plan,
        pr=case.pr,
        evidence=case.proof,
        approvals=case.approvals,
        now=h.clock[0],
    )


async def test_all_sorted_dependencies_are_evidenced_and_distinct_from_coordinator_root(
    authority_case,
):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        assert [request.target_ref for request in case.lock.requests] == [
            "alert-noise-exclusive:" + ref for ref in sorted(h.plan.lock_refs)
        ]
        assert all(
            request.target_ref != h.action.target_resource_ref for request in case.lock.requests
        )
        with pytest.raises(AlertExecutionHeld, match="inactive"):
            lease.require_active(now=h.clock[0])
        await _current(h, case, lease)
        lease.require_active(now=h.clock[0])
        assert all(case.lock.snapshot().values())
    assert case.lock.snapshot() == {}
    assert all(
        held.release_receipt.state is ResourceLockReleaseState.RELEASED
        for held in case.lock.handles
    )
    with pytest.raises(AlertExecutionHeld, match="inactive"):
        lease.require_active(now=h.clock[0])


async def test_production_rejects_local_lock_even_with_all_fixture_admissions(authority_case):
    h = authority_case
    case = await _fence_case(h, production=True)
    with pytest.raises(AlertExecutionHeld):
        async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr):
            pytest.fail("A local lock cannot become production eligible")
    assert not case.lock.requests


async def test_no_writer_mechanism_proof_means_no_lease_not_an_advisory_fallback(authority_case):
    h = authority_case
    case = await _fence_case(h, install_writer=False)
    with pytest.raises(AlertExecutionHeld, match="unverified"):
        async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr):
            pytest.fail("Locks alone cannot establish provider writer exclusion")
    assert case.lock.snapshot() == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("writer_ref", "principal:" + "f" * 64),
        ("generation", 0),
        ("generation", True),
        ("generation", "1"),
        ("execution_authority", True),
        ("execution_authority", 0),
        ("portal_role_granted", True),
        ("released_at", "2026-09-14T12:00:00Z"),
        ("release_not_before", "2026-09-14T12:00:00Z"),
        ("exclusive_from", "2026-09-15T12:00:00Z"),
        ("exclusive_until", "2026-09-14T12:04:59Z"),
    ],
)
async def test_writer_exclusion_requires_closed_current_protected_window(
    authority_case, field, value
):
    h = authority_case
    case = await _fence_case(h)
    await _install_record(
        h,
        key=case.key,
        payload={**case.writer, field: value},
        purpose=ALERT_WRITER_EXCLUSIVITY_PURPOSE,
    )
    with pytest.raises(AlertExecutionHeld):
        async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr):
            pytest.fail("Malformed or released writer restrictions cannot yield a lease")
    assert case.lock.snapshot() == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("dependency_refs", []),
        ("source_digest", "sha256:" + "f" * 64),
        ("patch_digest", "sha256:" + "f" * 64),
        ("action_digest", "sha256:" + "f" * 64),
        ("plan_digest", "sha256:" + "f" * 64),
        ("repository_ref", "repository:other"),
        ("repository_revision", "commit:" + "f" * 40),
        ("path", "infra/other.tf.json"),
        ("execution_authority", 0),
    ],
)
async def test_admitted_exclusion_cannot_be_rebound_to_a_different_publication(
    authority_case, field, value
):
    h = authority_case
    case = await _fence_case(h)
    writer = {**case.writer, "binding": {**case.writer["binding"], field: value}}
    await _install_record(h, key=case.key, payload=writer, purpose=ALERT_WRITER_EXCLUSIVITY_PURPOSE)
    with pytest.raises(AlertExecutionHeld):
        async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr):
            pytest.fail("The exact patch and all dependency bindings are mandatory")


async def test_writer_trust_is_read_from_actual_independent_bundle_not_a_payload_label(
    authority_case,
):
    h = authority_case
    case = await _fence_case(h)
    await _install_record(
        h,
        key=case.key,
        payload=case.writer,
        purpose=ALERT_WRITER_EXCLUSIVITY_PURPOSE,
        anchor="fixture:wrong-anchor",
    )
    with pytest.raises(AlertExecutionHeld, match="anchor"):
        async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr):
            pytest.fail("A different verifier trust anchor cannot qualify")


async def test_actual_lock_assessments_expire_at_five_seconds_without_auto_renewal(authority_case):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        await _current(h, case, lease)
        h.clock[0] += timedelta(seconds=4, milliseconds=999)
        lease.require_active(now=h.clock[0])
        old = h.clock[0]
        h.clock[0] += timedelta(milliseconds=1)
        with pytest.raises(ValueError, match="stale"):
            lease.require_active(now=old)  # Caller backdating cannot hide the injected clock.


async def test_provider_known_lock_loss_blocks_the_synchronous_boundary(authority_case):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        await _current(h, case, lease)
        case.lock.handles[-1].deactivate()
        with pytest.raises(RuntimeError, match="active"):
            lease.require_active(now=h.clock[0])


async def test_private_identity_rebinding_is_a_synchronous_veto_not_a_cached_grant(authority_case):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        await _current(h, case, lease)
        h.identities.pop(next(iter(h.identities)))
        with pytest.raises(AlertExecutionHeld, match="mapping_changed|binding_changed"):
            lease.require_active(now=h.clock[0])


@pytest.mark.parametrize("wrong", ["generation", "anchor", "verifier"])
async def test_replaced_lock_generation_or_trust_cannot_supply_a_positive_boundary(
    authority_case, wrong
):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        held = case.lock.handles[0]
        assess = held.assess_ownership

        async def substituted():
            current = await assess()
            return LiveLockOwnershipAssessment.create(
                current.acquisition_receipt,
                current_fencing_generation=1
                if wrong == "generation"
                else current.current_fencing_generation,
                current_session_identity=current.current_session_identity,
                verifier_id="fixture-wrong-verifier"
                if wrong == "verifier"
                else current.verifier_id,
                verifier_version=current.verifier_version,
                trust_anchor_id="fixture:wrong-anchor"
                if wrong == "anchor"
                else current.trust_anchor_id,
                provider_attestation_digest=current.provider_attestation_digest,
                evaluated_at=current.evaluated_at,
                valid_until=current.valid_until,
            )

        held.assess_ownership = substituted
        with pytest.raises(AlertExecutionHeld):
            await _current(h, case, lease)
        with pytest.raises(AlertExecutionHeld, match="inactive"):
            lease.require_active(now=h.clock[0])


@pytest.mark.parametrize("changed", ["var", "dispatch", "exclusion", "source", "promotion"])
async def test_each_boundary_reloads_real_authority_and_exclusion_records(authority_case, changed):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        await _current(h, case, lease)
        key = {
            "var": h.var_key,
            "dispatch": case.dispatch_key,
            "exclusion": case.key,
            "source": SCOPE_KEY,
            "promotion": "action_promotion:" + h.plan.action_type,
        }[changed]
        raw = await h.store.read_state(key)
        if changed == "var":
            raw["state"] = "cancelled"
        elif changed == "promotion":
            raw["mode"] = "shadow"
        else:
            raw["payload"]["changed"] = True
        await h.store.write_state(key, raw)
        with pytest.raises(AlertExecutionHeld):
            await _current(h, case, lease)
        with pytest.raises(AlertExecutionHeld, match="inactive"):
            lease.require_active(now=h.clock[0])


async def test_freshly_admitted_new_generation_cannot_renew_a_held_exclusion(authority_case):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        await _current(h, case, lease)
        await _install_record(
            h,
            key=case.key,
            payload={**case.writer, "generation": 2},
            purpose=ALERT_WRITER_EXCLUSIVITY_PURPOSE,
        )
        with pytest.raises(AlertExecutionHeld):
            await _current(h, case, lease)


async def test_writer_shared_admission_is_resolved_again_at_each_boundary(authority_case):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        await _current(h, case, lease)
        admit = h.admissions.admit

        async def revoked_writer(**query):
            if query["purpose_id"] == ALERT_WRITER_EXCLUSIVITY_PURPOSE:
                return None
            return await admit(**query)

        h.admissions.admit = revoked_writer
        with pytest.raises(AlertExecutionHeld):
            await _current(h, case, lease)


async def test_exclusion_is_read_back_after_other_authoritative_io(authority_case):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        held = case.lock.handles[0]
        assess = held.assess_ownership

        async def replace_writer_during_lock_readback():
            current = await assess()
            raw = await h.store.read_state(case.key)
            raw["payload"]["generation"] += 1
            await h.store.write_state(case.key, raw)
            return current

        held.assess_ownership = replace_writer_during_lock_readback
        with pytest.raises(AlertExecutionHeld):
            await _current(h, case, lease)


async def test_separate_dispatch_admission_is_required_even_if_roles_and_writer_record_exist(
    authority_case,
):
    h = authority_case
    case = await _fence_case(h)
    # Corrupt only the independently retained dispatch admission, not the writer/authority data.
    key = decision_evidence_state_key(
        evidence_digest=content_digest(case.dispatch_binding),
        scope_digest=case.writer["binding"]["scope_digest"],
        purpose_id=ALERT_DISPATCH_PURPOSE,
        source_revision=SOURCE,
    )
    await h.store.write_state(key, {})
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        with pytest.raises(AlertExecutionHeld):
            await _current(h, case, lease)


async def test_recovery_uses_only_its_current_separate_proofs_not_expired_forward_source(
    authority_case,
):
    h = authority_case
    recovery = await _recovery_fixture(h, action_step="compensate_update_routing")
    case = await _fence_case(h, recovery=recovery)
    reads = []
    original = h.store.read_state

    async def record_reads(key):
        reads.append(key)
        return await original(key)

    h.store.read_state = record_reads
    async with case.fence.hold(action=case.action, plan=h.plan, pr=case.pr) as lease:
        await _current(h, case, lease)
        lease.require_active(now=h.clock[0])
    assert SCOPE_KEY not in reads
    assert case.dispatch_key in reads and recovery.var_key in reads


async def test_publisher_metadata_change_after_async_validation_invalidates_retained_binding(
    authority_case,
):
    h = authority_case
    case = await _fence_case(h)
    async with case.fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        await _current(h, case, lease)
        h.pr.metadata["source_digest"] = "sha256:" + "f" * 64
        with pytest.raises(AlertExecutionHeld, match="binding_changed"):
            lease.require_active(now=h.clock[0])


async def test_lock_trust_cannot_be_inferred_from_eligibility_boolean(authority_case):
    h = authority_case
    case = await _fence_case(h)
    fence = StateStoreAlertAuthorityFence(
        **{**case.options, "lock_trust": replace(LOCK_TRUST, verifier_id="other-verifier")}
    )
    async with fence.hold(action=h.action, plan=h.plan, pr=h.pr) as lease:
        with pytest.raises(AlertExecutionHeld):
            await _current(h, case, lease)
