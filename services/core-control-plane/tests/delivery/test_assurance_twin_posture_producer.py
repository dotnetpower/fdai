from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from fdai.core.assurance_twin import (
    AssuranceTwinEvaluationUnavailableError,
    CompletePostureEvaluation,
    build_baseline_projection,
)
from fdai.delivery.assurance_twin_evidence_source import StateStoreTwinEvidenceRepository
from fdai.delivery.assurance_twin_inventory import (
    AssuranceTwinInventoryChangedError,
    TwinInventoryRevision,
    TwinInventoryUnavailableError,
)
from fdai.delivery.assurance_twin_posture import AssuranceTwinPostureRecorder
from fdai.delivery.assurance_twin_posture_producer import AssuranceTwinPostureProducer
from fdai.delivery.assurance_twin_writers import AssuranceTwinAgentWriter
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.providers.projection import ResourceRef
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime.now(UTC) - timedelta(seconds=5)
_INVENTORY_REVISION = "sha256:" + "a" * 64
_RULE_SET_DIGEST = "sha256:" + "b" * 64
_COVERAGE_DIGEST = "sha256:" + "c" * 64
_GENERATION_DIGEST = "sha256:" + "e" * 64


class _Inventory:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        source_revision: str = _INVENTORY_REVISION,
        current_revision: str | None = None,
        revision_after_first_fence: str | None = None,
        revision_time: datetime = _NOW,
    ) -> None:
        self.error = error
        self.source_revision = source_revision
        self.current_revision = current_revision or source_revision
        self.revision_after_first_fence = revision_after_first_fence
        self.revision_time = revision_time
        self.calls: list[dict[str, Any]] = []
        self.fence_calls: list[str] = []

    def _revision(self) -> TwinInventoryRevision:
        return TwinInventoryRevision(
            projection=build_baseline_projection(
                ((ResourceRef("compute.vm", "vm-a"), {"public": False}),)
            ),
            snapshot_id="snapshot-1",
            source_revision=self.source_revision,
            completed_at=_NOW,
            revision_time=self.revision_time,
            source="azure-resource-graph",
            resource_count=1,
            delta_count=0,
        )

    async def load(self, **kwargs: Any) -> TwinInventoryRevision:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self._revision()

    async def load_at_revision(
        self,
        *,
        expected_revision: str,
        **_kwargs: Any,
    ) -> TwinInventoryRevision:
        self.fence_calls.append(expected_revision)
        if self.error is not None:
            raise self.error
        if expected_revision != self.current_revision:
            raise TwinInventoryUnavailableError("Twin Inventory revision changed")
        if len(self.fence_calls) == 1 and self.revision_after_first_fence is not None:
            self.current_revision = self.revision_after_first_fence
        return self._revision()

    async def run_at_revision(
        self,
        *,
        expected_revision: str,
        operation: Any,
        **kwargs: Any,
    ) -> Any:
        await self.load_at_revision(
            expected_revision=expected_revision,
            **kwargs,
        )
        result = await operation()
        try:
            await self.load_at_revision(
                expected_revision=expected_revision,
                **kwargs,
            )
        except TwinInventoryUnavailableError as exc:
            raise AssuranceTwinInventoryChangedError(
                "Twin Inventory changed across guarded write",
                result=result,
            ) from exc
        return result


class _Evaluator:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        coverage_digest: str = _COVERAGE_DIGEST,
        rule_set_digest: str = _RULE_SET_DIGEST,
        generation_digest: str = _GENERATION_DIGEST,
        generation_time: datetime = _NOW,
    ) -> None:
        self.error = error
        self.coverage_digest = coverage_digest
        self.rule_set_digest = rule_set_digest
        self.generation_digest = generation_digest
        self.generation_time = generation_time
        self.calls: list[dict[str, Any]] = []
        self.fence_calls: list[str] = []

    async def evaluate_assurance_twin_posture(self, **kwargs: Any) -> CompletePostureEvaluation:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return CompletePostureEvaluation(
            findings=(),
            evaluated_rule_ids=("rule.example",),
            rule_set_digest=self.rule_set_digest,
            rule_generation_digest=self.generation_digest,
            rule_generation_time=self.generation_time,
            coverage_refs=(
                str(kwargs["inventory_revision"]),
                self.rule_set_digest,
                self.coverage_digest,
            ),
        )

    async def run_assurance_twin_if_current(
        self,
        *,
        rule_generation_revision: str,
        operation: Any,
    ) -> Any:
        self.fence_calls.append(rule_generation_revision)
        if rule_generation_revision != self.generation_digest:
            return None
        return await operation()


