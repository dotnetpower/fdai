from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

import pytest
from fdai.core.case_history import CaseHistoryMaterializer, CaseSourceRecord
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.core.measurement.operational_promotion import (
    OperationalPromotionBatch,
    OperationalPromotionRecord,
    PromotionEvidenceCohort,
    operational_promotion_scope_digest,
)
from fdai.core.measurement.promotion_binding import ReviewedReplayBinding
from fdai.core.operational_learning.promotion_review import (
    ReviewedReplayAuthority,
    ReviewedReplayPersistedAuthorityVerifier,
    ReviewedReplayPromotionEvidence,
    ReviewedReplayReceiptVerifier,
)
from fdai.core.risk_gate import PromotionMetrics
from fdai.delivery.measurement.operational_promotion_batch import (
    GovernedLiveBatchProducer,
    _batch_mapping,
)
from fdai.delivery.measurement.operational_promotion_evidence import (
    ImmutableFileOperationalPromotionEvidenceSource,
    _decode_batch,
)
from fdai.delivery.persistence import (
    StateStoreActionPromotionRegistry,
    StateStoreOperationalPromotionReceiptStore,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.case_history.test_service import SCOPE, T0, _seal
from tests.core.measurement.test_operational_promotion import (
    _SEALED,
    _action,
    _evaluator,
    _passing_batch,
    _with_admission,
)


class _AdmissionChanges(TypedDict, total=False):
    receipt_digest: str
    verification_bundle_digest: str
    evidence_digest: str
    scope_digest: str
    purpose_id: str
    source_revision: str
    verified_at: datetime
    valid_until: datetime


class _BindingChanges(TypedDict, total=False):
    candidate_digest: str
    package_digest: str
    replay_first_digest: str
    replay_second_digest: str
    immutable_case_refs: tuple[str, ...]
    access_scope_digest: str
    purpose: str


class _ReviewChanges(TypedDict, total=False):
    action_type: str
    action_type_version: str
    action_type_digest: str
    fdai_revision: str
    scenario_set_version: str
    candidate_digest: str
    package_digest: str
    replay_first_digest: str
    replay_second_digest: str
    review_ref: str
    reviewer_principal: str
    approved: bool


class _ReceiptChanges(TypedDict, total=False):
    reviewed_replay_binding: ReviewedReplayBinding | None
    decision_evidence_receipt_digest: str | None
    decision_evidence_verification_bundle_digest: str | None
    action_type_version: str
    sample_count: int
    accuracy: float
    policy_escapes: int
    rollback_rate: float
    ready: bool
    gaps: tuple[str, ...]


class _Source:
    def __init__(self, batch: OperationalPromotionBatch) -> None:
        self.batch = batch
        self.calls = 0
        self.wait: asyncio.Event | None = None
        self.started = asyncio.Event()

    async def load_batch(self, **kwargs: str) -> OperationalPromotionBatch:
        self.calls += 1
        self.started.set()
        if self.wait is not None:
            await self.wait.wait()
        return self.batch


class _Admissions:
    def __init__(self, batch: OperationalPromotionBatch, review_digest: str) -> None:
        self.allowed = {"sha256:" + batch.content_digest, review_digest}
        self.calls: list[dict[str, str]] = []
        self.defect: str | None = None
        self.scope = operational_promotion_scope_digest(batch)
        self.now = _SEALED
        self.measurement_receipt_marker = "d"
        self.measurement_bundle_marker = "e"

    async def admit(self, **kwargs: str) -> DecisionEvidenceAdmission | None:
        self.calls.append(kwargs)
        if kwargs["evidence_digest"] not in self.allowed or self.defect == "missing":
            return None
        if self.defect == "exception":
            raise RuntimeError("provider-private-detail")
        changes: _AdmissionChanges = {}
        if self.defect == "scope_digest":
            changes["scope_digest"] = "sha256:" + "0" * 64
        if self.defect == "evidence_digest":
            changes["evidence_digest"] = "sha256:" + "0" * 64
        if self.defect == "purpose_id":
            changes["purpose_id"] = "other"
        if self.defect == "source_revision":
            changes["source_revision"] = "other"
        review = kwargs["purpose_id"] == "reviewed-replay-promotion"
        admission = DecisionEvidenceAdmission(
            receipt_digest="sha256:" + ("f" if review else self.measurement_receipt_marker) * 64,
            verification_bundle_digest=(
                "sha256:" + ("9" if review else self.measurement_bundle_marker) * 64
            ),
            evidence_digest=kwargs["evidence_digest"],
            scope_digest=self.scope,
            purpose_id=kwargs["purpose_id"],
            source_revision=kwargs["source_revision"],
            verified_at=self.now - timedelta(seconds=1),
            valid_until=self.now + timedelta(seconds=30),
        )
        if self.defect == "expired":
            changes["verified_at"] = self.now - timedelta(seconds=60)
            changes["valid_until"] = self.now - timedelta(seconds=1)
        if self.defect == "reused_receipt" and review:
            changes["receipt_digest"] = "sha256:" + "d" * 64
        if self.defect == "reused_bundle" and review:
            changes["verification_bundle_digest"] = "sha256:" + "e" * 64
        return replace(admission, **changes)


class _Setup:
    async def initialize(self) -> _Setup:
        self.clock = _SEALED
        self.metadata = InMemoryCaseHistoryMetadataStore()
        self.artifacts = InMemoryCaseHistoryArtifactStore()
        self.materializer = CaseHistoryMaterializer(
            metadata=self.metadata, artifacts=self.artifacts
        )
        self.case = await _seal(self.materializer)
        self.binding = ReviewedReplayBinding(
            candidate_digest="1" * 64,
            package_digest="2" * 64,
            replay_first_digest="3" * 64,
            replay_second_digest="3" * 64,
            immutable_case_refs=(
                f"case-history:{self.case.case_id}:{self.case.revision}:{self.case.manifest_digest}",
            ),
            access_scope_digest=SCOPE,
            purpose=self.case.purpose,
        )
        self.batch = _with_admission(
            replace(_passing_batch(), reviewed_replay_binding=self.binding)
        )
        self.review = ReviewedReplayPromotionEvidence(
            action_type=self.batch.action_type_name,
            action_type_version=self.batch.action_type_version,
            action_type_digest=self.batch.action_type_digest,
            fdai_revision=self.batch.fdai_revision,
            scenario_set_version=self.batch.scenario_set_version,
            candidate_digest=self.binding.candidate_digest,
            package_digest=self.binding.package_digest,
            replay_first_digest=self.binding.replay_first_digest,
            replay_second_digest=self.binding.replay_second_digest,
            promotion_evidence_digest=self.batch.content_digest,
            review_ref="retained-review:one",
            reviewer_principal="independent-reviewer",
            approved=True,
            reviewed_replay_binding=self.binding,
        )
        self.source = _Source(self.batch)
        self.admissions = _Admissions(self.batch, self.review.reviewed_replay_digest)
        self.authority = self.new_authority()
        self.receipt = _evaluator().evaluate(_action(), self.batch)
        self.args = {
            "action_type": self.review.action_type,
            "action_type_version": self.review.action_type_version,
            "action_type_digest": self.review.action_type_digest,
            "fdai_revision": self.review.fdai_revision,
            "scenario_set_version": self.review.scenario_set_version,
            "evidence_digest": self.review.promotion_evidence_digest,
        }
        return self

    def new_authority(self) -> ReviewedReplayAuthority:
        evaluator = _evaluator()
        evaluator._as_of_fn = lambda: self.clock
        return ReviewedReplayAuthority(
            (self.review,),
            production_evidence_source=self.source,
            production_admission_provider=self.admissions,
            case_materializer=self.materializer,
            case_metadata=self.metadata,
            production_action_types={_action().name: _action()},
            production_evaluator=evaluator,
            clock=lambda: self.clock,
        )


@pytest.fixture
async def bound() -> _Setup:
    return await _Setup().initialize()


async def test_independent_bound_review_promotes_and_restart_revalidates(bound: _Setup) -> None:
    assert bound.receipt.ready
    store = InMemoryStateStore()
    receipts = StateStoreOperationalPromotionReceiptStore(store)
    await receipts.save(bound.receipt)
    loaded = await receipts.load(
        action_type_name=bound.batch.action_type_name,
        fdai_revision=bound.batch.fdai_revision,
        scenario_set_version=bound.batch.scenario_set_version,
        evidence_digest=bound.batch.content_digest,
    )
    assert loaded == bound.receipt
    registry = StateStoreActionPromotionRegistry(
        store=store, receipt_verifier=ReviewedReplayReceiptVerifier(bound.authority)
    )
    await registry.refresh_for_update(_action().name)
    assert await bound.authority.prepare(**bound.args)
    record = registry.consider_promotion(
        action_type=_action(),
        metrics=PromotionMetrics(
            action_type=_action().name,
            shadow_days=bound.receipt.live_observation_days,
            samples=bound.receipt.sample_count,
            accuracy=bound.receipt.accuracy,
            policy_escapes=bound.receipt.policy_escapes,
        ),
        receipt=loaded,
    )
    assert record.mode is Mode.ENFORCE
    await registry.persist(_action().name)
    restarted = StateStoreActionPromotionRegistry(
        store=store,
        persisted_authority_verifier=ReviewedReplayPersistedAuthorityVerifier(
            bound.new_authority()
        ),
    )
    await restarted.refresh(_action().name)
    assert restarted.mode_of(_action().name) is Mode.ENFORCE
    assert bound.source.calls == 2
    bound.clock = bound.case.deletion_due_at
    bound.admissions.now = bound.clock
    assert bound.case.storage_ref is not None
    await bound.metadata.mark_deletion_started(
        bound.case.case_id,
        access_scope_digest=SCOPE,
        revision=bound.case.revision,
        storage_refs=(bound.case.storage_ref,),
        started_at=bound.clock,
    )
    await restarted.refresh(_action().name)
    assert restarted.mode_of(_action().name) is Mode.SHADOW


@pytest.mark.parametrize(
    "binding_changes,review_changes",
    [
        ({"candidate_digest": "4" * 64}, {"candidate_digest": "4" * 64}),
        ({"package_digest": "4" * 64}, {"package_digest": "4" * 64}),
        (
            {"replay_first_digest": "4" * 64, "replay_second_digest": "4" * 64},
            {"replay_first_digest": "4" * 64, "replay_second_digest": "4" * 64},
        ),
        ({"access_scope_digest": "4" * 64}, {}),
        ({"purpose": "other-purpose"}, {}),
        ({"immutable_case_refs": ("case-history:other:1:" + "4" * 64,)}, {}),
    ],
)
async def test_unrelated_artifacts_cannot_reuse_o7_digest(
    bound: _Setup, binding_changes: _BindingChanges, review_changes: _ReviewChanges
) -> None:
    altered = replace(bound.binding, **binding_changes)
    bound.review = replace(bound.review, reviewed_replay_binding=altered, **review_changes)
    authority = bound.new_authority()
    assert not await authority.prepare(**bound.args)
    assert not authority.accepts(**bound.args)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "exception",
        "scope_digest",
        "evidence_digest",
        "purpose_id",
        "source_revision",
        "expired",
        "reused_receipt",
        "reused_bundle",
    ],
)
async def test_independent_admissions_fail_closed(bound: _Setup, defect: str) -> None:
    bound.admissions.defect = defect
    assert not await bound.authority.prepare(**bound.args)
    assert not bound.authority.accepts(**bound.args)


