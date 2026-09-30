from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.catalog_review_wiring import CatalogReviewBindings
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.mimir import CatalogReviewCapacityError, Mimir
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.core.case_history import OperationalEvidenceSourceKind, OperationalOutcomeClass
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogCheckReceipts,
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
    CatalogValidationRequest,
    OperatingPatternCompiler,
    PatternCase,
    PolicyCheckReceipt,
    ReplayCheckReceipt,
    SchemaCheckReceipt,
    ShadowCheckReceipt,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

# Fixture cases end by 2026-08-02 and a review rejects evidence older than 90 days, so reviews
# run at one fixed time instead of the wall clock, which passes that bound on 2026-10-30.
_REVIEWED_AT = datetime(2026, 8, 3, tzinfo=UTC)


def _review_clock() -> datetime:
    return _REVIEWED_AT


class _Publisher:
    def __init__(self, *, conflict: bool = False) -> None:
        self.packages: list[CatalogReviewPackage] = []
        self._conflict = conflict

    async def publish(
        self,
        package: CatalogReviewPackage,
    ) -> CatalogReviewPublicationReceipt:
        self.packages.append(package)
        return CatalogReviewPublicationReceipt(
            package_digest="9" * 64 if self._conflict else package.content_digest,
            review_ref="catalog-review:1",
            already_existed=False,
        )


class _FailingPublisher(_Publisher):
    def __init__(self, *, failures: int) -> None:
        super().__init__()
        self.failures = failures

    async def publish(
        self,
        package: CatalogReviewPackage,
    ) -> CatalogReviewPublicationReceipt:
        self.packages.append(package)
        if len(self.packages) <= self.failures:
            raise RuntimeError("publisher unavailable")
        return CatalogReviewPublicationReceipt(
            package_digest=package.content_digest,
            review_ref="catalog-review:recovered",
            already_existed=False,
        )


class _CaseHistory:
    def __init__(self, *, available: bool) -> None:
        self.available = available

    async def current_revision_available(self, **_values: object) -> bool:
        return self.available


@pytest.mark.parametrize("review_ref", ["", " review:1", "review:\n1"])
def test_publication_receipt_rejects_unsafe_review_ref(review_ref: str) -> None:
    with pytest.raises(ValueError, match="printable ASCII"):
        CatalogReviewPublicationReceipt(
            package_digest="a" * 64,
            review_ref=review_ref,
            already_existed=False,
        )


def test_publication_receipt_requires_boolean_idempotency_flag() -> None:
    with pytest.raises(ValueError, match="MUST be boolean"):
        CatalogReviewPublicationReceipt(
            package_digest="a" * 64,
            review_ref="review:1",
            already_existed=1,  # type: ignore[arg-type]
        )


class _Validator:
    def __init__(self, *, fail_schema: bool = False) -> None:
        self._fail_schema = fail_schema

    def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
        common = {
            "candidate_digest": request.candidate.digest,
            "artifact_digest": request.artifact_digest,
        }
        return CatalogCheckReceipts(
            schema=SchemaCheckReceipt(
                **common,
                schema_version=request.schema_version,
                passed=not self._fail_schema,
            ),
            replay=ReplayCheckReceipt(
                **common,
                replay_version="replay-v1",
                first_result_digest="1" * 64,
                second_result_digest="1" * 64,
                passed=True,
            ),
            shadow=ShadowCheckReceipt(
                **common,
                scenario_set_id="operational-learning-v1",
                baseline_result_digest="2" * 64,
                challenger_result_digest="3" * 64,
                regression_passed=True,
                policy_escapes=0,
                passed=True,
            ),
            policy=PolicyCheckReceipt(
                **common,
                policy_version="policy-v1",
                policy_escapes=0,
                passed=True,
            ),
        )


def _compiler(
    *,
    fail_schema: bool = False,
    catalog_version: str = "catalog-v1",
) -> CatalogCandidateCompiler:
    return CatalogCandidateCompiler(
        clock=_review_clock,
        validator=_Validator(fail_schema=fail_schema),
        catalog_version=catalog_version,
        schema_version="2.0.0",
    )


