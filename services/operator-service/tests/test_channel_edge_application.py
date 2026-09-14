"""Factory and entry-point tests for the standalone Operator channel edge."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.application import create_app
from fdai_operator_service.families.conversation.channel_edge.composition import (
    ProductionChannelEdgeComposition,
)
from fdai_operator_service.families.conversation.channel_edge.entry import serve
from fdai_operator_service.families.conversation.channel_edge.environment import (
    ChannelEdgeConfigurationError,
)
from fdai_operator_service.families.conversation.channel_edge.slack_ingress import (
    SlackIngressAction,
)


class _Runtime:
    max_body_bytes = 32
    enabled_channels = frozenset({ChannelKind.SLACK})
    ready = True

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def accept_slack(
        self,
        *,
        body: bytes,
        headers: object,
        received_at: datetime,
    ) -> tuple[SlackIngressAction, str | None]:
        del body, headers, received_at
        return SlackIngressAction.ACCEPTED, None

    async def accept_teams(self, **_kwargs: object) -> None:
        raise AssertionError("Teams is disabled")


class _Composition:
    def __init__(self) -> None:
        self.environ: Mapping[str, str] | None = None

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> _Runtime:
        self.environ = environ
        return _Runtime()


def _environment() -> dict[str, str]:
    return {
        "FDAI_EXECUTION_VENUE": "local",
        "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS": "slack",
        "FDAI_DATABASE_URL": "postgresql://operator@example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_operator",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.semantic-turn.requests",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "core.semantic-turn.projections",
        "FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON": (
            '{"principal-example":{"scope_ref":"scope://example","roles":["Reader"]}}'
        ),
        "FDAI_SLACK_SIGNING_SECRET": "test-signing-secret",
        "FDAI_SLACK_BOT_TOKEN": "test-bot-token",
        "FDAI_SLACK_TEAM_ID": "team-example",
        "FDAI_SLACK_PRINCIPAL_MAP_JSON": '{"sender-example":"principal-example"}',
    }


def test_application_factory_passes_explicit_environment_to_composition() -> None:
    composition = _Composition()
    environment = _environment()

    app = create_app(environment, composition=composition)

    assert composition.environ is environment
    paths = {route.path for route in app.routes}
    assert "/webhooks/slack/events" in paths
    assert "/webhooks/teams/activities" not in paths


def test_entry_validates_environment_and_uses_dedicated_listener() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def runner(reference: str, **kwargs: object) -> object:
        calls.append((reference, kwargs))
        return None

    environment = _environment()
    environment["FDAI_CHANNEL_EDGE_HOST"] = "127.0.0.1"
    environment["FDAI_CHANNEL_EDGE_PORT"] = "8014"

    assert serve(environment, runner=runner) == 0
    assert calls == [
        (
            "fdai_operator_service.families.conversation.channel_edge.application:create_app",
            {"factory": True, "host": "127.0.0.1", "port": 8014},
        )
    ]


async def test_production_composition_builds_and_closes_local_slack_edge() -> None:
    runtime = ProductionChannelEdgeComposition().build_runtime(_environment())

    assert runtime.enabled_channels == {ChannelKind.SLACK}
    assert runtime.ready is False
    await runtime.aclose()


def test_production_composition_rejects_incomplete_attachments_before_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment()
    environment["FDAI_CHANNEL_ATTACHMENTS_ENABLED"] = "1"

    def reject_allocation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("HTTP client allocated before attachment binding validation")

    monkeypatch.setattr(
        "fdai_operator_service.families.conversation.channel_edge.composition.httpx.AsyncClient",
        reject_allocation,
    )

    with pytest.raises(ChannelEdgeConfigurationError, match="SCRATCH_ENCRYPTED"):
        ProductionChannelEdgeComposition().build_runtime(environment)


async def test_production_composition_binds_complete_local_attachment_ingestor(
    tmp_path: Path,
) -> None:
    environment = _environment()
    environment.update(
        {
            "FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1",
            "FDAI_CHANNEL_ATTACHMENT_INTAKE_ORIGIN": "http://127.0.0.1:8015",
            "FDAI_CHANNEL_ATTACHMENT_INTAKE_AUDIENCE": "api://document-ingestion",
            "FDAI_CHANNEL_ATTACHMENT_CLIENT_ID": "channel-edge-attachment-client",
            "FDAI_CHANNEL_ATTACHMENT_TENANT_ID": "tenant-example",
            "FDAI_CHANNEL_ATTACHMENT_CLIENT_SECRET": "test-client-secret",
            "FDAI_CHANNEL_ATTACHMENT_SCRATCH_DIR": str(tmp_path),
            "FDAI_CHANNEL_ATTACHMENT_SCRATCH_ENCRYPTED": "1",
            "FDAI_SLACK_FILES_INFO_URL": "https://slack.com/api/files.info",
            "FDAI_SLACK_ATTACHMENT_METADATA_HOSTS_JSON": '["slack.com"]',
            "FDAI_SLACK_ATTACHMENT_DOWNLOAD_HOSTS_JSON": '["files.slack.com"]',
        }
    )

    runtime = ProductionChannelEdgeComposition().build_runtime(environment)

    assert runtime._pipeline._attachment_ingestor is not None
    assert runtime._pipeline._attachment_ingestor._max_content_bytes == 25 * 1024 * 1024
    assert any(
        getattr(check, "__name__", "") == "probe_readiness" for check in runtime._readiness_checks
    )
    await runtime.aclose()
