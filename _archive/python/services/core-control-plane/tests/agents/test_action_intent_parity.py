"""Contract test for server-owned action-intent routing."""

from __future__ import annotations

from pathlib import Path

_DECK = Path(__file__).resolve().parents[4] / "console" / "src" / "deck"


def test_client_action_intent_router_stays_removed() -> None:
    """The Web always sends prose to the server-owned semantic router."""

    assert not (_DECK / "action-intent.ts").exists()
    assert not (_DECK / "action-intent.test.ts").exists()
    submit_hook = (_DECK / "use-command-deck-submit.ts").read_text(encoding="utf-8")
    assert "detectActionIntent" not in submit_hook
    assert "submitAction(" not in submit_hook