def _candidate(marker: int = 0) -> dict[str, object]:
    suffix = f"{marker:04d}"
    fingerprint = f"{marker + 15:064x}"
    cases = (
        PatternCase(
            case_id=f"case-success-{suffix}",
            revision=1,
            manifest_digest=f"{marker + 10:064x}",
            failure_fingerprint=fingerprint,
            resource_type="kubernetes.service",
            action_type="ops.scale-out",
            outcome_class=OperationalOutcomeClass.SUCCESS,
            reusable=True,
            negative=False,
            digest_evidence=(f"{marker + 20:064x}",),
            fdai_revision="a" * 40,
            scenario_set_version="v2026.08",
            event_time_cutoff=datetime(2026, 8, 1, tzinfo=UTC),
            source_kind=OperationalEvidenceSourceKind.LIVE,
            source_identity_digest=f"{marker + 21:064x}",
            source_synthetic=False,
            evidence_complete=True,
            conflict_digests=(),
        ),
        PatternCase(
            case_id=f"case-rollback-{suffix}",
            revision=1,
            manifest_digest=f"{marker + 30:064x}",
            failure_fingerprint=fingerprint,
            resource_type="kubernetes.service",
            action_type="ops.scale-out",
            outcome_class=OperationalOutcomeClass.ROLLBACK,
            reusable=False,
            negative=True,
            digest_evidence=(f"{marker + 40:064x}",),
            fdai_revision="a" * 40,
            scenario_set_version="v2026.08",
            event_time_cutoff=datetime(2026, 8, 2, tzinfo=UTC),
            source_kind=OperationalEvidenceSourceKind.LIVE,
            source_identity_digest=f"{marker + 41:064x}",
            source_synthetic=False,
            evidence_complete=True,
            conflict_digests=(),
        ),
    )
    candidate = OperatingPatternCompiler().compile(cases)
    assert candidate is not None
    return {
        "producer_principal": "Norns",
        "correlation_id": "correlation-1",
        "idempotency_key": f"candidate-{marker + 1}",
        "norns_consensus": {
            "decision": "propose",
            "unanimous": True,
            "perspective_count": 3,
            "reason_codes": [
                "historical_evidence_grounded",
                "current_contract_valid",
                "future_safety_preserved",
            ],
        },
        **candidate.to_rule_candidate_mapping(),
    }


def _bind_audit(mimir: Mimir) -> tuple[InMemoryBus, Saga]:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    saga = Saga()
    mimir.bind_bus(bus)
    saga.bind_bus(bus)
    bus.subscribe("object.rule", "Saga", saga.on_typed_message)
    return bus, saga


def _mimir(**kwargs: object) -> tuple[Mimir, InMemoryBus, Saga]:
    mimir = Mimir(**kwargs)  # type: ignore[arg-type]
    bus, saga = _bind_audit(mimir)
    return mimir, bus, saga


async def test_operational_candidate_compiles_to_inert_review_package() -> None:
    mimir, _, _ = _mimir(catalog_candidate_compiler=_compiler())

    await mimir.on_typed_message("object.rule-candidate", _candidate())

    packages = mimir.catalog_review_packages()
    assert len(packages) == 1
    assert packages[0].review_required is True
    assert packages[0].draft_rule.mapping["remediates"] == "ops.scale-out"
    assert len(mimir.pending_candidates()) == 1


async def test_duplicate_candidate_keeps_one_review_package() -> None:
    mimir, _, _ = _mimir(catalog_candidate_compiler=_compiler())
    candidate = _candidate()

    await mimir.on_typed_message("object.rule-candidate", candidate)
    await mimir.on_typed_message("object.rule-candidate", candidate)

    assert len(mimir.catalog_review_packages()) == 1