async def test_plain_approval_and_missing_binding_are_unavailable(bound: _Setup) -> None:
    assert not bound.authority.accepts(**bound.args)
    assert not await ReviewedReplayAuthority((bound.review,)).prepare(**bound.args)
    bound.review = replace(bound.review, reviewed_replay_binding=None)
    assert not await bound.new_authority().prepare(**bound.args)


async def test_distinct_review_admission_is_required(bound: _Setup) -> None:
    bound.admissions.allowed.remove(bound.review.reviewed_replay_digest)
    assert not await bound.authority.prepare(**bound.args)
    assert len(bound.admissions.calls) == 2
    assert bound.admissions.calls[0]["purpose_id"] == "operational-promotion"
    assert bound.admissions.calls[1]["purpose_id"] == "reviewed-replay-promotion"


async def test_current_case_revision_is_rechecked_on_every_preparation(bound: _Setup) -> None:
    assert await bound.authority.prepare(**bound.args)
    await _seal(
        bound.materializer,
        sources=(
            CaseSourceRecord(
                record_type="postmortem",
                record_id="review-1",
                record_digest="c" * 64,
                occurred_at=T0 + timedelta(hours=3),
                payload={"finding": "new source revision"},
            ),
        ),
    )
    assert not await bound.authority.prepare(**bound.args)
    assert not bound.authority.accepts(**bound.args)