async def test_producer_records_idempotent_complete_clear_evidence() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    inventory = _Inventory()
    evaluator = _Evaluator()
    producer = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )

    first = await producer.produce_once()
    second = await producer.produce_once()

    assert first is not None and second == first
    assert first.source_revision != _INVENTORY_REVISION
    retained = await repository.read_posture(first.source_key, first.source_revision)
    assert retained is not None and retained.record.verdict.value == "clear"
    assert retained.rule_assessment is not None
    assert retained.rule_assessment.rule_set_digest == _RULE_SET_DIGEST
    assert retained.rule_assessment.rule_generation_digest == _GENERATION_DIGEST
    assert retained.rule_assessment.coverage_refs == (
        _INVENTORY_REVISION,
        _RULE_SET_DIGEST,
        _COVERAGE_DIGEST,
    )
    assert inventory.calls[0]["required_scopes"] == ("scope-a",)
    assert evaluator.calls[0]["inventory_revision"] == _INVENTORY_REVISION
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=repository,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
        posture_generation_fence=evaluator,
    )
    assert await writer.process(first)
    assert evaluator.fence_calls == [
        _GENERATION_DIGEST,
        _GENERATION_DIGEST,
        _GENERATION_DIGEST,
    ]


async def test_expected_evidence_gap_abstains_without_a_row() -> None:
    for inventory_error, evaluation_error in (
        (TwinInventoryUnavailableError("stale"), None),
        (psycopg.OperationalError("database unavailable"), None),
        (None, AssuranceTwinEvaluationUnavailableError("abstained")),
    ):
        store = InMemoryStateStore()
        producer = AssuranceTwinPostureProducer(
            inventory=_Inventory(error=inventory_error),
            evaluator=_Evaluator(error=evaluation_error),
            repository=StateStoreTwinEvidenceRepository(store=store),
            scope="subscription:scope-a",
            required_scopes=("scope-a",),
            clock=lambda: _NOW,
        )

        assert await producer.produce_once() is None
        rows, total = await store.read_state_page("runtime:assurance-twin-evidence:", limit=10)
        assert rows == () and total == 0


async def test_delayed_older_inventory_is_rejected_before_recording() -> None:
    store = InMemoryStateStore()
    inventory = _Inventory(
        source_revision="sha256:" + "1" * 64,
        current_revision="sha256:" + "2" * 64,
    )
    producer = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=_Evaluator(),
        repository=StateStoreTwinEvidenceRepository(store=store),
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )

    assert await producer.produce_once() is None
    assert inventory.fence_calls == ["sha256:" + "1" * 64]
    rows, total = await store.read_state_page(
        "runtime:assurance-twin-evidence:",
        limit=10,
        field="request_status",
        value="pending",
    )
    assert rows == () and total == 0


async def test_inventory_change_across_source_write_is_terminalized() -> None:
    store = InMemoryStateStore()
    old_revision = "sha256:" + "1" * 64
    inventory = _Inventory(
        source_revision=old_revision,
        revision_after_first_fence="sha256:" + "2" * 64,
    )
    producer = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=_Evaluator(),
        repository=StateStoreTwinEvidenceRepository(store=store),
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )

    assert await producer.produce_once() is None
    rows, total = await store.read_state_page(
        "runtime:assurance-twin-evidence:",
        limit=10,
        field="request_status",
        value="superseded",
    )
    assert total == 1 and rows[0]["source_revision"] != old_revision


