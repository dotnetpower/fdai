"""The audit chain rule is one rule, not one per backend.

A chain written by the in-memory backend is verified by the PostgreSQL backend
after a migration, and vice versa. That only holds if both compute the identical
digest for the identical entry - one whitespace or key-ordering difference would
report an intact log as tampered. The rule used to be duplicated in both
backends with nothing checking that the copies agreed; these tests check it.
"""

from __future__ import annotations

from fdai.shared.providers.audit_hash import GENESIS_HASH, canonical_entry, next_hash


def test_the_genesis_hash_is_the_documented_constant() -> None:
    assert GENESIS_HASH == "0" * 64


def test_key_order_does_not_change_the_digest() -> None:
    """Entries are dicts; insertion order must not decide the hash."""
    a = {"action_kind": "executor.apply", "mode": "shadow", "seq": 1}
    b = {"seq": 1, "mode": "shadow", "action_kind": "executor.apply"}

    assert next_hash(GENESIS_HASH, a) == next_hash(GENESIS_HASH, b)


def test_the_previous_hash_participates_in_the_digest() -> None:
    """Otherwise entries could be reordered without breaking the chain."""
    entry = {"action_kind": "executor.apply"}

    assert next_hash(GENESIS_HASH, entry) != next_hash("f" * 64, entry)


def test_canonical_form_carries_no_incidental_whitespace() -> None:
    rendered = canonical_entry({"b": 2, "a": 1})

    assert rendered == '{"a":1,"b":2}'


def test_both_state_store_backends_agree_on_the_same_chain() -> None:
    """The in-memory and PostgreSQL backends now share one implementation.

    Imported through each backend's own module so the test fails if either
    stops delegating and reintroduces a private copy.
    """
    from fdai.delivery.persistence.postgres import _GENESIS_HASH as PG_GENESIS
    from fdai.delivery.persistence.postgres import _next_hash as pg_next
    from fdai.shared.providers.testing.state_store import _GENESIS_HASH as MEM_GENESIS
    from fdai.shared.providers.testing.state_store import _next_hash as mem_next

    assert PG_GENESIS == MEM_GENESIS

    previous_pg = PG_GENESIS
    previous_mem = MEM_GENESIS
    for index in range(5):
        entry = {"action_kind": "executor.apply", "seq": index, "mode": "shadow"}
        previous_pg = pg_next(previous_pg, entry)
        previous_mem = mem_next(previous_mem, entry)
        assert previous_pg == previous_mem