@pytest.mark.parametrize("changes", [{"access_scope_digest": "4" * 64}, {"purpose": "other"}])
async def test_source_scope_is_revalidated_even_when_review_is_independently_admitted(
    bound: _Setup, changes: _BindingChanges
) -> None:
    binding = replace(bound.binding, **changes)
    bound.batch = _with_admission(replace(bound.batch, reviewed_replay_binding=binding))
    bound.review = replace(
        bound.review,
        reviewed_replay_binding=binding,
        promotion_evidence_digest=bound.batch.content_digest,
    )
    bound.source.batch = bound.batch
    bound.admissions = _Admissions(bound.batch, bound.review.reviewed_replay_digest)
    args = {**bound.args, "evidence_digest": bound.batch.content_digest}
    assert not await bound.new_authority().prepare(**args)


async def test_unapproved_review_remains_shadow_despite_admission(bound: _Setup) -> None:
    bound.review = replace(bound.review, approved=False)
    bound.admissions.allowed.add(bound.review.reviewed_replay_digest)
    assert not await bound.new_authority().prepare(**bound.args)


async def test_independent_review_covers_attribution_and_action_identity(bound: _Setup) -> None:
    original = bound.review.reviewed_replay_digest
    changesets: tuple[_ReviewChanges, ...] = (
        {"action_type": "ops.other"},
        {"action_type_version": "99.0.0"},
        {"action_type_digest": "0" * 64},
        {"fdai_revision": "0" * 40},
        {"scenario_set_version": "other"},
        {"review_ref": "retained-review:other"},
        {"reviewer_principal": "another-reviewer"},
        {"approved": False},
    )
    for changes in changesets:
        assert replace(bound.review, **changes).reviewed_replay_digest != original