async def test_operational_candidate_publishes_a_digest_bound_review() -> None:
    publisher = _Publisher()
    mimir, bus, saga = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
    )

    await mimir.on_typed_message("object.rule-candidate", _candidate())

    receipt = mimir.catalog_review_publication_receipts()[0]
    assert receipt.package_digest == publisher.packages[0].content_digest
    assert receipt.review_ref == "catalog-review:1"
    assert len(publisher.packages) == 1
    assert mimir.catalog_review_packages() == ()
    assert mimir.pending_candidates() == ()
    assert bus.messages_on("object.audit-entry")[-1].principal == "Saga"
    assert saga.audit_chain.entries[-1].topic == "object.rule"


async def test_publication_receipt_digest_conflict_fails_closed() -> None:
    mimir, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_Publisher(conflict=True),
    )

    with pytest.raises(ValueError, match="receipt digest conflict"):
        await mimir.on_typed_message("object.rule-candidate", _candidate())

    assert mimir.catalog_review_publication_receipts() == ()


async def test_runtime_injects_catalog_review_bindings() -> None:
    publisher = _Publisher()
    store = InMemoryStateStore()
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        muninn_state_store=store,
        catalog_review=CatalogReviewBindings(
            compiler=_compiler(),
            publisher=publisher,
        ),
    )
    mimir = runtime.agents["Mimir"]
    assert isinstance(mimir, Mimir)

    await mimir.on_typed_message("object.rule-candidate", _candidate())

    assert len(mimir.catalog_review_publication_receipts()) == 1
    records = await store.read_states("pantheon/mimir/catalog-review/", limit=2)
    assert records[0]["status"] == "published"


def test_runtime_injects_operating_pattern_compiler() -> None:
    compiler = OperatingPatternCompiler()
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        operating_pattern_compiler=compiler,
    )

    norns = runtime.agents["Norns"]
    assert isinstance(norns, Norns)
    assert norns._operating_pattern_compiler is compiler


def test_operational_candidate_cannot_use_direct_runtime_promotion() -> None:
    mimir, _, _ = _mimir(catalog_candidate_compiler=_compiler())

    import asyncio

    asyncio.run(mimir.on_typed_message("object.rule-candidate", _candidate()))

    with pytest.raises(ValueError, match="reviewed catalog PR"):
        mimir.promote("ops.scale-out", source="handoff")
    draft_rule_id = str(mimir.catalog_review_packages()[0].draft_rule.mapping["id"])
    with pytest.raises(ValueError, match="reviewed catalog PR"):
        mimir.promote(draft_rule_id, source="handoff")
    assert mimir.status("ops.scale-out") is None
    assert mimir.status(draft_rule_id) is None


def test_operational_rule_namespace_never_allows_direct_promotion() -> None:
    mimir = Mimir()

    with pytest.raises(ValueError, match="reviewed catalog PR"):
        mimir.promote("learned.operational.evicted-candidate", source="manual")


async def test_failed_catalog_check_quarantines_candidate() -> None:
    mimir, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(fail_schema=True),
    )

    await mimir.on_typed_message("object.rule-candidate", _candidate())

    assert mimir.pending_candidates() == ()
    assert mimir.catalog_review_packages() == ()
    assert mimir.quarantined_candidates()[0]["quarantine_reason"] == (
        "catalog_compile:schema_check_failed"
    )


async def test_publisher_redrive_reuses_retained_package_without_flood_quarantine() -> None:
    publisher = _FailingPublisher(failures=3)
    mimir, bus, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
    )
    candidate = _candidate()

    for _ in range(3):
        with pytest.raises(RuntimeError, match="publisher unavailable"):
            await mimir.on_typed_message("object.rule-candidate", candidate)
    await mimir.on_typed_message("object.rule-candidate", candidate)

    assert len(mimir.pending_candidates()) == 0
    assert len(mimir.catalog_review_packages()) == 0
    assert len(mimir.catalog_review_publication_receipts()) == 1
    assert mimir.quarantined_candidates() == ()
    assert [message.payload["outcome"] for message in bus.messages_on("object.rule")] == [
        "publication_failed",
        "publication_failed",
        "publication_failed",
        "published",
    ]


