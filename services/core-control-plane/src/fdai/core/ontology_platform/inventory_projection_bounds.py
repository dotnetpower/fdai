"""Admit expanded normalization work without copying an inventory observation."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import fields, is_dataclass
from itertools import chain

_MAX_PROJECTION_VALUES = 2_000_000
_MAX_PROJECTION_CHARACTERS = 16 * 1024 * 1024
_MAX_PROJECTION_INPUT_DEPTH = 128


def validate_projection_allocation(values: Iterable[object]) -> None:
    """Charge repeated aliases again; retain only the active path to detect cycles.

    Explicit expanded-value and character counts bound work, not process RSS.
    Unsupported scalar validation remains with the canonical normalizer.
    """
    stack: list[tuple[Iterator[object], int | None]] = [(iter(values), None)]
    active: set[int] = set()
    value_count = 0
    character_count = 0
    while stack:
        iterator, owner_id = stack[-1]
        try:
            value = next(iterator)
        except StopIteration:
            stack.pop()
            if owner_id is not None:
                active.remove(owner_id)
            continue
        value_count += 1
        if value_count > _MAX_PROJECTION_VALUES:
            raise ValueError("inventory projection allocation exceeds its expanded-value bound")
        if isinstance(value, str):
            character_count += len(value)
            if character_count > _MAX_PROJECTION_CHARACTERS:
                raise ValueError("inventory projection allocation exceeds its character bound")
        children = _children(value)
        if children is None:
            continue
        identity = id(value)
        if identity in active:
            raise ValueError("inventory projection contains cyclic input")
        if len(stack) > _MAX_PROJECTION_INPUT_DEPTH:
            raise ValueError("inventory projection input nesting exceeds its bound")
        active.add(identity)
        stack.append((children, identity))


def _children(value: object) -> Iterator[object] | None:
    if isinstance(value, Mapping):
        return chain.from_iterable(value.items())
    if isinstance(value, (set, frozenset)):
        return iter(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return iter(value)
    if is_dataclass(value) and not isinstance(value, type):
        return (getattr(value, field.name) for field in fields(value))
    return None
