"""Actual isolated PostgreSQL owner/writer concurrency, never live qualification."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fdai.core.case_history import CaseHistoryMaterializer, CaseHistoryRetentionService
from fdai.core.case_history.derived import CaseHistoryDerivedRetention
from fdai.core.control_loop._audit_helpers import write_t1_audit
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    current_reuse_evidence_digest,
    current_reuse_scope_digest,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import (
    BoundRetainedPatternAction,
    BoundRetainedPatternRequest,
    RetainedPatternQualification,
    qualification_request,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_lease import RetainedPatternLeaseEvidence
from fdai.core.tiers.t1_lightweight.retained_patterns import (
    RetainedPatternComparison,
    RetainedPatternSource,
)
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.core.tiers.t1_lightweight.tier import SimilarityMatch, T1Config
from fdai.core.trust_router import RoutingDecision, RoutingTier
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.local_pattern_backend import LocalPostgresPatternBackend
from fdai.delivery.persistence.local_pattern_owner import (
    LOCAL_VENUE,
    LocalPatternArtifactStore,
    LocalPatternOwner,
    local_dsn,
    owner_key,
)
from fdai.delivery.persistence.local_pattern_qualification import LocalPostgresPatternQualifier
from fdai.delivery.persistence.local_pattern_validation import lookups
from fdai.delivery.persistence.state_store_case_history import StateStoreCaseHistoryMetadataStore
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
    decision_evidence_state_key,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from psycopg.conninfo import make_conninfo

from tests.core.tiers.t1_lightweight.test_contextual_reuse import _event, _Verifier
from tests.core.tiers.t1_lightweight.test_eligibility_comparison import _Library
from tests.core.tiers.t1_lightweight.test_retained_pattern_audit import (
    _retain_protocol_fixture_admission,
)
from tests.core.tiers.t1_lightweight.test_retained_patterns import NOW, _retained
from tests.persistence.test_postgres_state_store import saga_database  # noqa: F401


@pytest.fixture
async def local_case(saga_database: str) -> AsyncIterator[tuple[Any, ...]]:  # noqa: F811
    h = await _retained()
    store = PostgresStateStore(
        config=PostgresStateStoreConfig(dsn=local_dsn(saga_database, venue=LOCAL_VENUE))
    )
    admission = StateStoreDecisionEvidenceAdmissionProvider(store=store, clock=lambda: NOW)
    owner = LocalPatternOwner(store=store, admission=admission, venue=LOCAL_VENUE)
    metadata = StateStoreCaseHistoryMetadataStore(store=store)
    artifacts = LocalPatternArtifactStore(store=store, venue=LOCAL_VENUE)
    context, stats, event = h.action.operational_case, h.statistics, _event()
    assert context is not None and stats is not None
    records = []
    for case in h.cases:
        record = await h.metadata.latest(case.case_id, access_scope_digest="f" * 64)
        assert record is not None and record.storage_ref is not None
        content = await h.artifacts.get(record.storage_ref)
        assert content is not None
        await artifacts.put(record.storage_ref, content, digest=record.manifest_digest)
        await metadata.append_revision(record)
        records.append(record)
    projected_key = "case-history-derived:v1:" + "f" * 64
    projection = await h.durable.read_state(projected_key)
    assert projection is not None
    await store.write_state(projected_key, projection)
    h.materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    observed = await _Verifier(decision_evidence=None).verify(  # type: ignore[no-untyped-call]
        event=event, action=h.action, context=context
    )
    await owner.retain_principal(
        context=h.request.context,
        scope="f" * 64,
        purpose=h.request.purpose,
        allowed=True,
        valid_until=NOW + timedelta(minutes=3),
    )
    await owner.retain_statistics(stats, authorized=True)
    await owner.retain_reuse(event=event, action=h.action, context=context, verification=observed)
    await owner.register_action(h.registry[h.action.action_type])
    # The normal readiness gate, proof bundle, recorder and PG admission provider
    # are used. These protocol observations are synthetic and not a live claim.
    temp = InMemoryStateStore()
    preliminary = qualification_request(
        event=event,
        arguments=h.request.arguments(),
        principal=h.request.context.model_dump(mode="json"),
        read_source_revision="a" * 40,
        cohort=next(iter(projection["entries"].values()))["value"],
        match=SimilarityMatch(h.action, 0.98),
        statistics=stats,
        verification=observed,
    )
    read_lookup, reuse_lookup = lookups(preliminary.descriptor)
    assert reuse_lookup["evidence_digest"] == current_reuse_evidence_digest(observed)
    assert reuse_lookup["scope_digest"] == current_reuse_scope_digest(
        event=event, action=h.action, context=context
    )
    for lookup in (read_lookup, reuse_lookup):
        await _retain_protocol_fixture_admission(temp, **lookup)
        key = decision_evidence_state_key(**lookup)
        value = await temp.read_state(key)
        assert value is not None
        await store.write_state(key, value)
    current = await owner.verify(event=event, action=h.action, context=context)
    assert current.decision_evidence is not None
    bound = BoundRetainedPatternAction(
        str(event.event_id),
        h.action.signature,
        SimilarityMatch(h.action, 0.98),
        stats.evidence_ref,
        owner.statistics,
    )
    query = OperatingPatternQuery(
        store=store,
        materializer=lambda: h.materializer,
        admission=admission,
        source_revision="a" * 40,
        clock=lambda: NOW,
    )
    qualifier = LocalPostgresPatternQualifier(
        dsn=saga_database, venue=LOCAL_VENUE, clock=lambda: NOW
    )
    source = RetainedPatternSource(
        query=query,
        request_source=BoundRetainedPatternRequest(str(event.event_id), h.request),
        action_resolver=bound.resolve,
        action_types=lambda: h.registry,
        store=store,
        materializer=lambda: h.materializer,
        statistics_source=bound.read_statistics,
        leased_qualifier=qualifier,
        clock=lambda: NOW,
    )
    h.source = source
    try:
        yield (
            saga_database,
            store,
            owner,
            h,
            source,
            qualifier,
            records,
            read_lookup,
            reuse_lookup,
            observed,
        )
    finally:
        await store.aclose()


@pytest.mark.parametrize(
    "kind",
    [
        "negative_artifact",
        "negative_metadata",
        "projection",
        "measurement",
        "principal",
        "reuse_policy",
        "read_admission",
        "reuse_admission",
        "action",
    ],
)
async def test_real_owner_writers_block_until_positive_acceptance(
    local_case: tuple[Any, ...], kind: str
) -> None:
    dsn, store, owner, h, source, qualifier, records, read_lookup, reuse_lookup, observed = (
        local_case
    )
    writer_name = "local-pattern-writer-" + uuid4().hex
    other = PostgresStateStore(
        config=PostgresStateStoreConfig(
            dsn=make_conninfo(local_dsn(dsn, venue=LOCAL_VENUE), application_name=writer_name)
        )
    )
    other_owner = LocalPatternOwner(
        store=other,
        admission=StateStoreDecisionEvidenceAdmissionProvider(store=other),
        venue=LOCAL_VENUE,
    )
    accepted = asyncio.Event()
    writer: asyncio.Task[None] | None = None
    original = source._accept_leased

    def accept(*args: Any, **kwargs: Any) -> RetainedPatternComparison:
        assert writer is not None and not writer.done()
        accepted.set()
        result: RetainedPatternComparison = original(*args, **kwargs)
        return result

    source._accept_leased = accept

    async def mutate() -> None:
        context = h.action.operational_case
        assert context is not None and h.statistics is not None
        if kind == "negative_artifact":
            await LocalPatternArtifactStore(store=other, venue=LOCAL_VENUE).delete(
                records[-1].storage_ref
            )
        elif kind == "negative_metadata":
            await other.delete_state("case-history:latest:" + records[-1].case_id)
        elif kind == "projection":
            await other.delete_state("case-history-derived:v1:" + "f" * 64)
        elif kind == "measurement":
            await other_owner.retain_statistics(h.statistics, authorized=False)
        elif kind == "principal":
            await other_owner.retain_principal(
                context=h.request.context,
                scope="f" * 64,
                purpose=h.request.purpose,
                allowed=False,
                valid_until=NOW + timedelta(minutes=3),
            )
        elif kind == "reuse_policy":
            await other_owner.retain_reuse(
                event=_event(),
                action=h.action,
                context=context,
                verification=replace(observed, policy_allowed=False),
            )
        elif kind == "action":
            await other.delete_state(owner_key("action", h.action.action_type))
        else:
            await other.delete_state(
                decision_evidence_state_key(
                    **(read_lookup if kind == "read_admission" else reuse_lookup)
                )
            )

    class ObservedLease:
        @asynccontextmanager
        async def lease(
            self, request: RetainedPatternQualification
        ) -> AsyncIterator[RetainedPatternLeaseEvidence | None]:
            nonlocal writer
            async with qualifier.lease(request) as evidence:
                assert evidence is not None
                writer = asyncio.create_task(mutate())
                async with await psycopg.AsyncConnection.connect(dsn) as check:
                    for _ in range(100):
                        row = await (
                            await check.execute(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE application_name = %s AND wait_event_type = 'Lock'",
                                (writer_name,),
                            )
                        ).fetchone()
                        if row and row[0]:
                            break
                        assert not writer.done()
                        await asyncio.sleep(0.01)
                    else:
                        pytest.fail("the real owner writer did not wait on the read lease")
                yield evidence
                assert accepted.is_set()

    source._leased_qualifier = ObservedLease()
    try:
        result = await h.tier(verifier=owner).evaluate(event=_event())
        assert accepted.is_set()
        comparison = result.retained_pattern_comparison
        assert comparison is not None and comparison.challenger_match is not None
        assert comparison.final_qualification is None  # No self-signed final permission.
        assert comparison.final_lease is not None
        assert comparison.final_lease.guard.active is False
        assert result.reason == "no_neighbour_found" and result.best_match is None
        assert writer is not None
        await asyncio.wait_for(writer, timeout=2)
        source._leased_qualifier = qualifier
        after = await h.tier(verifier=owner).evaluate(event=_event())
        assert after.retained_pattern_comparison is not None
        assert after.retained_pattern_comparison.challenger_match is None
        await write_t1_audit(
            store,
            event=_event(),
            decision=RoutingDecision(tier=RoutingTier.T1, resource_type="kubernetes.service"),
            t1=result,
        )
        async with await psycopg.AsyncConnection.connect(dsn) as check:
            row = await (
                await check.execute(
                    "SELECT entry FROM audit_log WHERE action_kind = 'control_loop.t1_evaluate' "
                    "ORDER BY seq DESC LIMIT 1"
                )
            ).fetchone()
        assert row is not None
        audit = row[0]["t1_retained_pattern_comparison"]
        assert audit["local_lease_dependencies_digest"].startswith("sha256:")
        assert audit["local_lease_read_admission_digest"].startswith("sha256:")
        assert audit["local_lease_reuse_admission_digest"].startswith("sha256:")
        assert audit["execution_authority"] is audit["operationally_proven"] is False
    finally:
        if writer is not None and not writer.done():
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        await other.aclose()


@pytest.mark.parametrize("venue", ["deployed", "azure", "production", "local"])
def test_deployed_venue_is_refused(venue: str) -> None:
    with pytest.raises(PermissionError):
        LocalPostgresPatternQualifier(dsn="postgresql://localhost:5433/example", venue=venue)


def test_runtime_database_is_refused() -> None:
    with pytest.raises(PermissionError):
        LocalPostgresPatternQualifier(dsn="postgresql://localhost:5432/example", venue=LOCAL_VENUE)


@pytest.mark.parametrize("cancel", [False, True])
async def test_deadline_and_cancellation_release_actual_owner_rows(
    local_case: tuple[Any, ...], cancel: bool
) -> None:
    _, store, owner, h, source, qualifier, records, _, _, _ = local_case
    entered = asyncio.Event()
    evidence_seen: list[RetainedPatternLeaseEvidence] = []

    class PausedLease:
        @asynccontextmanager
        async def lease(
            self, request: RetainedPatternQualification
        ) -> AsyncIterator[RetainedPatternLeaseEvidence | None]:
            async with qualifier.lease(request) as evidence:
                assert evidence is not None
                evidence_seen.append(evidence)
                entered.set()
                await asyncio.Event().wait()
                yield evidence

    source._leased_qualifier = PausedLease()
    evaluation = asyncio.create_task(
        h.tier(verifier=owner, timeout=5 if cancel else 0.15).evaluate(event=_event())
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    writer = asyncio.create_task(store.delete_state("case-history:latest:" + records[-1].case_id))
    if cancel:
        evaluation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await evaluation
    else:
        result = await evaluation
        assert result.reason == "no_neighbour_found"
        assert result.retained_pattern_comparison.stop_reason == "t1_deadline_exceeded"
    assert await asyncio.wait_for(writer, timeout=2)
    assert evidence_seen[0].guard.active is False


async def test_local_restart_and_default_off_preserve_baseline(
    local_case: tuple[Any, ...],
) -> None:
    dsn, store, owner, h, source, qualifier, _, _, _, _ = local_case
    disabled = await h.tier(verifier=owner, compare=False).evaluate(event=_event())
    assert disabled.retained_pattern_comparison is None
    for _ in range(2):
        source._leased_qualifier = LocalPostgresPatternQualifier(
            dsn=dsn, venue=LOCAL_VENUE, clock=lambda: NOW
        )
        rebuilt = LocalPatternOwner(
            store=store,
            admission=StateStoreDecisionEvidenceAdmissionProvider(store=store, clock=lambda: NOW),
            venue=LOCAL_VENUE,
        )
        result = await h.tier(verifier=rebuilt).evaluate(event=_event())
        assert result.retained_pattern_comparison.challenger_match is not None
        assert result.retained_pattern_comparison.final_lease is not None
        assert (
            replace(result, retained_pattern_comparison=None, eligibility_comparison=None)
            == disabled
        )


async def test_reusable_backend_wires_only_its_owned_local_sources(
    local_case: tuple[Any, ...],
) -> None:
    dsn, _, _, h, _, _, _, _, _, _ = local_case
    backend = LocalPostgresPatternBackend(
        dsn=dsn, venue=LOCAL_VENUE, read_source_revision="a" * 40, clock=lambda: NOW
    )
    assert h.statistics is not None
    bound = BoundRetainedPatternAction(
        str(_event().event_id),
        h.action.signature,
        SimilarityMatch(h.action, 0.98),
        h.statistics.evidence_ref,
        backend.owner.statistics,
    )
    try:
        for enabled in (False, True):
            tier = backend.tier(
                embedding_model=DeterministicEmbeddingModel(),
                baseline_library=_Library(()),
                request_source=BoundRetainedPatternRequest(str(_event().event_id), h.request),
                action_resolver=bound.resolve,
                action_types=lambda: h.registry,
                config=T1Config(compare_eligibility=True) if enabled else None,
            )
            decision = await tier.evaluate(event=_event())
            assert decision.reason == "no_neighbour_found" and decision.best_match is None
            if enabled:
                assert decision.retained_pattern_comparison is not None
                assert decision.retained_pattern_comparison.challenger_match is not None
                assert decision.retained_pattern_comparison.final_lease is not None
                assert decision.retained_pattern_comparison.final_qualification is None
            else:
                assert decision.retained_pattern_comparison is None
    finally:
        await backend.aclose()


async def test_real_retention_deletes_artifacts_and_projection_without_a_copied_index(
    local_case: tuple[Any, ...],
) -> None:
    _, store, owner, h, _, _, records, _, _, _ = local_case
    before = await h.tier(verifier=owner).evaluate(event=_event())
    assert before.retained_pattern_comparison.challenger_match is not None
    metadata = StateStoreCaseHistoryMetadataStore(store=store)
    artifacts = LocalPatternArtifactStore(store=store, venue=LOCAL_VENUE)
    retention = CaseHistoryRetentionService(
        metadata=metadata,
        artifacts=artifacts,
        derived_data=CaseHistoryDerivedRetention(store=store, materializer=h.materializer),
    )
    removed = await retention.delete_due(now=records[0].deletion_due_at)
    assert set(removed) == {record.case_id for record in records}
    for record in records:
        assert await artifacts.get(record.storage_ref) is None
    projected = await store.read_state("case-history-derived:v1:" + "f" * 64)
    assert projected is not None and projected["entries"] == {}
    after = await h.tier(verifier=owner).evaluate(event=_event())
    assert after.retained_pattern_comparison.challenger_match is None
    assert after.retained_pattern_comparison.stop_reason == "no_retained_pattern"


async def test_owner_lease_exit_failure_discards_a_constructed_positive(
    local_case: tuple[Any, ...],
) -> None:
    _, store, owner, h, source, qualifier, records, _, _, _ = local_case

    class ExitFailure:
        @asynccontextmanager
        async def lease(
            self, request: RetainedPatternQualification
        ) -> AsyncIterator[RetainedPatternLeaseEvidence | None]:
            async with qualifier.lease(request) as evidence:
                assert evidence is not None
                yield evidence
                raise OSError("local owner lease release failed")

    source._leased_qualifier = ExitFailure()
    result = await h.tier(verifier=owner).evaluate(event=_event())
    assert result.reason == "no_neighbour_found" and result.best_match is None
    assert result.retained_pattern_comparison.challenger_match is None
    assert result.retained_pattern_comparison.stop_reason == "retained_pattern_error:OSError"
    assert await asyncio.wait_for(
        store.delete_state("case-history:latest:" + records[-1].case_id), timeout=2
    )


async def test_case_expiry_caps_lease_even_without_a_source_write(
    local_case: tuple[Any, ...],
) -> None:
    _, store, owner, h, source, qualifier, records, _, _, _ = local_case
    key = "case-history:latest:" + records[-1].case_id
    raw = dict(await store.read_state(key))
    raw["retention_until"] = (NOW + timedelta(seconds=1)).isoformat()
    raw["deletion_due_at"] = (NOW + timedelta(seconds=1)).isoformat()
    await store.write_state(key, raw)

    class ExpiringLease:
        @asynccontextmanager
        async def lease(
            self, request: RetainedPatternQualification
        ) -> AsyncIterator[RetainedPatternLeaseEvidence | None]:
            async with qualifier.lease(request) as evidence:
                assert evidence is not None
                assert evidence.valid_until == NOW + timedelta(seconds=1)
                source._clock = lambda: NOW + timedelta(seconds=2)
                yield evidence

    source._leased_qualifier = ExpiringLease()
    result = await h.tier(verifier=owner).evaluate(event=_event())
    assert result.reason == "no_neighbour_found"
    assert result.retained_pattern_comparison.challenger_match is None
    assert result.retained_pattern_comparison.stop_reason == (
        "retained_pattern_qualification_rejected"
    )
