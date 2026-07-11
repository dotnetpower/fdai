"""Serve harness for surface A - drive ``provision.*`` from Terraform output.

The pure :class:`~fdai.delivery.provisioning.terraform_bridge.TerraformProvisionBridge`
folds ``terraform apply -json`` lines into ``provision.*`` events, and
:class:`~fdai.delivery.read_api.provision_stream.SseProvisionPublisher` fans
them out - but nothing connected the two. The "thin serve harness" the bridge
docstring refers to did not exist, leaving the bridge (and its ``finalize``)
unreachable. This module is that harness.

It is deliberately I/O-agnostic: the caller supplies an async iterable of
already-split lines (subprocess stdout via :func:`aiter_json_lines`, a file, a
socket) and a :class:`~fdai.delivery.read_api.provision_stream.ProvisionPublisher`.
The pump owns only fold + publish + a single clean-EOF finalize, so it stays
unit-testable and spawns no subprocess itself - subprocess ownership stays
with the bootstrap caller, never the core.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator

from fdai.delivery.provisioning.terraform_bridge import TerraformProvisionBridge
from fdai.delivery.read_api.provision_stream import ProvisionPublisher


async def aiter_json_lines(
    chunks: AsyncIterable[str | bytes],
    *,
    encoding: str = "utf-8",
) -> AsyncIterator[str]:
    """Reassemble a chunked byte/str stream into complete text lines.

    Subprocess stdout arrives in arbitrary chunks that can split a JSON object
    across a boundary, but the bridge needs exactly one JSON object per line.
    This buffers partial lines, splits on ``\\n`` (tolerating ``\\r\\n``), and
    flushes a final unterminated line at end-of-stream. Blank lines are yielded
    as-is - the bridge skips them - so no content is silently dropped.
    """
    buffer = ""
    async for chunk in chunks:
        buffer += chunk.decode(encoding) if isinstance(chunk, bytes) else chunk
        newline = buffer.find("\n")
        while newline != -1:
            yield buffer[:newline].rstrip("\r")
            buffer = buffer[newline + 1 :]
            newline = buffer.find("\n")
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