async def test_missing_source_artifact_is_not_current(bound: _Setup) -> None:
    assert bound.case.storage_ref is not None
    await bound.artifacts.delete(bound.case.storage_ref)
    assert not await bound.authority.prepare(**bound.args)


async def test_preparation_rechecks_expiry_after_source_io(
    bound: _Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = bound.materializer.current_revision_available

    async def delayed_current(
        *, case_ref: str, access_scope_digest: str, purpose: str, now: datetime
    ) -> bool:
        current = await original(
            case_ref=case_ref, access_scope_digest=access_scope_digest, purpose=purpose, now=now
        )
        bound.clock += timedelta(seconds=31)
        return current

    monkeypatch.setattr(bound.materializer, "current_revision_available", delayed_current)
    assert not await bound.authority.prepare(**bound.args)


async def test_preparation_timeout_is_bounded_and_does_not_retry(
    bound: _Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "fdai.core.operational_learning.promotion_revalidation._PREPARATION_SECONDS", 0.01
    )
    bound.source.wait = asyncio.Event()
    assert not await bound.authority.prepare(**bound.args)
    assert bound.source.calls == 1
    assert not bound.authority.accepts(**bound.args)


async def test_bound_batch_producer_manifest_source_round_trip(
    bound: _Setup, tmp_path: Path
) -> None:
    class LiveSource:
        async def load_records(self, **kwargs: str) -> tuple[OperationalPromotionRecord, ...]:
            return tuple(
                record
                for record in bound.batch.records
                if record.cohort is PromotionEvidenceCohort.LIVE_SHADOW
            )

    producer = GovernedLiveBatchProducer(
        source=LiveSource(),
        output_dir=tmp_path,
        benchmark_records=tuple(
            record
            for record in bound.batch.records
            if record.cohort is PromotionEvidenceCohort.FROZEN_BENCHMARK
        ),
        clock=lambda: bound.clock,
    )
    artifact = await producer.produce(
        action_type_name=bound.batch.action_type_name,
        action_type_version=bound.batch.action_type_version,
        action_type_digest=bound.batch.action_type_digest,
        fdai_revision=bound.batch.fdai_revision,
        scenario_set_version=bound.batch.scenario_set_version,
        reviewed_replay_binding=bound.binding,
    )
    loaded = await ImmutableFileOperationalPromotionEvidenceSource(artifact.manifest).load_batch(
        action_type_name=bound.batch.action_type_name,
        fdai_revision=bound.batch.fdai_revision,
        scenario_set_version=bound.batch.scenario_set_version,
    )
    assert loaded.reviewed_replay_binding == bound.binding
    assert loaded.content_digest == bound.batch.content_digest


async def test_legacy_enforce_record_remains_readable_and_can_be_demoted(bound: _Setup) -> None:
    store = InMemoryStateStore()
    key = "action_promotion:" + bound.review.action_type
    legacy = {
        "schema_version": "1.0.0",
        "revision": 7,
        "action_type": bound.review.action_type,
        "mode": "enforce",
        "promoted_at": bound.clock.isoformat(),
        "metrics": None,
    }
    await store.write_state(key, legacy)
    registry = StateStoreActionPromotionRegistry(
        store=store,
        persisted_authority_verifier=ReviewedReplayPersistedAuthorityVerifier(bound.authority),
    )
    await registry.refresh(bound.review.action_type)
    assert registry.mode_of(bound.review.action_type) is Mode.SHADOW
    await registry.refresh_for_demotion(bound.review.action_type)
    assert registry.mode_of(bound.review.action_type) is Mode.SHADOW
    registry.demote(bound.review.action_type)
    await registry.persist(bound.review.action_type)
    persisted = await store.read_state(key)
    assert persisted is not None
    assert persisted["mode"] == "shadow"
    assert persisted["revision"] == 8
    assert tuple(store.audit_entries)[-1]["entry"]["action_kind"] == "action_promotion.persisted"
    assert bound.source.calls == 0


async def test_demotion_refresh_clears_cached_enforce_on_store_failure(bound: _Setup) -> None:
    class FailingStore(InMemoryStateStore):
        fail_reads = False

        async def read_state(self, key: str) -> Mapping[str, Any] | None:
            if self.fail_reads:
                raise RuntimeError("store unavailable")
            return await super().read_state(key)

    store = FailingStore()
    registry = StateStoreActionPromotionRegistry(
        store=store, receipt_verifier=ReviewedReplayReceiptVerifier(bound.authority)
    )
    await registry.refresh_for_update(_action().name)
    assert await bound.authority.prepare(**bound.args)
    registry.consider_promotion(
        action_type=_action(),
        metrics=PromotionMetrics(
            action_type=_action().name,
            shadow_days=bound.receipt.live_observation_days,
            samples=bound.receipt.sample_count,
            accuracy=bound.receipt.accuracy,
            policy_escapes=bound.receipt.policy_escapes,
        ),
        receipt=bound.receipt,
    )
    assert registry.mode_of(_action().name) is Mode.ENFORCE
    store.fail_reads = True
    with pytest.raises(RuntimeError, match="store unavailable"):
        await registry.refresh_for_demotion(_action().name)
    assert registry.mode_of(_action().name) is Mode.SHADOW
    with pytest.raises(RuntimeError, match="requires a writer refresh"):
        await registry.persist(_action().name)


async def test_prepared_proof_is_single_use_and_expires(bound: _Setup) -> None:
    assert await bound.authority.prepare(**bound.args)
    assert bound.authority.accepts(**bound.args)
    assert not bound.authority.accepts(**bound.args)
    assert await bound.authority.prepare(**bound.args)
    bound.clock += timedelta(seconds=5)
    assert not bound.authority.accepts(**bound.args)


async def test_failed_new_preparation_revokes_previous_proof(bound: _Setup) -> None:
    assert await bound.authority.prepare(**bound.args)
    bound.admissions.defect = "missing"
    assert not await bound.authority.prepare(**bound.args)
    assert not bound.authority.accepts(**bound.args)


async def test_preparation_exceptions_are_redacted(
    bound: _Setup, caplog: pytest.LogCaptureFixture
) -> None:
    bound.admissions.defect = "exception"
    assert not await bound.authority.prepare(**bound.args)
    assert "RuntimeError" in caplog.text
    assert "provider-private-detail" not in caplog.text


async def test_cancelled_preparation_revokes_previous_proof(bound: _Setup) -> None:
    assert await bound.authority.prepare(**bound.args)
    bound.source.wait = asyncio.Event()
    bound.source.started.clear()
    pending = asyncio.create_task(bound.authority.prepare(**bound.args))
    await bound.source.started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not bound.authority.accepts(**bound.args)


async def test_concurrent_newer_rejection_cannot_be_overwritten(bound: _Setup) -> None:
    bound.source.wait = asyncio.Event()
    old_wait = bound.source.wait
    pending = asyncio.create_task(bound.authority.prepare(**bound.args))
    await bound.source.started.wait()
    bound.source.wait = None
    bound.admissions.defect = "missing"
    assert not await bound.authority.prepare(**bound.args)
    bound.admissions.defect = None
    old_wait.set()
    assert not await pending
    assert not bound.authority.accepts(**bound.args)


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewed_replay_binding": None},
        {"decision_evidence_receipt_digest": None},
        {"decision_evidence_verification_bundle_digest": None},
        {"action_type_version": "99.0.0"},
    ],
)
async def test_sync_receipt_verifier_rejects_missing_or_substituted_proof(
    bound: _Setup, changes: _ReceiptChanges
) -> None:
    assert await bound.authority.prepare(**bound.args)
    assert not ReviewedReplayReceiptVerifier(bound.authority).verify(
        action_type=_action(), receipt=replace(bound.receipt, **changes)
    )


