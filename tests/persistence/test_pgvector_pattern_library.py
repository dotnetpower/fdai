"""PgVectorPatternLibrary — unit + integration tests.

The database-touching paths are gated on ``AIOPSPILOT_DATABASE_URL`` and
mirror the skip pattern established by
``tests/persistence/test_postgres_state_store.py``. The offline unit
tests below exercise config validation and the vector encoder so the
adapter has coverage even without a live DB.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest

from aiopspilot.core.tiers.t1_lightweight.tier import LearnedAction
from aiopspilot.delivery.persistence import (
    PgVectorPatternLibrary,
    PgVectorPatternLibraryConfig,
)
from aiopspilot.delivery.persistence.pgvector_pattern_library import (
    _coerce_params,
    _encode_vector,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Offline unit tests — no database required.
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


@pytest.mark.asyncio
async def test_search_rejects_zero_k() -> None:
    library = PgVectorPatternLibrary(
        config=PgVectorPatternLibraryConfig(dsn="postgresql://placeholder")
    )
    with pytest.raises(ValueError, match="k MUST"):
        await library.search([0.0] * 384, k=0)


# ---------------------------------------------------------------------------
# Integration tests — require a live Postgres+pgvector.
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration


def _requires_live_db() -> str:
    url = os.environ.get("AIOPSPILOT_DATABASE_URL")
    if not url:
        pytest.skip("AIOPSPILOT_DATABASE_URL is unset")
    return url


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 — controlled subprocess
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
    # earlier runs of the same test — pgvector cannot break score ties by
    # signature, and the shared table is not truncated between tests.
    near_vec = _unit_vector_at(1 + (hash(prefix) % 100))
    far_vec = _unit_vector_at(200 + (hash(prefix) % 100))

    await library.add(vector=near_vec, action=_seed_action(signature=near_sig))
    await library.add(vector=far_vec, action=_seed_action(signature=far_sig))

    # Query the near vector — the identical pattern must top the ranking.
    near_matches = await library.search(near_vec, k=5)
    assert near_matches, "expected at least one match"
    top = near_matches[0]
    assert top.action.signature == near_sig
    assert top.score == pytest.approx(1.0, abs=1e-6)

    # Query the far vector — the identical far pattern must top *that* ranking.
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
    library = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn))

    signature = f"upsert-{uuid.uuid4().hex}"
    baseline_count = await library.count()

    await library.add(
        vector=_unit_vector_at(0),
        action=_seed_action(signature=signature, success_rate=0.5),
    )
    after_first = await library.count()
    assert after_first == baseline_count + 1

    # Second add with same signature — must UPDATE, not duplicate.
    await library.add(
        vector=_unit_vector_at(0),
        action=_seed_action(signature=signature, success_rate=0.9),
    )
    after_second = await library.count()
    assert after_second == after_first, (
        "ON CONFLICT (signature) DO UPDATE must not create a duplicate row"
    )

    matches = await library.search(_unit_vector_at(0), k=10)
    hits = [m for m in matches if m.action.signature == signature]
    assert len(hits) == 1
    assert hits[0].action.success_rate == pytest.approx(0.9)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_respects_k_limit() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    library = PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn))

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
    action = LearnedAction(
        signature=signature,
        rule_id="rg.tagging.owner-required",
        action_type="remediate.set-tag",
        params={"tag": "owner", "value": "team-x", "note": {"nested": True}},
        incident_id="incident-roundtrip",
        success_rate=0.87,
        reuse_count=3,
    )
    await library.add(vector=_unit_vector_at(1), action=action)
    matches = await library.search(_unit_vector_at(1), k=5)
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
