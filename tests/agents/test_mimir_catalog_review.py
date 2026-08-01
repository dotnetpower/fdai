from __future__ import annotations

import asyncio

import pytest

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.catalog_review_wiring import CatalogReviewBindings
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.mimir import CatalogReviewCapacityError, Mimir
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.core.case_history import OperationalOutcomeClass
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


def _compiler(*, fail_schema: bool = False) -> CatalogCandidateCompiler:
    return CatalogCandidateCompiler(
        validator=_Validator(fail_schema=fail_schema),
        catalog_version="catalog-v1",
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
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        catalog_review=CatalogReviewBindings(
            compiler=_compiler(),
            publisher=publisher,
        ),
    )
    mimir = runtime.agents["Mimir"]
    assert isinstance(mimir, Mimir)

    await mimir.on_typed_message("object.rule-candidate", _candidate())

    assert len(mimir.catalog_review_publication_receipts()) == 1


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
    mimir, bus, _ = _mimir(
        catalog_candidate_compiler=_compiler(),
        catalog_review_publisher=publisher,
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