def test_bound_batch_codec_preserves_legacy_digest_and_rejects_downgrade() -> None:
    legacy = _passing_batch()
    wire = _batch_mapping(legacy)
    assert wire["schema_version"] == "1.0.0"
    assert _decode_batch(wire).content_digest == legacy.content_digest
    binding = ReviewedReplayBinding(
        candidate_digest="1" * 64,
        package_digest="2" * 64,
        replay_first_digest="3" * 64,
        replay_second_digest="3" * 64,
        immutable_case_refs=("case-history:one:1:" + "4" * 64,),
        access_scope_digest="5" * 64,
        purpose="operational-learning",
    )
    batch = replace(legacy, reviewed_replay_binding=binding)
    encoded = _batch_mapping(batch)
    assert encoded["schema_version"] == "1.1.0"
    assert _decode_batch(encoded).content_digest == batch.content_digest
    assert batch.content_digest != legacy.content_digest
    assert operational_promotion_scope_digest(batch) != operational_promotion_scope_digest(legacy)
    encoded["schema_version"] = "1.0.0"
    with pytest.raises(ValueError, match="fields"):
        _decode_batch(encoded)


@pytest.mark.parametrize(
    "field,value",
    [
        ("immutable_case_refs", []),
        ("immutable_case_refs", ["case-history:one:01:" + "4" * 64]),
        ("immutable_case_refs", ["case-history:one:1:" + "4" * 64] * 2),
        ("candidate_digest", "not-a-digest"),
        ("replay_second_digest", "4" * 64),
        ("purpose", ""),
    ],
)
def test_binding_schema_rejects_incomplete_or_ambiguous_sources(field: str, value: object) -> None:
    raw: dict[str, object] = {
        "candidate_digest": "1" * 64,
        "package_digest": "2" * 64,
        "replay_first_digest": "3" * 64,
        "replay_second_digest": "3" * 64,
        "immutable_case_refs": ["case-history:one:1:" + "4" * 64],
        "access_scope_digest": "5" * 64,
        "purpose": "operational-learning",
    }
    raw[field] = value
    with pytest.raises(ValueError):
        ReviewedReplayBinding.from_mapping(raw)


