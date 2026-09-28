"""In-memory ``read_state_page`` dotted field paths match the PostgreSQL contract."""

from __future__ import annotations

import pytest
from fdai.shared.providers.state_store import state_field_path
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.providers.state_store_field_path_cases import assert_field_path_semantics


async def test_in_memory_store_matches_nested_values_like_postgres() -> None:
    await assert_field_path_semantics(InMemoryStateStore(), "field_path%case:")


async def test_single_identifier_filter_is_unchanged() -> None:
    store = InMemoryStateStore()
    await store.write_state("row:a", {"source_confirmed": True, "kind": "a.b"})
    await store.write_state("row:b", {"source_confirmed": False, "kind": "b"})

    rows, total = await store.read_state_page(
        "row:", limit=10, field="source_confirmed", value="true"
    )
    assert total == 1 and rows[0]["kind"] == "a.b"
    rows, total = await store.read_state_page("row:", limit=10, field="kind", value="a.b")
    assert total == 1


@pytest.mark.parametrize(
    ("field", "segments"),
    [
        ("publication_outbox.published", ("publication_outbox", "published")),
        ("a.b.c", ("a", "b", "c")),
        ("A_1.b2", ("A_1", "b2")),
    ],
)
def test_state_field_path_accepts_dotted_ascii_identifiers(
    field: str, segments: tuple[str, ...]
) -> None:
    assert state_field_path(field) == segments


@pytest.mark.parametrize("field", ["published", "", "a..b", "a.b-c", "a.\u00e9"])
def test_state_field_path_rejects_anything_else(field: str) -> None:
    with pytest.raises(ValueError, match="state field path"):
        state_field_path(field)
