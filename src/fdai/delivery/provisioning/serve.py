"""Serve harness for surface A - drive ``provision.*`` from Terraform output.

The pure :class:`~fdai.delivery.provisioning.terraform_bridge.TerraformProvisionBridge`
folds ``terraform apply -json`` lines into ``provision.*`` events, and
:class:`~fdai.delivery.read_api.streaming.provision_stream.SseProvisionPublisher` fans
them out - but nothing connected the two. The "thin serve harness" the bridge
docstring refers to did not exist, leaving the bridge (and its ``finalize``)
unreachable. This module is that harness.

It is deliberately I/O-agnostic: the caller supplies an async iterable of
already-split lines (subprocess stdout via :func:`aiter_json_lines`, a file, a
socket) and a :class:`~fdai.delivery.read_api.streaming.provision_stream.ProvisionPublisher`.
The pump owns only fold + publish + a single clean-EOF finalize, so it stays
unit-testable and spawns no subprocess itself - subprocess ownership stays
with the bootstrap caller, never the core.
"""

from __future__ import annotations

import codecs
from collections.abc import AsyncIterable, AsyncIterator

from fdai.delivery.provisioning.terraform_bridge import TerraformProvisionBridge
from fdai.delivery.read_api.streaming.provision_stream import ProvisionPublisher


async def aiter_json_lines(
    chunks: AsyncIterable[str | bytes],
    *,
    encoding: str = "utf-8",
) -> AsyncIterator[str]:
    """Reassemble a chunked byte/str stream into complete text lines.

    Subprocess stdout arrives in arbitrary chunks that can split a JSON object
    or a multi-byte UTF-8 sequence across a boundary, but the bridge needs
    exactly one JSON object per line. A single :mod:`codecs` incremental
    decoder is threaded across all byte chunks so a boundary that lands
    mid-codepoint does not raise ``UnicodeDecodeError`` and corrupt the pump;
    the trailing partial codepoint is buffered until the next chunk. This
    buffers partial lines, splits on ``\\n`` (tolerating ``\\r\\n``), and
    flushes a final unterminated line at end-of-stream. Blank lines are
    yielded as-is - the bridge skips them - so no content is silently dropped.
    """
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    buffer = ""
    async for chunk in chunks:
        buffer += decoder.decode(chunk) if isinstance(chunk, bytes) else chunk
        newline = buffer.find("\n")
        while newline != -1:
            yield buffer[:newline].rstrip("\r")
            buffer = buffer[newline + 1 :]
            newline = buffer.find("\n")
    # Flush any bytes still pending in the incremental decoder (final=True
    # raises on an incomplete sequence, exposing truncated stdout instead of
    # silently swallowing bytes).
    buffer += decoder.decode(b"", final=True)
    if buffer:
        yield buffer.rstrip("\r")


async def pump_provision_events(
    lines: AsyncIterable[str],
    publisher: ProvisionPublisher,
    *,
    bridge: TerraformProvisionBridge | None = None,
) -> None:
    """Fold ``lines`` through ``bridge`` and publish each event in order.

    ``finalize`` runs only after the line source ends cleanly, so a cancelled
    or errored apply propagates before it and is never papered over with a
    fake ``provision.done``. Every event a line produces is published before
    the next line is read, preserving order.
    """
    active = bridge if bridge is not None else TerraformProvisionBridge()
    async for line in lines:
        for event in active.feed(line):
            await publisher.emit(event)
    for event in active.finalize():
        await publisher.emit(event)


__all__ = ["aiter_json_lines", "pump_provision_events"]