async def test_failed_review_publication_recovers_from_durable_pending_state() -> None:
    store = InMemoryStateStore()
    failing = _FailingPublisher(failures=1)
    first, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=failing,
        catalog_review_state_store=store,
    )
    candidate = _candidate()

    with pytest.raises(RuntimeError, match="publisher unavailable"):
        await first.on_typed_message("object.rule-candidate", candidate)

    pending = await store.read_states("pantheon/mimir/catalog-review/", limit=2)
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert pending[0]["candidate"] == candidate

    publisher = _Publisher()
    recovered, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
        catalog_review_state_store=store,
    )

    assert await recovered.recover_catalog_reviews() == 1
    assert len(publisher.packages) == 1
    assert recovered.pending_candidates() == ()
    terminal = (await store.read_states("pantheon/mimir/catalog-review/", limit=2))[0]
    assert terminal["status"] == "published"
    assert "candidate" not in terminal


async def test_recovery_keeps_publisher_outage_pending_without_blocking_startup() -> None:
    store = InMemoryStateStore()
    first, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_FailingPublisher(failures=1),
        catalog_review_state_store=store,
    )
    candidate = _candidate()
    with pytest.raises(RuntimeError, match="publisher unavailable"):
        await first.on_typed_message("object.rule-candidate", candidate)

    recovered, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_FailingPublisher(failures=1),
        catalog_review_state_store=store,
    )

    assert await recovered.recover_catalog_reviews() == 1
    assert len(recovered.pending_candidates()) == 1
    record = (await store.read_states("pantheon/mimir/catalog-review/", limit=2))[0]
    assert record["status"] == "pending"
    assert recovered.behavior_snapshot()["operational_catalog_publication_retry_pending"] == 1


async def test_terminal_review_history_does_not_consume_pending_recovery_capacity() -> None:
    store = InMemoryStateStore()
    publisher = _Publisher()
    first, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
        catalog_review_state_store=store,
        max_review_packages=1,
        max_pending_candidates=1,
    )
    await first.on_typed_message("object.rule-candidate", _candidate(0))
    await first.on_typed_message("object.rule-candidate", _candidate(1))

    recovered, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_Publisher(),
        catalog_review_state_store=store,
        max_review_packages=1,
        max_pending_candidates=1,
    )

    assert await recovered.recover_catalog_reviews() == 0


async def test_shared_pending_overflow_defers_without_blocking_replica_startup() -> None:
    store = InMemoryStateStore()
    for marker in (0, 1):
        instance, _, _ = _mimir(
            catalog_candidate_compiler=_compiler(),
            catalog_review_publisher=_FailingPublisher(failures=1),
            catalog_review_state_store=store,
            max_review_packages=1,
            max_pending_candidates=1,
        )
        with pytest.raises(RuntimeError, match="publisher unavailable"):
            await instance.on_typed_message("object.rule-candidate", _candidate(marker))

    recovered, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_state_store=store,
        max_review_packages=1,
        max_pending_candidates=1,
    )

    assert await recovered.recover_catalog_reviews() == 1
    assert len(recovered.pending_candidates()) == 1
    assert recovered.behavior_snapshot()["operational_catalog_recovery_deferred"] == 1
    rows, total = await store.read_state_page(
        "pantheon/mimir/catalog-review/",
        limit=3,
        field="status",
        value="pending",
    )
    assert len(rows) == total == 2


async def test_published_review_redelivery_after_restart_is_a_durable_duplicate() -> None:
    store = InMemoryStateStore()
    candidate = _candidate()
    first, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_Publisher(),
        catalog_review_state_store=store,
    )
    await first.on_typed_message("object.rule-candidate", candidate)

    publisher = _Publisher()
    restarted, bus, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
        catalog_review_state_store=store,
    )
    await restarted.on_typed_message("object.rule-candidate", candidate)

    assert publisher.packages == []
    assert restarted.pending_candidates() == ()
    assert bus.messages_on("object.rule")[-1].payload["outcome"] == "duplicate"


