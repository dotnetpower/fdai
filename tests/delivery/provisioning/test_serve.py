"""Tests for :mod:`fdai.delivery.provisioning.serve`.

The pump is the missing link that drives the pure bridge from a line source
and publishes onto a :class:`ProvisionPublisher`. Tests use an in-memory
collecting publisher and assert ordering + the clean-EOF finalize contract.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from fdai.delivery.provisioning.serve import aiter_json_lines, pump_provision_events
from fdai.delivery.read_api.streaming.provision_stream import (
    DEFAULT_CHANNEL,
    ProvisionEvent,
    ProvisionPhase,
    SseProvisionPublisher,
)
from fdai.shared.providers.testing.sse import InMemorySseSink


class _Collector:
    """A :class:`ProvisionPublisher` that records what it is asked to emit."""

    def __init__(self) -> None:
        self.events: list[ProvisionEvent] = []

    async def emit(self, event: ProvisionEvent) -> None:
        self.events.append(event)


async def _alines(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


def _apply_complete(addr: str) -> str:
    return json.dumps(
        {"type": "apply_complete", "hook": {"resource": {"addr": addr}, "action": "create"}}
    )


def _plan(add: int) -> str:
    return json.dumps({"type": "change_summary", "changes": {"add": add, "operation": "plan"}})


def _apply_summary(add: int) -> str:
    return json.dumps({"type": "change_summary", "changes": {"add": add, "operation": "apply"}})


def _outputs(url: str) -> str:
    return json.dumps({"type": "outputs", "outputs": {"console_url": {"value": url}}})


class TestPumpProvisionEvents:
    async def test_publishes_ordered_events_and_finalizes_done(self) -> None:
        pub = _Collector()
        await pump_provision_events(
            _alines(
                _plan(2),
                _apply_complete("a"),
                _apply_complete("b"),
                _apply_summary(2),  # apply change_summary BEFORE outputs
                _outputs("https://c.example.com"),
            ),
            pub,
        )
        phases = [e.phase for e in pub.events]
        assert phases == [
            ProvisionPhase.PROGRESS,
            ProvisionPhase.PROGRESS,
            ProvisionPhase.DONE,
        ]
        assert pub.events[-1].console_url == "https://c.example.com"
        assert pub.events[-1].fraction == 1.0

    async def test_finalize_flushes_done_without_outputs(self) -> None:
        pub = _Collector()
        await pump_provision_events(_alines(_apply_summary(1)), pub)
        # Deferred done is flushed by the clean-EOF finalize.
        assert [e.phase for e in pub.events] == [ProvisionPhase.DONE]
        assert pub.events[-1].console_url is None

    async def test_errored_source_does_not_fake_done(self) -> None:
        pub = _Collector()

        async def _boom() -> AsyncIterator[str]:
            yield _apply_summary(1)  # apply finished but done deferred
            raise RuntimeError("terraform crashed")

        with pytest.raises(RuntimeError, match="terraform crashed"):
            await pump_provision_events(_boom(), pub)
        # finalize is skipped on an errored source: no fake provision.done.
        assert pub.events == []

    async def test_empty_stream_emits_nothing(self) -> None:
        pub = _Collector()
        await pump_provision_events(_alines(), pub)
        assert pub.events == []


async def _achunks(*chunks: str | bytes) -> AsyncIterator[str | bytes]:
    for chunk in chunks:
        yield chunk


async def _collect(it: AsyncIterator[str]) -> list[str]:
    return [line async for line in it]


class TestAiterJsonLines:
    async def test_reassembles_line_split_across_chunks(self) -> None:
        lines = await _collect(aiter_json_lines(_achunks('{"ty', 'pe":"x"}\n')))
        assert lines == ['{"type":"x"}']

    async def test_multiple_lines_in_one_chunk(self) -> None:
        lines = await _collect(aiter_json_lines(_achunks("a\nb\nc\n")))
        assert lines == ["a", "b", "c"]

    async def test_crlf_stripped(self) -> None:
        lines = await _collect(aiter_json_lines(_achunks("a\r\nb\r\n")))
        assert lines == ["a", "b"]

    async def test_trailing_unterminated_line_flushed(self) -> None:
        lines = await _collect(aiter_json_lines(_achunks("a\nb")))  # no final newline
        assert lines == ["a", "b"]

    async def test_bytes_decoded(self) -> None:
        lines = await _collect(aiter_json_lines(_achunks(b'{"type":"x"}\n')))
        assert lines == ['{"type":"x"}']

    async def test_multibyte_utf8_split_across_chunks(self) -> None:
        # A single non-ASCII codepoint whose UTF-8 encoding is split mid-byte
        # by the chunk boundary must not crash the pump. Realistic terraform
        # output escapes non-ASCII to \\uXXXX, but a stray byte-boundary from
        # an operator's locale or an unusual producer must degrade gracefully.
        # U+00E9 (e-acute) encodes to b"\xc3\xa9".
        chunks = _achunks(b'{"n":"caf\xc3', b'\xa9"}\n')
        lines = await _collect(aiter_json_lines(chunks))
        assert lines == ['{"n":"caf\u00e9"}']

    async def test_multibyte_utf8_split_three_ways(self) -> None:
        # A 4-byte codepoint split across three chunks (2 + 1 + 1 boundary
        # variants) still reassembles correctly. U+1F600 = b"\xf0\x9f\x98\x80".
        chunks = _achunks(b'"', b"\xf0\x9f", b"\x98", b'\x80"\n')
        lines = await _collect(aiter_json_lines(chunks))
        assert lines == ['"\U0001f600"']


class TestEndToEnd:
    async def test_chunks_flow_to_sse_subscriber(self) -> None:
        # Full surface-A path: chunked bytes -> aiter_json_lines -> pump ->
        # SseProvisionPublisher -> InMemorySseSink -> a subscribed console.
        import asyncio

        sink = InMemorySseSink()
        publisher = SseProvisionPublisher(sink=sink, channel=DEFAULT_CHANNEL)
        received: list[dict[str, object]] = []

        async def _subscriber() -> None:
            async for event in sink.subscribe(DEFAULT_CHANNEL):
                received.append(json.loads(event.data))
                if received[-1].get("type") == "provision.done":
                    break

        task = asyncio.create_task(_subscriber())
        await asyncio.sleep(0)  # let the subscriber attach before publishing

        raw = (
            _plan(1).encode()
            + b"\n"
            + _apply_complete("a").encode()
            + b"\n"
            + _apply_summary(1).encode()
            + b"\n"
            + _outputs("https://c.example.com").encode()
            + b"\n"
        )
        # Deliberately split the byte stream mid-record to exercise reassembly.
        chunks = [raw[:20], raw[20:55], raw[55:]]
        await pump_provision_events(aiter_json_lines(_achunks(*chunks)), publisher)

        await asyncio.wait_for(task, timeout=1.0)
        types = [e["type"] for e in received]
        assert types == ["provision.progress", "provision.done"]
        assert received[-1]["console_url"] == "https://c.example.com"
