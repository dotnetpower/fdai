"""Live restart coverage for complete PostgreSQL conversation history assembly."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.conversation.context_bridge import session_to_working_context
from fdai.core.conversation.session import ConversationSession, Principal, Role, Turn
from fdai.core.working_context.types import ContextBudget, EntryKind
from fdai.delivery.persistence import (
    PostgresConversationHistoryStore,
    PostgresUserContextStoreConfig,
)
from fdai.shared.providers import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
)

_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 8, 14, 5, tzinfo=UTC)


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    result = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_complete_history_and_latest_context_survive_store_restart() -> None:
    _upgrade()
    suffix = uuid.uuid4().hex
    principal_id = f"principal-history-{suffix}"
    conversation_id = f"conversation-history-{suffix}"
    config = PostgresUserContextStoreConfig(dsn=_dsn())
    writer = PostgresConversationHistoryStore(config=config)
    await writer.create_conversation(
        ConversationRecord(
            conversation_id=conversation_id,
            principal_id=principal_id,
            channel_id="web",
            started_at=_NOW,
            last_active=_NOW,
        )
    )
    roles = (
        ConversationTurnRole.OPERATOR,
        ConversationTurnRole.ASSISTANT,
        ConversationTurnRole.OPERATOR,
        ConversationTurnRole.ASSISTANT,
        ConversationTurnRole.OPERATOR,
    )
    expected_ids: list[str] = []
    for index, role in enumerate(roles):
        turn_id = f"turn-history-{index}-{suffix}"
        expected_ids.append(turn_id)
        await writer.append_turn(
            ConversationTurnRecord(
                turn_id=turn_id,
                conversation_id=conversation_id,
                principal_id=principal_id,
                turn_index=index,
                role=role,
                content=f"History turn {index}",
                recorded_at=_NOW + timedelta(minutes=index),
                idempotency_key=f"history-{index}-{suffix}",
            )
        )

    restarted = PostgresConversationHistoryStore(config=config)
    turns = await restarted.list_all_turns(
        principal_id=principal_id,
        conversation_id=conversation_id,
    )
    assert [turn.turn_id for turn in turns] == expected_ids
    assert (
        await restarted.list_all_turns(
            principal_id=f"other-{principal_id}",
            conversation_id=conversation_id,
        )
        == ()
    )
    assert await restarted.latest_operator_turn_ids(
        principal_id=principal_id,
        conversation_ids=(conversation_id,),
    ) == {conversation_id: expected_ids[-1]}

    session = ConversationSession(
        session_id=conversation_id,
        principal=Principal(id=principal_id, role=Role.READER),
        channel_id="web",
    )
    for turn in turns:
        session.append(
            Turn(
                turn_id=turn.turn_id,
                direction=("inbound" if turn.role is ConversationTurnRole.OPERATOR else "outbound"),
                content=turn.content,
                timestamp=turn.recorded_at,
            )
        )
    context = session_to_working_context(
        session=session,
        budget=ContextBudget(
            total_window=1_000,
            base_reserve=0,
            output_reserve=1,
            tools_reserve=0,
            memory_reserve=0,
        ),
        token_estimator=lambda _text: 1,
    )
    assert set(context.manifest.verbatim_ids) == set(expected_ids)
    assert [
        entry.entry_id for entry in context.entries if entry.kind is EntryKind.VERBATIM
    ] == expected_ids

    assert await restarted.delete_conversation(
        principal_id=principal_id,
        conversation_id=conversation_id,
    )
