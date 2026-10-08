"""Element-sensitive taint for function-local lists in the Python weakness verifier.

A local name bound to a list display is tracked element by element while it is only extended with
``append`` and shrunk with ``pop`` at a fixed index. Any other read, store, deletion, or a branch
merge that disagrees on its length stops tracking, and the verifier falls back to the name's
whole-list label. Tracking lives in the verifier's name-to-label state under keys that can't be
Python identifiers, so it merges and copies with the rest of the state.
"""

from __future__ import annotations

from collections.abc import Sequence

_PREFIX = "<list>"
State = dict[str, str]


def _length_key(name: str) -> str:
    return f"{_PREFIX}{name}"


def _element_key(name: str, index: int) -> str:
    return f"{_PREFIX}{name}#{index}"


def untrack(state: State, name: str) -> None:
    """Forget element labels for ``name``; its whole-list label stays."""
    length = _length_key(name)
    for key in [key for key in state if key == length or key.startswith(f"{length}#")]:
        del state[key]


def track(state: State, name: str, labels: Sequence[str | None]) -> None:
    """Start tracking ``name`` as a list whose elements carry ``labels``."""
    untrack(state, name)
    state[_length_key(name)] = str(len(labels))
    for index, label in enumerate(labels):
        if label:
            state[_element_key(name, index)] = label


def length(state: State, name: str) -> int | None:
    """Return the tracked length of ``name`` or ``None`` when it isn't tracked."""
    value = state.get(_length_key(name))
    return None if value is None else int(value)


def _labels(state: State, name: str, size: int) -> list[str | None]:
    return [state.get(_element_key(name, index)) for index in range(size)]


def _position(size: int, index: int) -> int | None:
    position = index + size if index < 0 else index
    return position if 0 <= position < size else None


def element(state: State, name: str, index: int) -> str | None:
    """Return the label of one tracked element; an out-of-range read raises, so it is clean."""
    size = length(state, name)
    if size is None:
        return state.get(name)
    position = _position(size, index)
    return None if position is None else state.get(_element_key(name, position))


def append(state: State, name: str, label: str | None) -> None:
    """Record one appended element."""
    size = length(state, name)
    if size is None:
        return
    track(state, name, [*_labels(state, name, size), label])


def pop(state: State, name: str, index: int) -> bool:
    """Remove one tracked element; return ``False`` and stop tracking when it can't apply."""
    size = length(state, name)
    position = None if size is None else _position(size, index)
    if size is None or position is None:
        untrack(state, name)
        return False
    labels = _labels(state, name, size)
    del labels[position]
    track(state, name, labels)
    return True


def merge(live: Sequence[State], merged: State) -> None:
    """Keep tracking only names every live branch tracks with the same length."""
    names = {
        key.removeprefix(_PREFIX)
        for state in live
        for key in state
        if key.startswith(_PREFIX) and "#" not in key
    }
    for name in names:
        lengths = {state.get(_length_key(name)) for state in live}
        if len(lengths) != 1 or None in lengths:
            untrack(merged, name)