async def test_confirmed_source_drift_revokes_target_outbox() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    inventory = _Inventory()
    evaluator = _Evaluator()
    producer = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=repository,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
        posture_generation_fence=evaluator,
        posture_inventory_fence=producer,
    )
    request = await producer.produce_once()
    assert request is not None and await writer.process(request)

    inventory.fence_calls.clear()
    inventory.current_revision = _INVENTORY_REVISION
    inventory.revision_after_first_fence = "sha256:" + "2" * 64
    assert await producer.produce_once() is None

    source = await store.read_state(
        "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    )
    target = await store.read_state("runtime:assurance-twin-posture:subscription:scope-a")
    assert source is not None
    assert source["request_status"] == "conflict"
    assert source["writer_status"] == "conflict"
    assert target is not None
    assert target["source_confirmed"] is False
    assert target["publication_outbox"] is None
    assert target["conflict"]["reason_code"] == "assurance_twin_inventory_revision_changed"


async def test_changed_evaluation_receipt_gets_a_new_source_revision() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    first = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=_Evaluator(),
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    changed = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=_Evaluator(coverage_digest="sha256:" + "d" * 64),
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )

    first_request = await first.produce_once()
    changed_request = await changed.produce_once()

    assert first_request is not None and changed_request is not None
    assert first_request.source_revision != changed_request.source_revision
    first_retained = await repository.read_posture(
        first_request.source_key, first_request.source_revision
    )
    changed_retained = await repository.read_posture(
        changed_request.source_key, changed_request.source_revision
    )
    assert first_retained is not None and first_retained.conflict is False
    assert changed_retained is not None and changed_retained.conflict is False


class _WriteUnavailableRepository(StateStoreTwinEvidenceRepository):
    async def record_posture(self, **_kwargs: Any) -> Any:
        raise psycopg.OperationalError("state store unavailable")


class _FailOnceConfirmationRepository(StateStoreTwinEvidenceRepository):
    failed = False

    async def confirm_writer(self, request, *, evidence_digest):  # type: ignore[no-untyped-def]
        if not self.failed:
            self.failed = True
            return False
        return await super().confirm_writer(
            request,
            evidence_digest=evidence_digest,
        )


class _ClockContentionStore(InMemoryStateStore):
    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Any,
        *,
        expected_revision: int,
        audit_entry: Any,
    ) -> bool:
        if ":clock:" in key:
            return False
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )


async def test_transient_evidence_write_failure_remains_retryable() -> None:
    producer = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=_Evaluator(),
        repository=_WriteUnavailableRepository(store=InMemoryStateStore()),
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )

    assert await producer.produce_once() is None


async def test_clock_contention_remains_retryable() -> None:
    producer = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=_Evaluator(),
        repository=StateStoreTwinEvidenceRepository(store=_ClockContentionStore()),
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )

    assert await producer.produce_once() is not None


async def test_clock_release_contention_preserves_request_for_drift_terminalization() -> None:
    store = _ClockContentionStore()
    inventory = _Inventory(
        revision_after_first_fence="sha256:" + "2" * 64,
    )
    producer = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=_Evaluator(),
        repository=StateStoreTwinEvidenceRepository(store=store),
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )

    assert await producer.produce_once() is None
    rows, total = await store.read_state_page(
        "runtime:assurance-twin-evidence:",
        limit=10,
        field="request_status",
        value="superseded",
    )
    assert total == 1 and len(rows) == 1


async def test_transient_inventory_fence_failure_does_not_tombstone() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    inventory = _Inventory()
    evaluator = _Evaluator()
    producer = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    request = await producer.produce_once()
    assert request is not None
    inventory.error = psycopg.OperationalError("inventory unavailable")
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=repository,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
        posture_generation_fence=evaluator,
        posture_inventory_fence=producer,
    )

    assert not await writer.process(request)
    source = await store.read_state(
        "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    )
    assert source is not None
    assert source["request_status"] == "pending"
    assert source["conflict"] is False
    assert await store.read_state("runtime:assurance-twin-posture:subscription:scope-a") is None


async def test_transient_confirmation_failure_remains_retryable_with_inventory_fence() -> None:
    store = InMemoryStateStore()
    repository = _FailOnceConfirmationRepository(store=store)
    inventory = _Inventory()
    evaluator = _Evaluator()
    producer = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    request = await producer.produce_once()
    assert request is not None
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=repository,
        recorder=AssuranceTwinPostureRecorder(
            ledger=StateStoreAssuranceTwinPostureLedger(store=store)
        ),
        posture_generation_fence=evaluator,
        posture_inventory_fence=producer,
    )

    assert not await writer.process(request)
    provisional = await store.read_state("runtime:assurance-twin-posture:subscription:scope-a")
    assert provisional is not None
    assert provisional["source_confirmed"] is False
    assert provisional.get("conflict") is None
    assert await writer.process(request)


