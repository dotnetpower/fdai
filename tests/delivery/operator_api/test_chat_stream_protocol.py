"""Focused bounds for the Operator API chat SSE serializer."""

from __future__ import annotations

import json

import pytest

from fdai.delivery.operator_api.routes.chat_stream_protocol import _sse


def test_chat_sse_frame_stays_within_browser_limit() -> None:
    frame = _sse("done", {"answer": "bounded"})

    assert len(frame) <= 256 * 1024
    assert json.loads(frame.split(b"data: ", 1)[1]) == {"answer": "bounded"}


def test_chat_sse_frame_rejects_payload_above_browser_limit() -> None:
    with pytest.raises(ValueError, match="256 KiB"):
        _sse("done", {"answer": "x" * (256 * 1024)})
