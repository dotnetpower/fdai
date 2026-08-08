"""Unit tests for the PostgresStateStore helper functions and guards.

The database-touching paths are covered in
``services/core-control-plane/tests/persistence/test_postgres_state_store.py`` (skipped unless
``FDAI_DATABASE_URL`` is set). This file exercises the pure
helpers so the adapter's config validation + hash-chain math has
coverage even without a live DB.
"""

from __future__ import annotations

import pytest
from fdai.delivery.persistence.postgres import (
    PostgresStateStore,
    PostgresStateStoreConfig,
    _canonical,
    _next_hash,
)


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=""))


def test_config_rejects_non_positive_statement_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PostgresStateStore(
            config=PostgresStateStoreConfig(dsn="postgresql://x", statement_timeout_ms=0)
        )


def test_canonical_is_deterministic() -> None:
    a = _canonical({"b": 2, "a": 1})
    b = _canonical({"a": 1, "b": 2})
    assert a == b == '{"a":1,"b":2}'


def test_canonical_stringifies_unserializable() -> None:
    import uuid

    val = uuid.UUID("00000000-0000-0000-0000-000000000001")
    encoded = _canonical({"id": val})
    assert "00000000-0000-0000-0000-000000000001" in encoded


def test_next_hash_chains_previous_and_entry() -> None:
    genesis = "0" * 64
    h1 = _next_hash(genesis, {"seq": 1})
    h2 = _next_hash(h1, {"seq": 2})
    assert h1 != h2
    assert len(h1) == 64
    assert len(h2) == 64
    # Order matters - same entry with a different previous hash produces
    # a distinct chain hash, matching the tamper-evidence invariant.
    h1_bis = _next_hash(genesis, {"seq": 1})
    assert h1 == h1_bis
    h2_bad = _next_hash(genesis, {"seq": 2})
    assert h2 != h2_bad