async def test_published_redelivery_bypasses_unrelated_pending_capacity() -> None:
    store = InMemoryStateStore()
    published_candidate = _candidate(0)
    published, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_Publisher(),
        catalog_review_state_store=store,
        max_review_packages=1,
    )
    await published.on_typed_message("object.rule-candidate", published_candidate)

    pending, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_FailingPublisher(failures=1),
        catalog_review_state_store=store,
        max_review_packages=1,
    )
    with pytest.raises(RuntimeError, match="publisher unavailable"):
        await pending.on_typed_message("object.rule-candidate", _candidate(1))

    restarted, bus, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_state_store=store,
        max_review_packages=1,
    )
    assert await restarted.recover_catalog_reviews() == 1

    await restarted.on_typed_message("object.rule-candidate", published_candidate)

    assert len(restarted.pending_candidates()) == 1
    assert bus.messages_on("object.rule")[-1].payload["outcome"] == "duplicate"


async def test_catalog_change_invalidates_pending_review_without_blocking_startup() -> None:
    store = InMemoryStateStore()
    first, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(catalog_version="catalog-v1"),
        catalog_review_publisher=_FailingPublisher(failures=1),
        catalog_review_state_store=store,
    )
    with pytest.raises(RuntimeError, match="publisher unavailable"):
        await first.on_typed_message("object.rule-candidate", _candidate())

    publisher = _Publisher()
    recovered, bus, _ = _mimir(
        catalog_candidate_compiler=_compiler(catalog_version="catalog-v2"),
        catalog_review_publisher=publisher,
        catalog_review_state_store=store,
    )

    assert await recovered.recover_catalog_reviews() == 1
    assert publisher.packages == []
    terminal = (await store.read_states("pantheon/mimir/catalog-review/", limit=2))[0]
    assert terminal["status"] == "invalidated"
    assert terminal["reason"] == "compilation_identity_changed"
    assert "candidate" not in terminal
    assert bus.messages_on("object.rule")[-1].payload["outcome"] == "invalidated"


async def test_restart_invalidates_pending_review_after_source_deletion() -> None:
    store = InMemoryStateStore()
    first, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_FailingPublisher(failures=1),
        catalog_review_state_store=store,
    )
    first.bind_case_history(_CaseHistory(available=True))  # type: ignore[arg-type]
    candidate = {
        **_candidate(),
        "case_scope": {
            "access_scope_digest": "a" * 64,
            "purpose": "operational-learning",
        },
    }

    with pytest.raises(RuntimeError, match="publisher unavailable"):
        await first.on_typed_message("object.rule-candidate", candidate)

    publisher = _Publisher()
    recovered, bus, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
        catalog_review_state_store=store,
    )
    recovered.bind_case_history(_CaseHistory(available=False))  # type: ignore[arg-type]

    assert await recovered.recover_catalog_reviews() == 1
    assert publisher.packages == []
    assert recovered.pending_candidates() == ()
    terminal = (await store.read_states("pantheon/mimir/catalog-review/", limit=2))[0]
    assert terminal["status"] == "invalidated"
    assert terminal["reason"] == "source_no_longer_current"
    assert "candidate" not in terminal
    assert bus.messages_on("object.rule")[-1].payload["outcome"] == "invalidated"


async def test_source_deletion_scrubs_pending_review_before_recompile_failure() -> None:
    store = InMemoryStateStore()
    first, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=_FailingPublisher(failures=1),
        catalog_review_state_store=store,
    )
    first.bind_case_history(_CaseHistory(available=True))  # type: ignore[arg-type]
    candidate = {
        **_candidate(),
        "case_scope": {
            "access_scope_digest": "a" * 64,
            "purpose": "operational-learning",
        },
    }
    with pytest.raises(RuntimeError, match="publisher unavailable"):
        await first.on_typed_message("object.rule-candidate", candidate)

    recovered, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(fail_schema=True),
        catalog_review_state_store=store,
    )
    recovered.bind_case_history(_CaseHistory(available=False))  # type: ignore[arg-type]

    assert await recovered.recover_catalog_reviews() == 1
    terminal = (await store.read_states("pantheon/mimir/catalog-review/", limit=2))[0]
    assert terminal["status"] == "invalidated"
    assert terminal["reason"] == "source_no_longer_current"
    assert "candidate" not in terminal


