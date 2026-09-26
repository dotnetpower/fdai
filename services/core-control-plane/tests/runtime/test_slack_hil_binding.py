"""Core Slack A1 selection remains distinct from Teams and the persisted queue."""

from __future__ import annotations

import httpx
import pytest
from fdai.delivery.chatops.slack_adapter import SLACK_POST_URL, SlackHilAdapter
from fdai.runtime.delivery import _build_hil_channel
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
