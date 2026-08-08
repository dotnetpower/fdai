"""PostgreSQL cross-channel identity link persistence tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.conversation import ChannelSenderKey, CrossChannelIdentityLink
from fdai.delivery.persistence import (
    PostgresChannelIdentityLinkStore,
    PostgresChannelIdentityLinkStoreConfig,
)
from fdai.shared.providers.conversation_channel import ConversationChannelKind

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_config_rejects_empty_dsn_or_bad_timeout() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresChannelIdentityLinkStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresChannelIdentityLinkStoreConfig(dsn="postgresql://x", connect_timeout_s=0)


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_link_is_idempotent_and_restart_persistent() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex[:8]
    link = CrossChannelIdentityLink(
        link_id=f"channel-link:{suffix}",
        principal_id=f"operator-{suffix}",
        first=ChannelSenderKey(ConversationChannelKind.SLACK, "slack-channel", suffix),
        second=ChannelSenderKey(ConversationChannelKind.TEAMS, "teams-channel", suffix),
        approved_by="owner-example",
        created_at=datetime(2026, 7, 17, 6, 0, tzinfo=UTC),
    )
    config = PostgresChannelIdentityLinkStoreConfig(dsn=dsn)
    store = PostgresChannelIdentityLinkStore(config=config)

    assert await store.create(link) is True
    assert await store.create(link) is False

    restarted = PostgresChannelIdentityLinkStore(config=config)
    assert await restarted.get(link.link_id) == link
    assert await restarted.list_for_principal(link.principal_id) == (link,)
