"""Coverage for the inert Python task author request boundary."""

from __future__ import annotations

import pytest
from fdai.shared.providers.python_task_author import PythonTaskAuthorRequest
from fdai.shared.providers.vm_task import PythonTaskCapability


def test_author_request_accepts_bounded_values() -> None:
    request = PythonTaskAuthorRequest(
        intent="Inspect one bounded artifact.",
        task_id_hint="inspect-artifact",
        target_capabilities=frozenset({PythonTaskCapability.FILESYSTEM_READ}),
        allowed_modules=("json",),
    )

    assert request.allowed_modules == ("json",)


@pytest.mark.parametrize(
    "overrides",
    (
        {"intent": ""},
        {"intent": "x" * 4_001},
        {"task_id_hint": ""},
        {"task_id_hint": "x" * 81},
        {"allowed_modules": tuple(f"module_{index}" for index in range(65))},
    ),
)
def test_author_request_rejects_unbounded_values(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "intent": "Inspect one bounded artifact.",
        "task_id_hint": "inspect-artifact",
        "target_capabilities": frozenset({PythonTaskCapability.FILESYSTEM_READ}),
        "allowed_modules": (),
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        PythonTaskAuthorRequest(**values)  # type: ignore[arg-type]
