"""Shared ``read_state_page`` dotted field-path cases for every StateStore backend."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.shared.providers.state_store import StateStore

ROWS: dict[str, dict[str, Any]] = {
    "bool-false": {"outbox": {"published": False}},
    "bool-true": {"outbox": {"published": True}},
    "string-false": {"outbox": {"published": "false"}},
    "number-zero": {"outbox": {"published": 0}},
    "json-null": {"outbox": {"published": None}},
    "missing-leaf": {"outbox": {}},
    "missing-parent": {"other": {"published": False}},
    "null-parent": {"outbox": None},
    "scalar-parent": {"outbox": "published"},
    "quoted": {"outbox": {"state": 'it\'s "quoted" 100% _x_'}},
    "deep": {"a": {"b": {"c": False}}},
    "top-level": {"kind": "twin-row"},
}

EXPECTED: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("outbox.published", "false", frozenset({"bool-false", "string-false"})),
    ("outbox.published", "true", frozenset({"bool-true"})),
    ("outbox.state", 'it\'s "quoted" 100% _x_', frozenset({"quoted"})),
    ("outbox.state", "it's", frozenset()),
    ("a.b.c", "false", frozenset({"deep"})),
    ("kind", "twin-row", frozenset({"top-level"})),
)

INVALID_PATHS = (
    "outbox..published",
    ".outbox",
    "outbox.",
    "outbox.pub-lished",
    "outbox.published'",
    "outbox.\u00e9",
    "outbox.pub lished",
    "outbox.%",
    "outbox.{a,b}",
    "outbox.0.published",
    "outbox.9lives",
)


async def assert_field_path_semantics(store: StateStore, prefix: str) -> None:
    """Seed ``prefix`` and prove nested matching, paging, scoping, and validation."""

    for name, value in ROWS.items():
        await store.write_state(f"{prefix}{name}", {"name": name, **value})
    wildcard_lookalike = prefix.replace("_", "Z").replace("%", "Z")
    await store.write_state(
        f"{wildcard_lookalike}bool-false", {"name": "outside", "outbox": {"published": False}}
    )

    for field, value, names in EXPECTED:
        rows, total = await store.read_state_page(prefix, limit=100, field=field, value=value)
        assert {row["name"] for row in rows} == names, (field, value)
        assert total == len(names), (field, value)
    rows, total = await store.read_state_page(
        prefix, limit=1, offset=1, field="outbox.published", value="false"
    )
    assert total == 2 and len(rows) == 1
    for invalid in INVALID_PATHS:
        with pytest.raises(ValueError, match="state field path"):
            await store.read_state_page(prefix, limit=10, field=invalid, value="false")
