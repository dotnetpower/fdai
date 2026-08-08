"""PostgreSQL channel pairing persistence and concurrency tests."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.conversation import ChannelSenderKey, PairingCreateResult, PairingRequest
from fdai.delivery.persistence import (
    PostgresChannelPairingStore,
    PostgresChannelPairingStoreConfig,
)
from fdai.shared.providers.conversation_channel import ConversationChannelKind

REPO_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)


def test_config_rejects_empty_dsn_or_bad_timeout() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresChannelPairingStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresChannelPairingStoreConfig(dsn="postgresql://x", connect_timeout_s=0)


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


def _request(sender_id: str) -> PairingRequest:
    return PairingRequest(
        sender=ChannelSenderKey(
            ConversationChannelKind.SLACK,
            f"channel-{uuid.uuid4().hex[:8]}",
            sender_id,
        ),
        code_digest=hashlib.sha256(b"ABC123").hexdigest(),
        created_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
    )


@pytest.mark.integration
async def test_pending_cap_approval_and_restart_persist() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    store = PostgresChannelPairingStore(config=PostgresChannelPairingStoreConfig(dsn=dsn))
    first = _request(f"sender-{uuid.uuid4().hex[:8]}")
    second = _request(f"sender-{uuid.uuid4().hex[:8]}")

    results = await asyncio.gather(
        store.create_pending(first, max_pending=1),
        store.create_pending(second, max_pending=1),
    )

    assert sorted(results) == sorted([PairingCreateResult.CREATED, PairingCreateResult.CAP_REACHED])
    created = first if results[0] is PairingCreateResult.CREATED else second
    approved = await store.approve_pending(
        created.sender,
        code_digest=created.code_digest,
        principal_id="operator-example",
        at=_NOW + timedelta(minutes=1),
    )
    assert approved is not None and approved.approved

    restarted = PostgresChannelPairingStore(config=PostgresChannelPairingStoreConfig(dsn=dsn))
    persisted = await restarted.get(created.sender)
    assert persisted is not None and persisted.approved_principal_id == "operator-example"
    assert (
        await restarted.create_pending(created, max_pending=1)
        is PairingCreateResult.ALREADY_APPROVED
    )
