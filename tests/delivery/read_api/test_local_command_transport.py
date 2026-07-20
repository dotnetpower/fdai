"""Interactive local command transport configuration."""

from __future__ import annotations

import pytest

from fdai.delivery.read_api.dev.command_transport import build_local_command_transport
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel


def test_transport_is_absent_without_explicit_azure_configuration() -> None:
    assert (
        build_local_command_transport(
            read_model=InMemoryConsoleReadModel(),
            action_types=(),
            environ={},
        )
        is None
    )


@pytest.mark.parametrize(
    "environ",
    [
        {"FDAI_KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093"},
        {"KAFKA_TOPIC_EVENTS": "fdai.events"},
    ],
)
def test_partial_transport_configuration_fails_fast(environ: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="MUST be configured together"):
        build_local_command_transport(
            read_model=InMemoryConsoleReadModel(),
            action_types=(),
            environ=environ,
        )


def test_configured_transport_uses_real_broadcasters_without_connecting_eagerly() -> None:
    wiring = build_local_command_transport(
        read_model=InMemoryConsoleReadModel(),
        action_types=(),
        environ={
            "FDAI_KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
            "KAFKA_TOPIC_EVENTS": "fdai.events",
            "FDAI_STAGE_TOPIC": "fdai.stage-events",
        },
    )

    assert wiring is not None
    assert wiring.live_stream.broadcaster_factory is not None
    assert wiring.live_stream.emitter_factory is None
    assert wiring.agent_activity.broadcaster_factory is not None