async def test_fresh_invalid_candidate_is_compiled_before_source_admission() -> None:
    mimir, _, _ = _mimir(catalog_candidate_compiler=_compiler(fail_schema=True))
    mimir.bind_case_history(_CaseHistory(available=False))  # type: ignore[arg-type]
    candidate = {
        **_candidate(),
        "case_scope": {
            "access_scope_digest": "a" * 64,
            "purpose": "operational-learning",
        },
    }

    await mimir.on_typed_message("object.rule-candidate", candidate)

    assert mimir.quarantined_candidates()[0]["quarantine_reason"] == (
        "catalog_compile:schema_check_failed"
    )


async def test_review_capacity_fails_without_evicting_unresolved_package() -> None:
    mimir, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        max_pending_candidates=2,
        max_review_packages=1,
    )
    first = _candidate()
    second = _candidate(1)

    await mimir.on_typed_message("object.rule-candidate", first)
    with pytest.raises(CatalogReviewCapacityError, match="capacity exhausted"):
        await mimir.on_typed_message("object.rule-candidate", second)

    assert len(mimir.catalog_review_packages()) == 1
    assert len(mimir.pending_candidates()) == 1


async def test_semantic_package_aliases_recover_without_stale_mapping() -> None:
    publisher = _FailingPublisher(failures=1)
    store = InMemoryStateStore()
    mimir, bus, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
        catalog_review_state_store=store,
    )
    first = _candidate()
    alias = {**first, "idempotency_key": "candidate-alias"}

    with pytest.raises(RuntimeError, match="publisher unavailable"):
        await mimir.on_typed_message("object.rule-candidate", first)
    await mimir.on_typed_message("object.rule-candidate", alias)
    await mimir.on_typed_message("object.rule-candidate", first)

    assert mimir.pending_candidates() == ()
    assert mimir.catalog_review_packages() == ()
    assert [message.payload["outcome"] for message in bus.messages_on("object.rule")] == [
        "publication_failed",
        "published",
        "duplicate",
    ]
    rows = await store.read_states("pantheon/mimir/catalog-review/", limit=3)
    assert {row["status"] for row in rows} == {"published"}
    assert all("candidate" not in row for row in rows)


async def test_concurrent_redelivery_publishes_one_review() -> None:
    class _YieldingPublisher(_Publisher):
        async def publish(
            self,
            package: CatalogReviewPackage,
        ) -> CatalogReviewPublicationReceipt:
            await asyncio.sleep(0)
            return await super().publish(package)

    publisher = _YieldingPublisher()
    mimir, bus, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
    )
    candidate = _candidate()

    await asyncio.gather(
        mimir.on_typed_message("object.rule-candidate", candidate),
        mimir.on_typed_message("object.rule-candidate", candidate),
    )

    assert len(publisher.packages) == 1
    assert len(mimir.catalog_review_publication_receipts()) == 1
    assert [message.payload["outcome"] for message in bus.messages_on("object.rule")] == [
        "published",
        "duplicate",
    ]


async def test_published_review_reclaims_package_capacity() -> None:
    publisher = _Publisher()
    mimir, _, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
        max_pending_candidates=1,
        max_review_packages=1,
    )

    await mimir.on_typed_message("object.rule-candidate", _candidate(0))
    await mimir.on_typed_message("object.rule-candidate", _candidate(1))

    assert len(publisher.packages) == 2
    assert mimir.catalog_review_packages() == ()
    assert mimir.pending_candidates() == ()
    assert len(mimir.catalog_review_publication_receipts()) == 1