async def test_newer_overlay_revision_advances_posture_ordering() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    evaluator = _Evaluator()
    first_producer = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    newer_producer = AssuranceTwinPostureProducer(
        inventory=_Inventory(
            source_revision="sha256:" + "f" * 64,
            revision_time=_NOW,
        ),
        evaluator=evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    recorder = AssuranceTwinPostureRecorder(
        ledger=StateStoreAssuranceTwinPostureLedger(store=store)
    )
    writer = AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=repository,
        recorder=recorder,
        posture_generation_fence=evaluator,
    )

    first = await first_producer.produce_once()
    newer = await newer_producer.produce_once()
    assert first is not None and newer is not None
    assert await writer.process(first)
    assert await writer.process(newer)
    retained = await store.read_state("runtime:assurance-twin-posture:subscription:scope-a")
    assert retained is not None
    assert retained["evidence_source_revision"] == newer.source_revision
    assert retained.get("conflict") is None


async def test_same_evaluation_retry_keeps_first_generation_time() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    evaluator = _Evaluator()
    first = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    retry = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW + timedelta(seconds=1),
    )

    first_request = await first.produce_once()
    retry_request = await retry.produce_once()

    assert first_request is not None and retry_request == first_request
    retained = await repository.read_posture(
        first_request.source_key, first_request.source_revision
    )
    assert retained is not None
    assert retained.record.generated_at == _NOW.isoformat()


async def test_overlay_never_extends_baseline_freshness() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    inventory = _Inventory(revision_time=_NOW + timedelta(minutes=25))
    producer = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=_Evaluator(),
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW + timedelta(minutes=29),
    )
    request = await producer.produce_once()
    assert request is not None
    retained = await repository.read_posture(request.source_key, request.source_revision)
    assert retained is not None
    assert retained.fresh_until == _NOW + timedelta(minutes=30)

    expired = AssuranceTwinPostureProducer(
        inventory=inventory,
        evaluator=_Evaluator(),
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW + timedelta(minutes=31),
    )
    assert await expired.produce_once() is None


async def test_newer_rule_generation_advances_same_inventory_ordering() -> None:
    store = InMemoryStateStore()
    repository = StateStoreTwinEvidenceRepository(store=store)
    first_evaluator = _Evaluator()
    newer_evaluator = _Evaluator(
        rule_set_digest="sha256:" + "9" * 64,
        generation_digest="sha256:" + "8" * 64,
        generation_time=_NOW + timedelta(seconds=1),
    )
    first_producer = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=first_evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    newer_producer = AssuranceTwinPostureProducer(
        inventory=_Inventory(),
        evaluator=newer_evaluator,
        repository=repository,
        scope="subscription:scope-a",
        required_scopes=("scope-a",),
        clock=lambda: _NOW,
    )
    recorder = AssuranceTwinPostureRecorder(
        ledger=StateStoreAssuranceTwinPostureLedger(store=store)
    )

    first = await first_producer.produce_once()
    newer = await newer_producer.produce_once()
    assert first is not None and newer is not None
    assert await AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=repository,
        recorder=recorder,
        posture_generation_fence=first_evaluator,
    ).process(first)
    assert await AssuranceTwinAgentWriter(
        owner="Heimdall",
        source=repository,
        recorder=recorder,
        posture_generation_fence=newer_evaluator,
    ).process(newer)
    retained = await store.read_state("runtime:assurance-twin-posture:subscription:scope-a")
    assert retained is not None
    assert retained["evidence_source_revision"] == newer.source_revision
    assert retained.get("conflict") is None
