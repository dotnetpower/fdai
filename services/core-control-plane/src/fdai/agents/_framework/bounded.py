"""Bounded LRU containers for long-lived agent state.

A pantheon agent runs for the lifetime of the process, so any per-event or
per-resource map it keeps MUST be bounded or it leaks memory. These are the
shared, deterministic LRU containers agents use to cap that state: adding a
new key past ``maxsize`` evicts the least-recently-used entry. Eviction is
deterministic (insertion / access order), so a replay is reproducible.

Kept in ``_framework/`` because several agents (Norns, Forseti) need the
same bound - one implementation so the cap semantics never diverge.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator

# A floor: a maxsize below this is almost certainly a misconfiguration that
# would evict useful state on nearly every insert.
_MIN_MAXSIZE = 1


class BoundedLruSet[K]:
    """A membership set capped at ``maxsize`` (insertion-order eviction).

    ``add`` past the cap drops the oldest key. Used for "have I already
    handled this id?" guards keyed by an unbounded id (a correlation id, one
    per event), which would otherwise grow forever.

    ``__contains__`` is **pure** - a membership test (``key in s``) never
    reorders eviction. For a dedup guard this is the correct semantics: a
    repeated *check* must not keep an id alive forever; only a repeated
    ``add`` refreshes it. (This is deliberately insertion/refresh-order, not
    access-order, LRU.)
    """

    __slots__ = ("_d", "_max")

    def __init__(self, maxsize: int) -> None:
        if maxsize < _MIN_MAXSIZE:
            raise ValueError(f"maxsize MUST be >= {_MIN_MAXSIZE}, got {maxsize}")
        self._d: OrderedDict[K, None] = OrderedDict()
        self._max = maxsize

    def __contains__(self, key: K) -> bool:
        # Pure: no move_to_end. A membership check must not mutate eviction
        # order (Python's __contains__ convention + correct dedup semantics).
        return key in self._d

    def add(self, key: K) -> None:
        if key in self._d:
            self._d.move_to_end(key)
            return
        self._d[key] = None
        if len(self._d) > self._max:
            self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)


class BoundedLruDict[K, V]:
    """A dict capped at ``maxsize`` (LRU eviction on insert).

    Reading with :meth:`get` marks the key most-recently-used; inserting a
    new key past the cap drops the least-recently-used entry. Used for
    per-target accumulator maps (outcome tallies, domain advice) so they
    cannot grow without bound across every resource the agent ever sees.
    """

    __slots__ = ("_d", "_max")

    def __init__(self, maxsize: int) -> None:
        if maxsize < _MIN_MAXSIZE:
            raise ValueError(f"maxsize MUST be >= {_MIN_MAXSIZE}, got {maxsize}")
        self._d: OrderedDict[K, V] = OrderedDict()
        self._max = maxsize

    def __contains__(self, key: K) -> bool:
        return key in self._d

    def __len__(self) -> int:
        return len(self._d)

    def get(self, key: K, default: V | None = None) -> V | None:
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return default

    def set(self, key: K, value: V) -> None:
        if key in self._d:
            self._d.move_to_end(key)
        self._d[key] = value
        if len(self._d) > self._max:
            self._d.popitem(last=False)

    def pop(self, key: K, default: V | None = None) -> V | None:
        return self._d.pop(key, default)

    def items(self) -> Iterator[tuple[K, V]]:
        return iter(self._d.items())


__all__ = ["BoundedLruSet", "BoundedLruDict"]