def test_binding_canonicalizes_order_without_retaining_mutable_input() -> None:
    refs = ["case-history:two:2:" + "4" * 64, "case-history:one:1:" + "5" * 64]
    raw = {
        "candidate_digest": "1" * 64,
        "package_digest": "2" * 64,
        "replay_first_digest": "3" * 64,
        "replay_second_digest": "3" * 64,
        "immutable_case_refs": refs,
        "access_scope_digest": "5" * 64,
        "purpose": "operational-learning",
    }
    binding = ReviewedReplayBinding.from_mapping(raw)
    refs.clear()
    assert len(binding.immutable_case_refs) == 2
    assert binding.immutable_case_refs == tuple(sorted(binding.immutable_case_refs))


async def test_every_bound_subject_field_changes_measurement_and_scope_digests(
    bound: _Setup,
) -> None:
    for changes in (
        {"candidate_digest": "0" * 64},
        {"package_digest": "0" * 64},
        {"replay_first_digest": "0" * 64, "replay_second_digest": "0" * 64},
        {"access_scope_digest": "0" * 64},
        {"purpose": "other-purpose"},
        {"immutable_case_refs": ("case-history:other:9:" + "0" * 64,)},
    ):
        changed = replace(
            bound.batch,
            reviewed_replay_binding=replace(bound.binding, **changes),
        )
        assert changed.content_digest != bound.batch.content_digest
        assert operational_promotion_scope_digest(changed) != operational_promotion_scope_digest(
            bound.batch
        )


