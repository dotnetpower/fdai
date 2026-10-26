"""Result-handle wiring: follow-up context is on only when a venue opts in."""

from __future__ import annotations

import pytest
from fdai.delivery.persistence.postgres_result_handle_store import PostgresResultHandleStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.semantic_result_handle_config import (
    RESULT_HANDLE_MATERIAL_ENV,
    RESULT_HANDLES_ENV,
    result_handle_store_from_config,
)
from fdai_core_service.semantic_turn_consumer import (
    build_semantic_turn_processor,
    semantic_turn_binding_from_config,
)

_TOPICS = {
    "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request",
    "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "operator.projection",
}
_DSN = "postgresql://local.invalid/state"
_MATERIAL = "00" * 32


def test_result_handles_stay_off_without_the_venue_opt_in() -> None:
    assert result_handle_store_from_config({}) is None
    assert result_handle_store_from_config({RESULT_HANDLES_ENV: "0"}) is None
    processor = build_semantic_turn_processor(state_store=InMemoryStateStore(), runtime=None)
    assert processor._result_handles_enabled is False
    assert processor._result_handle_store is None


def test_opting_in_builds_the_encrypted_store_and_enables_follow_up_binding() -> None:
    config = {
        RESULT_HANDLES_ENV: "1",
        "FDAI_STATE_STORE_DSN": _DSN,
        RESULT_HANDLE_MATERIAL_ENV: _MATERIAL,
    }

    assert isinstance(result_handle_store_from_config(config), PostgresResultHandleStore)
    binding = semantic_turn_binding_from_config(
        state_store=InMemoryStateStore(), runtime=None, config={**_TOPICS, **config}
    )
    assert binding is not None
    assert binding.processor._result_handles_enabled is True
    assert isinstance(binding.processor._result_handle_store, PostgresResultHandleStore)


@pytest.mark.parametrize(
    "config",
    [
        {RESULT_HANDLES_ENV: "1", RESULT_HANDLE_MATERIAL_ENV: _MATERIAL},
        {RESULT_HANDLES_ENV: "1", "FDAI_STATE_STORE_DSN": _DSN},
    ],
)
def test_opting_in_without_state_or_key_material_stays_off_and_says_so(
    config: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        assert result_handle_store_from_config(config) is None

    # An environment default must never stop Core from starting.
    assert "semantic_result_handles_unavailable" in caplog.text


def test_the_typed_setting_decides_over_the_environment_flag() -> None:
    config = {"FDAI_STATE_STORE_DSN": _DSN, RESULT_HANDLE_MATERIAL_ENV: _MATERIAL}

    assert isinstance(
        result_handle_store_from_config(config, enabled=True), PostgresResultHandleStore
    )
    assert (
        result_handle_store_from_config({**config, RESULT_HANDLES_ENV: "1"}, enabled=False) is None
    )
    binding = semantic_turn_binding_from_config(
        state_store=InMemoryStateStore(),
        runtime=None,
        config={**_TOPICS, **config},
        result_handles_enabled=True,
    )
    assert binding is not None and binding.processor._result_handles_enabled is True
