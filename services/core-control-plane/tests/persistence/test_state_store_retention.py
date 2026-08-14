"""Contract tests for the one StateStore removal primitive.

``delete_states_beyond`` is the only way tracked state is ever removed, so its
contract is a safety boundary: it is prefix-scoped, it cannot name a key, and
it removes exactly the rows a bounded newest-first read would never return.
"""

from __future__ import annotations

import pytest
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_PREFIX = "context-selection:evaluation:"


async def _seed(store: InMemoryStateStore, prefix: str, count: int) -> None:
    for index in range(count):
        await store.write_state(f"{prefix}{index:02d}", {"index": index})


async def test_prune_removes_exactly_what_a_bounded_read_would_never_return() -> None:
    store = InMemoryStateStore()
    await _seed(store, _PREFIX, 6)

    retained = await store.read_states(_PREFIX, limit=3)
    removed = await store.delete_states_beyond(_PREFIX, retain_newest=3)

    assert removed == 3
    # The survivors are the same rows, in the same order, the bounded read
    # already returned. Prune and read MUST share one newest-first definition.
    assert await store.read_states(_PREFIX, limit=10) == retained


async def test_prune_never_reaches_outside_its_prefix() -> None:
    store = InMemoryStateStore()
    await _seed(store, _PREFIX, 4)
    await _seed(store, "audit:entry:", 4)

    await store.delete_states_beyond(_PREFIX, retain_newest=1)

    assert len(await store.read_states(_PREFIX, limit=10)) == 1
    # A neighbouring prefix - here an audit-shaped one - is untouched.
    assert len(await store.read_states("audit:entry:", limit=10)) == 4


async def test_prune_is_a_no_op_when_the_bound_is_not_reached() -> None:
    store = InMemoryStateStore()
    await _seed(store, _PREFIX, 3)

    assert await store.delete_states_beyond(_PREFIX, retain_newest=3) == 0
    assert await store.delete_states_beyond(_PREFIX, retain_newest=99) == 0
    assert len(await store.read_states(_PREFIX, limit=10)) == 3


async def test_prune_is_idempotent() -> None:
    store = InMemoryStateStore()
    await _seed(store, _PREFIX, 5)

    first = await store.delete_states_beyond(_PREFIX, retain_newest=2)
    second = await store.delete_states_beyond(_PREFIX, retain_newest=2)

    assert (first, second) == (3, 0)
    assert len(await store.read_states(_PREFIX, limit=10)) == 2


@pytest.mark.parametrize("retain_newest", [0, -1])
async def test_prune_refuses_a_bound_that_would_empty_the_prefix(retain_newest: int) -> None:
    store = InMemoryStateStore()
    await _seed(store, _PREFIX, 2)

    with pytest.raises(ValueError, match="retain_newest"):
        await store.delete_states_beyond(_PREFIX, retain_newest=retain_newest)
    assert len(await store.read_states(_PREFIX, limit=10)) == 2


async def test_prune_refuses_an_empty_prefix() -> None:
    # An empty prefix would match every tracked row in the store, including
    # rows this subsystem does not own.
    store = InMemoryStateStore()
    await _seed(store, _PREFIX, 2)

    with pytest.raises(ValueError, match="prefix"):
        await store.delete_states_beyond("", retain_newest=1)
    assert len(await store.read_states(_PREFIX, limit=10)) == 2