async def test_passing_metrics_cannot_authorize_a_failing_admitted_batch_or_restart(
    bound: _Setup,
) -> None:
    failing = replace(
        bound.batch, records=tuple(replace(record, correct=False) for record in bound.batch.records)
    )
    bound.batch = _with_admission(failing)
    bound.review = replace(bound.review, promotion_evidence_digest=failing.content_digest)
    bound.source.batch = bound.batch
    bound.admissions = _Admissions(bound.batch, bound.review.reviewed_replay_digest)
    bound.args["evidence_digest"] = failing.content_digest
    assert not _evaluator().evaluate(_action(), bound.batch).ready
    authority = bound.new_authority()
    forged = replace(bound.receipt, evidence_digest=failing.content_digest)
    assert forged.ready and forged.accuracy == 1.0
    assert not await authority.prepare(**bound.args)
    assert not ReviewedReplayReceiptVerifier(authority).verify(
        action_type=_action(), receipt=forged
    )
    assert not await ReviewedReplayPersistedAuthorityVerifier(authority).verify(**bound.args)


@pytest.mark.parametrize(
    "changes",
    [
        {"sample_count": 9999},
        {"accuracy": 0.9999},
        {"policy_escapes": 1},
        {"rollback_rate": 0.5},
        {"ready": False},
        {"gaps": ("forged_evaluation",)},
    ],
)
async def test_complete_evaluated_receipt_is_authenticated(
    bound: _Setup, changes: _ReceiptChanges
) -> None:
    assert await bound.authority.prepare(**bound.args)
    assert not ReviewedReplayReceiptVerifier(bound.authority).verify(
        action_type=_action(), receipt=replace(bound.receipt, **changes)
    )


async def test_case_expiring_during_currency_io_cannot_prepare(
    bound: _Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    bound.clock = bound.case.deletion_due_at - timedelta(seconds=1)
    bound.admissions.now = bound.clock
    original = bound.materializer.current_revision_available

    async def crossing_deadline(
        *, case_ref: str, access_scope_digest: str, purpose: str, now: datetime
    ) -> bool:
        assert await original(
            case_ref=case_ref, access_scope_digest=access_scope_digest, purpose=purpose, now=now
        )
        bound.clock += timedelta(seconds=2)
        return True

    monkeypatch.setattr(bound.materializer, "current_revision_available", crossing_deadline)
    assert not await bound.authority.prepare(**bound.args)
    assert not bound.authority.accepts(**bound.args)


async def test_prepared_proof_cannot_outlive_case_retention_deadline(bound: _Setup) -> None:
    bound.clock = bound.case.deletion_due_at - timedelta(seconds=1)
    bound.admissions.now = bound.clock
    assert await bound.authority.prepare(**bound.args)
    bound.clock = bound.case.deletion_due_at
    assert not bound.authority.accepts(**bound.args)


async def test_renewed_admissions_authenticate_the_original_immutable_receipt(
    bound: _Setup,
) -> None:
    bound.admissions.measurement_receipt_marker = "a"
    bound.admissions.measurement_bundle_marker = "b"
    assert await bound.authority.prepare(**bound.args)
    assert ReviewedReplayReceiptVerifier(bound.authority).verify(
        action_type=_action(), receipt=bound.receipt
    )


async def test_current_case_metadata_must_be_the_materializers_actual_store(bound: _Setup) -> None:
    with pytest.raises(ValueError, match="authoritative metadata"):
        ReviewedReplayAuthority(
            (bound.review,),
            case_materializer=bound.materializer,
            case_metadata=InMemoryCaseHistoryMetadataStore(),
        )
