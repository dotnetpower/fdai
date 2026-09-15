"""PgVectorPatternLibrary - unit + integration tests.

The database-touching paths are gated on ``FDAI_DATABASE_URL`` and
mirror the skip pattern established by
``services/core-control-plane/tests/persistence/test_postgres_state_store.py``. The offline unit
tests below exercise config validation and the vector encoder so the
adapter has coverage even without a live DB.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.tiers.t1_lightweight import LearnedAction, OperationalCaseContext
from fdai.delivery.persistence import (
    PgVectorPatternLibrary,
    PgVectorPatternLibraryConfig,
)
from fdai.delivery.persistence.pgvector_pattern_library import (
    _coerce_operational_case,
    _coerce_params,
    _encode_operational_case,
    _encode_vector,
)

from tests.persistence.test_postgres_forecast_episode import forecast_database as forecast_database

REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# Offline unit tests - no database required.
# ---------------------------------------------------------------------------


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=""))


def test_config_rejects_non_positive_statement_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PgVectorPatternLibrary(
            config=PgVectorPatternLibraryConfig(dsn="postgresql://x", statement_timeout_ms=0)
        )


def test_config_rejects_non_positive_probes() -> None:
    with pytest.raises(ValueError, match="probes"):
        PgVectorPatternLibrary(
            config=PgVectorPatternLibraryConfig(dsn="postgresql://x", ivfflat_probes=0)
        )


def test_encode_vector_produces_pgvector_literal() -> None:
    vector = [0.0] * 384
    vector[0] = 1.0
    vector[-1] = -0.5
    encoded = _encode_vector(vector)
    assert encoded.startswith("[")
    assert encoded.endswith("]")
    # 383 commas separate 384 values.
    assert encoded.count(",") == 383
    # First and last values survive the round-trip.
    assert encoded.startswith("[1,")
    assert encoded.endswith(",-0.5]")


def test_encode_vector_rejects_wrong_dimension() -> None:
    with pytest.raises(ValueError, match="embedding dim"):
        _encode_vector([0.1, 0.2, 0.3])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_encode_vector_rejects_non_finite_values(value: float) -> None:
    vector = [0.0] * 384
    vector[0] = value

    with pytest.raises(ValueError, match="MUST be finite"):
        _encode_vector(vector)


def test_coerce_params_accepts_dict_and_string() -> None:
    assert _coerce_params(None) == {}
    assert _coerce_params({"a": 1}) == {"a": 1}
    assert _coerce_params('{"b": 2}') == {"b": 2}


def test_coerce_params_rejects_non_object_json() -> None:
    with pytest.raises(RuntimeError, match="JSON object"):
        _coerce_params("[1, 2, 3]")


def test_coerce_params_rejects_unexpected_type() -> None:
    with pytest.raises(RuntimeError, match="unexpected type"):
        _coerce_params(42)


def test_operational_case_context_codec_round_trips() -> None:
    context = OperationalCaseContext(
        case_ref=f"case-history:case-a:1:{'a' * 64}",
        failure_fingerprint="f" * 64,
        resource_type="kubernetes.service",
        action_type="ops.scale-out",
        required_topology_role="serves",
        graph_digest="b" * 64,
        owner_digest="c" * 64,
        evidence_cutoff=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert _coerce_operational_case(_encode_operational_case(context)) == context
    assert _encode_operational_case(None) is None
    assert _coerce_operational_case(None) is None


def test_operational_case_context_codec_rejects_unknown_fields() -> None:
    with pytest.raises(RuntimeError, match="operational_case is invalid"):
        _coerce_operational_case({"case_ref": "unexpected-only"})


@pytest.mark.asyncio
async def test_search_rejects_zero_k() -> None:
    library = PgVectorPatternLibrary(
        config=PgVectorPatternLibraryConfig(dsn="postgresql://placeholder")
    )
    with pytest.raises(ValueError, match="k MUST"):
        await library.search([0.0] * 384, k=0)


async def test_retention_lock_uses_fresh_snapshot_after_waiting():
    from unittest.mock import AsyncMock, call

    connection = AsyncMock()
    library = PgVectorPatternLibrary(
        config=PgVectorPatternLibraryConfig(dsn="postgresql://example")
    )
    await library._retention_lock(connection)
    assert connection.execute.await_args_list == [
        call("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"),
        call("SELECT pg_advisory_xact_lock(hashtextextended('fdai.t1.case-retention', 0))"),
    ]


@pytest.mark.parametrize("operation", ["add", "purge"])
@pytest.mark.parametrize("failure", ["timeout", "cancel"])
async def test_pattern_mutations_bound_connection_wait_and_propagate_cancellation(
    monkeypatch, operation, failure
):
    import asyncio

    import psycopg
    from fdai.core.case_history import CaseHistoryMaterializer
    from fdai.core.case_history.testing import (
        InMemoryCaseHistoryArtifactStore,
        InMemoryCaseHistoryMetadataStore,
    )

    from tests.core.case_history.test_service import _seal

    entered = asyncio.Event()

    async def stalled(*_args, **_kwargs):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", stalled)
    timeout = asyncio.timeout
    budgets = []

    def deadline(seconds):
        budgets.append(seconds)
        return timeout(0 if failure == "timeout" else seconds)

    monkeypatch.setattr(asyncio, "timeout", deadline)
    library = PgVectorPatternLibrary(
        config=PgVectorPatternLibraryConfig(dsn="postgresql://example")
    )
    if operation == "add":
        work = library.add(vector=[0.0] * 384, action=_seed_action(signature="bounded"))
    else:
        source = await _seal(
            CaseHistoryMaterializer(
                metadata=InMemoryCaseHistoryMetadataStore(),
                artifacts=InMemoryCaseHistoryArtifactStore(),
            )
        )
        work = library.purge(
            replace(
                source,
                deletion_started_at=source.deletion_due_at,
                deletion_storage_refs=(source.storage_ref,),
            )
        )
    task = asyncio.create_task(work)
    if failure == "cancel":
        await entered.wait()
        task.cancel()
    with pytest.raises(TimeoutError if failure == "timeout" else asyncio.CancelledError):
        await task
    assert budgets == [15]


# ---------------------------------------------------------------------------
# Integration tests - require a live Postgres+pgvector.
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _unit_vector_at(index: int) -> Sequence[float]:
    """Return a length-384 unit vector with a 1.0 in ``index``, else 0.0."""
    vec = [0.0] * 384
    vec[index] = 1.0
    return vec


def _distinct_vector(seed: str) -> Sequence[float]:
    """Return a replay-stable vector that avoids shared-database tie collisions."""

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    vec = [0.0] * 384
    for offset, value in enumerate(digest):
        vec[offset * 11] = (value + 1) / 256
    return vec


def _seed_action(*, signature: str, success_rate: float = 0.95) -> LearnedAction:
    return LearnedAction(
        signature=signature,
        rule_id="object-storage.public-access.deny",
        action_type="remediate.disable-public-access",
        params={"reason": "test"},
        incident_id=f"incident-{signature}",
        success_rate=success_rate,
    )


@pytest.mark.integration
async def test_case_upsert_cannot_rebind_retained_action_in_postgres(forecast_database):
    import asyncio
    import json

    import psycopg
    from fdai.core.case_history import CaseHistoryMaterializer, CaseHistoryRetentionService
    from fdai.core.case_history.derived import CaseHistoryDerivedRetention
    from fdai.core.case_history.testing import (
        InMemoryCaseHistoryArtifactStore,
        InMemoryCaseHistoryMetadataStore,
    )
    from fdai.shared.providers.testing.state_store import InMemoryStateStore
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from tests.core.case_history.test_service import _seal

    async with await psycopg.AsyncConnection.connect(forecast_database) as connection:
        cursor = await connection.execute(
            "SELECT nspname FROM pg_extension JOIN pg_namespace ON extnamespace=pg_namespace.oid "
            "WHERE extname='vector'"
        )
        extension = await cursor.fetchone()
        if extension is None:
            await connection.execute("CREATE EXTENSION vector")
            extension = (conninfo_to_dict(forecast_database)["options"].split("=", 1)[1],)
    settings = conninfo_to_dict(forecast_database)
    dsn = make_conninfo(forecast_database, options=settings["options"] + "," + extension[0])
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            "CREATE TABLE state_kv (key TEXT PRIMARY KEY, value JSONB NOT NULL, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
        await connection.execute(
            "CREATE TABLE t1_pattern_library (signature TEXT PRIMARY KEY, rule_id TEXT NOT NULL, "
            "action_type TEXT NOT NULL, params JSONB NOT NULL, embedding vector(384) NOT NULL, "
            "source_incident_id TEXT NOT NULL, historical_success_rate DOUBLE PRECISION NOT NULL, "
            "reuse_count INTEGER NOT NULL, operational_case JSONB)"
        )
    library = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn))
    metadata, artifacts = InMemoryCaseHistoryMetadataStore(), InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    source = await _seal(materializer)
    context = OperationalCaseContext(
        case_ref=f"case-history:{source.case_id}:{source.revision}:{source.manifest_digest}",
        failure_fingerprint="f" * 64,
        resource_type="kubernetes.service",
        action_type="remediate.disable-public-access",
        required_topology_role="serves",
        graph_digest="b" * 64,
        owner_digest="c" * 64,
        evidence_cutoff=source.sealed_at,
        access_scope_digest=source.access_scope_digest,
        purpose=source.purpose,
    )
    original = replace(_seed_action(signature="case-bound"), operational_case=context)
    vector = _distinct_vector("case-bound")
    await library.add(vector=vector, action=original)
    await library.add(
        vector=vector, action=replace(original, operational_case=None, success_rate=0.8)
    )
    for change in (
        {"rule_id": "other.rule"},
        {"action_type": "ops.scale-out"},
        {"params": {"reason": "changed"}},
        {"incident_id": "other-incident"},
        {"operational_case": replace(context, access_scope_digest="e" * 64)},
        {"operational_case": replace(context, case_ref=f"case-history:case-b:1:{'a' * 64}")},
    ):
        for omitted in (False, True):
            if omitted and "operational_case" in change:
                continue
            candidate = replace(
                original, **({"operational_case": None} if omitted else {}), **change
            )
            with pytest.raises(ValueError, match="cannot replace"):
                await library.add(vector=vector, action=candidate)
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute(
            "SELECT rule_id, action_type, params, source_incident_id, operational_case, "
            "historical_success_rate FROM t1_pattern_library WHERE signature = %s",
            (original.signature,),
        )
        assert await cursor.fetchone() == (
            original.rule_id,
            original.action_type,
            dict(original.params),
            original.incident_id,
            json.loads(_encode_operational_case(context)),
            0.8,
        )
    with pytest.raises(PermissionError, match="deletion claim"):
        await library.purge(source)
    with pytest.raises(PermissionError, match="deletion claim"):
        await library.purge(
            replace(
                source,
                deletion_started_at=source.deletion_due_at,
                deletion_storage_refs=(source.storage_ref,),
                legal_hold=True,
                legal_hold_ref="hold:example",
            )
        )
    other = replace(
        original,
        signature="unrelated",
        operational_case=replace(
            context, case_ref=f"case-history:case-other:1:{'a' * 64}", access_scope_digest="e" * 64
        ),
    )
    await library.add(vector=vector, action=other)
    legacy = replace(
        original,
        signature="legacy-case-copy",
        operational_case=replace(context, access_scope_digest=None, purpose=None),
    )
    await library.add(vector=vector, action=legacy)
    derived_state = InMemoryStateStore()
    retention = CaseHistoryRetentionService(
        metadata=metadata,
        artifacts=artifacts,
        derived_data=CaseHistoryDerivedRetention(
            store=derived_state, materializer=materializer, downstream=(library,)
        ),
    )
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            "CREATE FUNCTION reject_pattern_delete() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'synthetic deletion failure'; END $$"
        )
        await connection.execute(
            "CREATE TRIGGER pattern_delete_failure BEFORE DELETE ON t1_pattern_library "
            "FOR EACH ROW EXECUTE FUNCTION reject_pattern_delete()"
        )
    with pytest.raises(psycopg.errors.RaiseException):
        await retention.delete_due(now=source.deletion_due_at)
    pending = await metadata.latest(source.case_id, access_scope_digest=source.access_scope_digest)
    assert (
        pending is not None
        and pending.deletion_started_at is not None
        and pending.deleted_at is None
    )
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute("SELECT COUNT(*) FROM state_kv")
        assert await cursor.fetchone() == (0,)
        cursor = await connection.execute("SELECT COUNT(*) FROM t1_pattern_library")
        assert await cursor.fetchone() == (3,)
        await connection.execute("DROP TRIGGER pattern_delete_failure ON t1_pattern_library")
        await connection.execute(
            "INSERT INTO t1_pattern_library SELECT 'batch-' || item, rule_id, action_type, params, "
            "embedding, source_incident_id, historical_success_rate, reuse_count, operational_case "
            "FROM t1_pattern_library CROSS JOIN generate_series(1, 1000) AS item "
            "WHERE signature=%s",
            (original.signature,),
        )
    with pytest.raises(RuntimeError, match="batch committed"):
        await retention.delete_due(now=source.deletion_due_at)
    pending = await metadata.latest(source.case_id, access_scope_digest=source.access_scope_digest)
    assert pending is not None and pending.deleted_at is None
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute("SELECT COUNT(*) FROM t1_pattern_library")
        assert await cursor.fetchone() == (3,)
    deleted, late = await asyncio.gather(
        retention.delete_due(now=source.deletion_due_at),
        library.add(vector=vector, action=replace(original, signature="late-case-write")),
        return_exceptions=True,
    )
    assert deleted == (source.case_id,)
    assert late is None or isinstance(late, PermissionError)
    restarted = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn))
    for action in (
        original,
        replace(original, operational_case=None),
        replace(original, signature="different-signature"),
    ):
        with pytest.raises(PermissionError, match="pending deletion"):
            await restarted.add(vector=vector, action=action)
    assert await retention.delete_due(now=source.deletion_due_at) == ()
    await restarted.purge(pending)
    assert await derived_state.verify_chain()
    assert await artifacts.get(source.storage_ref) is None
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        cursor = await connection.execute("SELECT signature FROM t1_pattern_library")
        assert await cursor.fetchall() == [(other.signature,)]
        cursor = await connection.execute("SELECT key, value FROM state_kv")
        markers = await cursor.fetchall()
        assert len(markers) == 1003
        assert all(
            source.case_id not in key
            and source.case_id not in json.dumps(value)
            and value["execution_authority"] is False
            for key, value in markers
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_add_then_search_returns_nearest_first() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    library = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn))

    prefix = uuid.uuid4().hex
    near_sig = f"{prefix}-near"
    far_sig = f"{prefix}-far"

    # Distinct vectors so this run's rows are not colliding with rows from
    # earlier runs of the same test - pgvector cannot break score ties by
    # signature, and the shared table is not truncated between tests.
    near_vec = _distinct_vector(near_sig)
    far_vec = _distinct_vector(far_sig)

    await library.add(vector=near_vec, action=_seed_action(signature=near_sig))
    await library.add(vector=far_vec, action=_seed_action(signature=far_sig))

    # Query the near vector - the identical pattern must top the ranking.
    near_matches = await library.search(near_vec, k=5)
    assert near_matches, "expected at least one match"
    top = near_matches[0]
    assert top.action.signature == near_sig
    assert top.score == pytest.approx(1.0, abs=1e-6)

    # Query the far vector - the identical far pattern must top *that* ranking.
    # (A shared table across test runs means other orthogonal patterns can
    # crowd the top-k of an unrelated query; this assertion pins the property
    # that "identical vector → score ≈ 1.0", not a global top-k position.)
    far_matches = await library.search(far_vec, k=5)
    assert far_matches, "expected at least one match for the far query"
    far_top = far_matches[0]
    assert far_top.action.signature == far_sig
    assert far_top.score == pytest.approx(1.0, abs=1e-6)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_add_upserts_on_signature_conflict() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    library = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn, ivfflat_probes=1))

    signature = f"upsert-{uuid.uuid4().hex}"
    vector = _distinct_vector(signature)
    baseline_count = await library.count()

    await library.add(
        vector=vector,
        action=_seed_action(signature=signature, success_rate=0.5),
    )
    after_first = await library.count()
    assert after_first == baseline_count + 1

    # Second add with same signature - must UPDATE, not duplicate.
    await library.add(
        vector=vector,
        action=_seed_action(signature=signature, success_rate=0.9),
    )
    after_second = await library.count()
    assert after_second == after_first, (
        "ON CONFLICT (signature) DO UPDATE must not create a duplicate row"
    )

    matches = await library.search(vector, k=10)
    hits = [m for m in matches if m.action.signature == signature]
    assert len(hits) == 1
    assert hits[0].action.success_rate == pytest.approx(0.9)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_contextless_upsert_preserves_existing_operational_context() -> None:
    url = _requires_live_db()
    _upgrade_head()
    library = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=_plain_dsn(url)))
    signature = f"context-upsert-{uuid.uuid4().hex}"
    context = OperationalCaseContext(
        case_ref=f"case-history:case-a:1:{'a' * 64}",
        failure_fingerprint="f" * 64,
        resource_type="kubernetes.service",
        action_type="ops.scale-out",
        required_topology_role="serves",
        graph_digest="b" * 64,
        owner_digest="c" * 64,
        evidence_cutoff=datetime(2026, 8, 1, tzinfo=UTC),
    )
    contextual = replace(
        _seed_action(signature=signature),
        operational_case=context,
    )
    vector = _distinct_vector(signature)
    await library.add(vector=vector, action=contextual)
    await library.add(vector=vector, action=_seed_action(signature=signature))

    match = next(
        item for item in await library.search(vector, k=20) if item.action.signature == signature
    )
    assert match.action.operational_case == context


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_respects_k_limit() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    library = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn, ivfflat_probes=1))

    prefix = uuid.uuid4().hex
    for i in range(3):
        await library.add(
            vector=_unit_vector_at(i),
            action=_seed_action(signature=f"{prefix}-{i}"),
        )
    matches = await library.search(_unit_vector_at(0), k=2)
    assert len(matches) == 2
    # Descending similarity.
    for a, b in zip(matches, matches[1:], strict=False):
        assert a.score >= b.score


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_returns_learned_action_fields_intact() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    library = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn))

    signature = f"roundtrip-{uuid.uuid4().hex}"
    vector = _distinct_vector(signature)
    action = LearnedAction(
        signature=signature,
        rule_id="rg.tagging.owner-required",
        action_type="remediate.set-tag",
        params={"tag": "owner", "value": "team-x", "note": {"nested": True}},
        incident_id="incident-roundtrip",
        success_rate=0.87,
        reuse_count=3,
        operational_case=OperationalCaseContext(
            case_ref=f"case-history:case-roundtrip:1:{'a' * 64}",
            failure_fingerprint="f" * 64,
            resource_type="resource-group",
            action_type="remediate.set-tag",
            required_topology_role="contains",
            graph_digest="b" * 64,
            owner_digest="c" * 64,
            evidence_cutoff=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    )
    await library.add(vector=vector, action=action)
    matches = await library.search(vector, k=5)
    hits = [m for m in matches if m.action.signature == signature]
    assert hits, "seeded pattern should be retrievable"
    got = hits[0].action
    assert got.rule_id == "rg.tagging.owner-required"
    assert got.action_type == "remediate.set-tag"
    assert dict(got.params) == {
        "tag": "owner",
        "value": "team-x",
        "note": {"nested": True},
    }
    assert got.incident_id == "incident-roundtrip"
    assert got.success_rate == pytest.approx(0.87)
    assert got.reuse_count == 3
    assert got.operational_case == action.operational_case
