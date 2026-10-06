"""The environment context is principal-scoped model context with honest completeness."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fdai.core.conversation.semantic_environment_context import (
    bind_environment_context,
    current_environment_context,
    resource_group_context,
    safe_environment_context,
)

NOW = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)


class _Gateway:
    def __init__(self, names: list[tuple[str, str]], *, complete: bool = True, fail: bool = False):
        self._names = names
        self._complete = complete
        self._fail = fail
        self.definitions: list[Any] = []

    async def materialize(self, definition: Any, *, projection_request: Any) -> Any:
        self.definitions.append(definition)
        if self._fail:
            raise RuntimeError("store unavailable")
        records = [
            SimpleNamespace(
                properties={"name": name, "location": location, "type": "resource-group"}
            )
            for name, location in self._names[: definition.limit]
        ]
        return SimpleNamespace(
            materialization=SimpleNamespace(graph=SimpleNamespace(objects=records)),
            receipt=SimpleNamespace(
                source_complete=self._complete,
                truncated=len(self._names) > definition.limit,
            ),
        )


def _read(gateway: _Gateway, limit: int = 200) -> Any:
    return asyncio.run(
        resource_group_context(
            gateway,  # type: ignore[arg-type]
            projection_request=object(),  # type: ignore[arg-type]
            purpose="operations-review",
            as_of=lambda: NOW,
            limit=limit,
        )
    )


def test_a_complete_read_lists_every_group_sorted_and_marks_the_list_whole() -> None:
    gateway = _Gateway([("rg-b", "westus3"), ("rg-a", "koreacentral")])

    context = _read(gateway)

    assert context == {
        "kind": "resource_groups",
        "complete": True,
        "resource_groups": [
            {"name": "rg-a", "location": "koreacentral"},
            {"name": "rg-b", "location": "westus3"},
        ],
    }
    predicate = gateway.definitions[0].predicates[0]
    assert (predicate.property, predicate.equals) == ("type", "resource-group")
    assert gateway.definitions[0].limit == 201


def test_a_bounded_or_incomplete_read_never_claims_the_list_is_whole() -> None:
    many = [(f"rg-{index:03d}", "koreacentral") for index in range(5)]

    bounded = _read(_Gateway(many), limit=3)
    incomplete = _read(_Gateway(many[:2], complete=False))

    assert bounded["complete"] is False and len(bounded["resource_groups"]) == 3
    assert incomplete["complete"] is False


def test_a_failed_read_yields_no_context() -> None:
    assert _read(_Gateway([], fail=True)) is None


def test_unsafe_names_are_withheld_counted_and_mark_the_list_incomplete() -> None:
    context = {
        "kind": "resource_groups",
        "complete": True,
        "resource_groups": [
            {"name": "rg-app", "location": "koreacentral"},
            {"name": "rg-secret", "location": "koreacentral"},
        ],
    }

    safe = safe_environment_context(context, unsafe=lambda text: "secret" in text)

    assert safe == {
        "kind": "resource_groups",
        "complete": False,
        "resource_groups": [{"name": "rg-app", "location": "koreacentral"}],
        "withheld": 1,
    }
    assert safe_environment_context(None, unsafe=lambda _text: False) is None


def test_the_bound_context_is_visible_only_inside_its_turn() -> None:
    value = {"kind": "resource_groups", "complete": True, "resource_groups": []}

    with bind_environment_context(value):
        assert current_environment_context() is value
    assert current_environment_context() is None
