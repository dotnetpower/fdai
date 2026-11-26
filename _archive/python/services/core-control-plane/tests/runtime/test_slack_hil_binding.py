"""Core Slack A1 selection remains distinct from Teams and the persisted queue."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.delivery.chatops.slack_adapter import (
    SLACK_POST_URL,
    SlackHilAdapter,
    SlackHilAdapterConfig,
)
from fdai.delivery.chatops.slack_request_outbox import DurableSlackApprovalChannel
from fdai.runtime.bootstrap_tasks import schedule_slack_request_outbox
from fdai.runtime.delivery import _build_hil_channel
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_KEYS = (
    "FDAI_SLACK_APPROVAL_API_URL",
    "FDAI_SLACK_APPROVAL_CHANNEL_ID",
    "FDAI_SLACK_APPROVAL_BOT_TOKEN",
    "FDAI_TEAMS_APPROVAL_ACTIVITY_URL",
    "FDAI_CHATOPS_WEBHOOK_URL",
)


@pytest.fixture(autouse=True)
def isolated_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def test_absent_channels_keep_the_persisted_queue() -> None:
    assert _build_hil_channel(None) is None


async def test_slack_only_requires_complete_configuration_and_shared_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_SLACK_APPROVAL_API_URL", SLACK_POST_URL)
    monkeypatch.setenv("FDAI_SLACK_APPROVAL_CHANNEL_ID", "CEXAMPLE1")
    monkeypatch.setenv("FDAI_SLACK_APPROVAL_BOT_TOKEN", "synthetic-bot-credential")
    with pytest.raises(RuntimeError, match="HTTP client"):
        _build_hil_channel(None)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        assert isinstance(_build_hil_channel(client), SlackHilAdapter)


@pytest.mark.parametrize("key", _KEYS[:3])
def test_partial_slack_config_fails_closed(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setenv(key, "configured")
    with pytest.raises(RuntimeError, match="MUST be set together"):
        _build_hil_channel(None)


def test_slack_and_teams_cannot_compete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_SLACK_APPROVAL_API_URL", SLACK_POST_URL)
    monkeypatch.setenv("FDAI_SLACK_APPROVAL_CHANNEL_ID", "CEXAMPLE1")
    monkeypatch.setenv("FDAI_SLACK_APPROVAL_BOT_TOKEN", "synthetic-bot-credential")
    monkeypatch.setenv("FDAI_TEAMS_APPROVAL_ACTIVITY_URL", "https://example.com/activities")
    with pytest.raises(RuntimeError, match="cannot be selected together"):
        _build_hil_channel(None)


def test_existing_teams_and_webhook_guards_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_CHATOPS_WEBHOOK_URL", "https://example.com/webhook")
    with pytest.raises(RuntimeError, match="Incoming Webhooks"):
        _build_hil_channel(None)
    monkeypatch.delenv("FDAI_CHATOPS_WEBHOOK_URL")
    monkeypatch.setenv("FDAI_TEAMS_APPROVAL_ACTIVITY_URL", "https://example.com/activities")
    with pytest.raises(RuntimeError, match="workload identity"):
        _build_hil_channel(None)
    identity = StaticWorkloadIdentity(
        audience="https://api.botframework.com/.default",
        token="synthetic-bot-credential",  # noqa: S106 - synthetic identity fixture
    )
    with pytest.raises(RuntimeError, match="HTTP client"):
        _build_hil_channel(None, identity)


async def test_only_slack_outbox_is_supervised_without_a_network_request() -> None:
    class Ready:
        async def run_when_ready(self, stop: asyncio.Event, runner: object) -> None:
            await runner()  # type: ignore[operator]

    stop = asyncio.Event()
    assert (
        schedule_slack_request_outbox(
            channel=object(),
            readiness=Ready(),
            stop=stop,  # type: ignore[arg-type]
        )
        is None
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("no request allowed"))
    ) as client:
        adapter = SlackHilAdapter(
            config=SlackHilAdapterConfig(
                api_url=SLACK_POST_URL, channel_id="CEXAMPLE1", bot_token="fixture"
            ),
            http_client=client,
        )
        outbox = DurableSlackApprovalChannel(adapter=adapter, store=InMemoryStateStore())
        outbox.run = AsyncMock()  # type: ignore[method-assign]
        task = schedule_slack_request_outbox(
            channel=outbox,
            readiness=Ready(),
            stop=stop,  # type: ignore[arg-type]
        )
        assert task is not None and task.get_name() == "hil-slack-outbound-request-outbox"
        await task
        outbox.run.assert_awaited_once_with(stop)  # type: ignore[attr-defined]


async def test_local_owner_only_slack_approval_activation_resolves_channel(
    tmp_path: object,
) -> None:
    from pathlib import Path

    from fdai.delivery.chatops.slack_binding import (
        LOCAL_SLACK_APPROVAL_ACTIVATION_ENV,
        build_slack_hil_channel,
        resolve_local_slack_approval_environment,
    )

    fdai_dir = Path(str(tmp_path)) / ".fdai"
    fdai_dir.mkdir(mode=0o700)
    input_env = fdai_dir / "local-channel-edge-input.env"
    input_env.write_text("FDAI_SLACK_BOT_TOKEN='fixture'\n", encoding="utf-8")
    input_env.chmod(0o600)
    channel_file = fdai_dir / "slack-public-channel"
    channel_file.write_text("C012345678\n", encoding="utf-8")
    channel_file.chmod(0o600)

    inactive = resolve_local_slack_approval_environment({}, fdai_dir=fdai_dir)
    assert "FDAI_SLACK_APPROVAL_BOT_TOKEN" not in inactive

    active = resolve_local_slack_approval_environment(
        {LOCAL_SLACK_APPROVAL_ACTIVATION_ENV: "1"},
        fdai_dir=fdai_dir,
    )
    assert active["FDAI_SLACK_APPROVAL_API_URL"] == SLACK_POST_URL
    assert active["FDAI_SLACK_APPROVAL_CHANNEL_ID"] == "C012345678"
    assert active["FDAI_SLACK_APPROVAL_BOT_TOKEN"] == "fixture"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        channel = build_slack_hil_channel(
            {LOCAL_SLACK_APPROVAL_ACTIVATION_ENV: "1"},
            http_client=client,
            teams_configured=False,
            fdai_dir=fdai_dir,
        )
        assert isinstance(channel, SlackHilAdapter)

    # Group-readable files must fail closed and resolve nothing.
    input_env.chmod(0o640)
    insecure = resolve_local_slack_approval_environment(
        {LOCAL_SLACK_APPROVAL_ACTIVATION_ENV: "1"},
        fdai_dir=fdai_dir,
    )
    assert "FDAI_SLACK_APPROVAL_BOT_TOKEN" not in insecure
