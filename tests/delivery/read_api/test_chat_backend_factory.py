from __future__ import annotations

import pytest

from fdai.delivery.read_api.routes.chat_backend_factory import (
    _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS,
    _narrator_turn_timeout_seconds,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (None, _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("invalid", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("0", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("301", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("45", 45.0),
        ("1.5", 1.5),
    ),
)
def test_narrator_turn_timeout_is_bounded(raw: str | None, expected: float) -> None:
    env = {} if raw is None else {"FDAI_NARRATOR_TURN_TIMEOUT_SECONDS": raw}

    assert _narrator_turn_timeout_seconds(env) == expected
