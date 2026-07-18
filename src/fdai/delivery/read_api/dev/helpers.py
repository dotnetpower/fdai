"""Environment-driven helper wiring for the local read API factory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fdai.delivery.read_api.streaming.agent_activity_relay import (
    ControlLoopAgentActivityRelay,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityStreamConfig,
    SseAgentActivityPublisher,
)
from fdai.delivery.read_api.streaming.live_control_loop import (
    ControlLoopEmitterUnavailable,
    build_control_loop_emitter,
)
from fdai.delivery.read_api.streaming.live_stream import (
    LiveEmitter,
    LiveStreamConfig,
    SyntheticLiveEmitter,
)
from fdai.shared.providers.sse import SseSink
from fdai.shared.providers.testing.sse import InMemorySseSink

LOCAL_SCENARIO_REPLAY_ENV = "FDAI_LOCAL_SCENARIO_REPLAY"
LOCAL_AZURE_DISCOVERY_ENV = "FDAI_LOCAL_AZURE_DISCOVERY"
LOCAL_AZURE_SUBSCRIPTION_ENV = "FDAI_LOCAL_AZURE_SUBSCRIPTION_ID"
LOCAL_AZURE_CONFIG_DIR_ENV = "FDAI_LOCAL_AZURE_CONFIG_DIR"


def build_stewardship_map() -> Any:
    from fdai.core.stewardship import StewardshipValidationError, load_stewardship_from_yaml

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "agent-stewardship.yaml"
        if candidate.is_file():
            try:
                return load_stewardship_from_yaml(candidate)
            except (StewardshipValidationError, OSError):
                return None
    return None


def build_chat_backend(metering_sink: Any = None) -> Any:
    from fdai.delivery.read_api.routes.chat import backend_from_env

    return backend_from_env(metering_sink=metering_sink)


def build_chat_web_search() -> Any:
    from fdai.delivery.read_api.routes.chat_web_search import chat_web_search_from_env

    return chat_web_search_from_env()


def chat_probe_interval_seconds() -> int:
    raw = os.environ.get("FDAI_NARRATOR_PROBE_INTERVAL_SECONDS", "").strip()
    if not raw:
        return 300
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("FDAI_NARRATOR_PROBE_INTERVAL_SECONDS MUST be an integer") from exc
    if value < 30:
        raise ValueError("FDAI_NARRATOR_PROBE_INTERVAL_SECONDS MUST be >= 30")
    return value


def build_live_stream_config(stage_publisher_wrapper: Any = None) -> LiveStreamConfig:
    sink: SseSink = InMemorySseSink()
    channel = "aw.pipeline.stages"

    def factory(sink_arg: SseSink, channel_arg: str) -> LiveEmitter:
        try:
            return build_control_loop_emitter(
                sink_arg,
                channel_arg,
                events_per_second=3.0,
                stage_publisher_wrapper=stage_publisher_wrapper,
            )
        except ControlLoopEmitterUnavailable:
            return SyntheticLiveEmitter(
                sink=sink_arg,
                channel=channel_arg,
                events_per_second=3.0,
            )

    return LiveStreamConfig(
        path="/live/stream",
        channel=channel,
        sink=sink,
        emitter_factory=factory,
    )


def build_agent_streams() -> tuple[LiveStreamConfig, AgentActivityStreamConfig]:
    if os.environ.get(LOCAL_SCENARIO_REPLAY_ENV, "").strip() != "1":
        return (
            LiveStreamConfig(sink=InMemorySseSink()),
            AgentActivityStreamConfig(sink=InMemorySseSink()),
        )
    if os.environ.get("FDAI_AGENTS_REAL_RELAY") == "0":
        return build_live_stream_config(), AgentActivityStreamConfig()

    agent_sink: SseSink = InMemorySseSink()
    agent_publisher = SseAgentActivityPublisher(sink=agent_sink)

    def wrapper(inner: Any) -> Any:
        return ControlLoopAgentActivityRelay(publisher=agent_publisher, inner=inner)

    return (
        build_live_stream_config(stage_publisher_wrapper=wrapper),
        AgentActivityStreamConfig(sink=agent_sink),
    )


def build_inventory_graph_provider() -> Any:
    from fdai.delivery.read_api.routes.demo_inventory_graph import demo_inventory_graph_provider

    if os.environ.get(LOCAL_AZURE_DISCOVERY_ENV, "").strip() != "1":
        return demo_inventory_graph_provider
    subscription_id = os.environ.get(LOCAL_AZURE_SUBSCRIPTION_ENV, "").strip()
    if not subscription_id:
        raise ValueError(
            "FDAI_LOCAL_AZURE_SUBSCRIPTION_ID MUST be set when local Azure discovery is enabled"
        )
    from fdai.delivery.azure.dev_inventory import AzureCliInventory
    from fdai.delivery.read_api.dev.azure_inventory_graph import AzureCliInventoryGraphProvider

    config_dir = os.environ.get(LOCAL_AZURE_CONFIG_DIR_ENV, "").strip() or None
    return AzureCliInventoryGraphProvider(
        inventory=AzureCliInventory(
            subscription_id=subscription_id,
            azure_config_dir=config_dir,
        )
    )


__all__ = [
    "build_agent_streams",
    "build_chat_backend",
    "build_chat_web_search",
    "build_inventory_graph_provider",
    "build_live_stream_config",
    "build_stewardship_map",
    "chat_probe_interval_seconds",
]
