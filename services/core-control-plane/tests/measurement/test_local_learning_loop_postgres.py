"""Azure-free end-to-end learning loop on a loopback PostgreSQL validation cluster.

Chain: enforce dispatch against a local resource with an independent observer, verified outcomes in
the real hash-chained audit log, holdout evidence, shadow growth into the real pgvector library, a
measured success-rate update, a T1 lookup that reuses the pattern, and demotion after failures.
No cloud, model, or Azure call is made; the embedding model is deterministic.

Run through ``scripts/automation/with-local-test-database.py``. The test only deletes the row
of its own unique pattern signature.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fdai.core.control_loop._growth_context import record_growth_context
from fdai.core.measurement.pattern_growth import TemporalHoldoutValidator
from fdai.core.measurement.runners import PatternGrowthIntakeRunner
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.core.tiers.t1_lightweight.tier import T1Config, T1Outcome, T1Tier
from fdai.delivery.measurement.holdout import (
    HoldoutVerifiedPatternBuilder,
    StateStoreTemporalHoldoutEvidenceSource,
)
from fdai.delivery.measurement.pattern_evidence import (
    PatternEvidenceProducer,
    PostgresPatternEvidenceSource,
    PostgresPatternStatisticsWriter,
)
from fdai.delivery.measurement.postgres_growth import (
    PostgresVerifiedOutcomeSource,
    PostgresVerifiedPatternBuilder,
)
from fdai.delivery.measurement.postgres_growth_writer import PostgresShadowPatternWriter
from fdai.delivery.persistence.pgvector_pattern_library import (
    PgVectorPatternLibrary,
    PgVectorPatternLibraryConfig,
)
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.measurement.test_local_learning_loop import (
    _action,
    _event,
    _LocalResource,
    _loop,
    _rule,
)

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _dsn() -> str:
    raw = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("FDAI_DATABASE_URL is unset; run through with-local-test-database.py")
    dsn = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    host = psycopg.conninfo.conninfo_to_dict(dsn).get("host")
    if host not in _LOOPBACK:
        pytest.fail("the local learning loop requires a loopback database")
    return dsn


async def _run_many(
    audit: PostgresStateStore,
    *,
    count: int,
    first: datetime,
    tag: str,
    apply_effect: bool,
) -> datetime:
    clock = first
    for _ in range(count):
        resource = _LocalResource()
        resource.apply_effect = apply_effect
        action = _action(Mode.ENFORCE, start=clock, tag_value=tag).model_copy(
            update={
                "action_id": uuid.uuid4(),
                "idempotency_key": f"learning-loop-{uuid.uuid4()}",
            }
        )
        await record_growth_context(
            audit,
            event=_event("00000000-0000-0000-0000-000000000001", resource="resource:example/rg/a"),
            action=action,
            rule=_rule(),
            incident_id="incident-1",
        )
        await _loop(audit, resource, start=clock)._dispatch_action(
            action=action, rule=_rule(), authorization_decision="auto"
        )
        clock += timedelta(hours=2)
    return clock


@pytest.mark.asyncio
async def test_verified_outcomes_grow_measure_reuse_and_demote_a_pattern() -> None:
    dsn = _dsn()
    tag = f"learning-loop-{uuid.uuid4().hex}"
    audit = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    measurement = InMemoryStateStore()
    config = PgVectorPatternLibraryConfig(dsn=dsn, ivfflat_probes=100)
    library = PgVectorPatternLibrary(config=config)
    embedding = DeterministicEmbeddingModel()
    producer = PatternEvidenceProducer(
        source=PostgresPatternEvidenceSource(dsn=dsn),
        state_store=measurement,
        statistics_writer=PostgresPatternStatisticsWriter(config=config),
    )
    with psycopg.connect(dsn) as connection:
        high_water = connection.execute("SELECT COALESCE(max(seq), 0) FROM audit_log").fetchone()
    assert high_water is not None
    await measurement.write_state("measurement:pattern_growth:watermark", {"seq": high_water[0]})
    signature: str | None = None
    try:
        first = datetime.now(tz=UTC).replace(microsecond=0) - timedelta(days=5)
        next_start = await _run_many(audit, count=22, first=first, tag=tag, apply_effect=True)

        holdout = await producer.publish_holdout_evidence()
        assert holdout.complete_envelopes >= 1

        runner = PatternGrowthIntakeRunner(
            outcome_source=PostgresVerifiedOutcomeSource(dsn=dsn, state_store=measurement),
            pattern_builder=HoldoutVerifiedPatternBuilder(
                delegate=PostgresVerifiedPatternBuilder(dsn=dsn, embedding_model=embedding),
                evidence_source=StateStoreTemporalHoldoutEvidenceSource(measurement),
                validator=TemporalHoldoutValidator(),
                audit_store=measurement,
            ),
            writer=PostgresShadowPatternWriter(config=config),
            audit_store=measurement,
        )
        report = await runner.run_once()
        assert report.accepted_count >= 1
        signature = report.ingested_signatures[0]

        tier = T1Tier(
            embedding_model=embedding,
            pattern_library=library,
            config=T1Config(similarity_threshold=0.8, min_success_rate=0.9),
        )
        probe = _event("00000000-0000-0000-0000-000000000002", resource="resource:example/rg/b")

        shadow = await tier.evaluate(event=probe)
        assert shadow.best_match is not None and shadow.best_match.action.signature == signature
        assert shadow.best_match.action.success_rate == 0.0
        assert shadow.outcome is T1Outcome.ABSTAIN

        promoted = await producer.apply_measured_statistics()
        assert promoted.patterns_updated >= 1
        reused = await tier.evaluate(event=probe)
        assert reused.best_match is not None
        assert reused.best_match.action.success_rate == 1.0
        assert reused.best_match.action.reuse_count >= 22
        assert reused.outcome is T1Outcome.REUSED

        await _run_many(audit, count=5, first=next_start, tag=tag, apply_effect=False)
        demoted_report = await producer.apply_measured_statistics()
        assert demoted_report.patterns_updated >= 1
        demoted = await tier.evaluate(event=probe)
        assert demoted.best_match is not None
        assert demoted.best_match.action.success_rate < 0.9
        assert demoted.outcome is T1Outcome.ABSTAIN
        assert any(
            entry["entry"].get("direction") == "demoted"
            for entry in measurement.audit_entries
            if entry["entry"].get("action_kind") == "measurement.pattern_statistics"
        )
    finally:
        if signature is not None:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    "DELETE FROM t1_pattern_library WHERE signature = %s", (signature,)
                )
