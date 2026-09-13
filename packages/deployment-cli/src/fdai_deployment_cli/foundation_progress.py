"""Adapt known Genesis presentation records without deriving execution authority."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

CHECKPOINT_LABELS = (
    "Toolchain prerequisites",
    "Azure target verification",
    "Source and required CI",
    "Azure resource providers",
    "Tenant policy route",
    "Deployment route selection",
    "Runner image exact plan",
    "Runner image exact apply",
    "Foundation exact plan",
    "Foundation exact apply",
    "Runner enrollment and attestation",
    "Foundation private state handoff",
    "Protected application exact plan",
    "Protected application exact apply",
    "Post-deployment verification",
)
_TOTAL = len(CHECKPOINT_LABELS)
_MAX_LINE = 512
_CHUNK_SIZE = 4096
_RECORD = re.compile(
    r"\[([#.]{24})\] +([0-9]{1,3})%  done ([0-9]{1,2})/15 \| "
    r"stage ([0-9]{1,2})/15 ([^\r\n]{1,80}) - "
    r"(RUNNING|WAITING|BLOCKED|FAILED|COMPLETE) \| "
    r"skipped ([0-9]{1,2}) \| remaining ([0-9]{1,2})"
)


@dataclass(frozen=True)
class FoundationCheckpoint:
    """A checked display record, never a status receipt or approval."""

    number: int
    label: str
    state: str
    completed: int
    skipped: int
    total: int = _TOTAL


def _prefix(completed: int) -> str:
    filled = 24 * completed // _TOTAL
    return (
        f"[{'#' * filled}{'.' * (24 - filled)}] {completed * 100 // _TOTAL:3d}%  "
        f"done {completed}/{_TOTAL} | stage "
    )


_PREFIXES = tuple(_prefix(count) for count in range(_TOTAL + 1))


def parse_checkpoint(line: str) -> FoundationCheckpoint | None:
    """Accept only the producer's exact labels, arithmetic, bar, and field layout."""
    match = _RECORD.fullmatch(line)
    if match is None:
        return None
    _bar, _percent, count, number, label, state, skipped, remaining = match.groups()
    completed, index, omitted = int(count), int(number), int(skipped)
    if (
        not 0 <= omitted <= completed <= _TOTAL
        or not 1 <= index <= _TOTAL
        or label != CHECKPOINT_LABELS[index - 1]
        or int(remaining) != _TOTAL - completed
    ):
        return None
    expected = (
        f"{_prefix(completed)}{index}/{_TOTAL} {label} - {state} | "
        f"skipped {omitted} | remaining {_TOTAL - completed}"
    )
    if line != expected:
        return None
    return FoundationCheckpoint(index, label, state, completed, omitted)


def _intro(mode: str) -> str:
    return (
        f"FDAI Azure Genesis\nMode: {mode}; prompts: none\nProcedure:\n"
        + "".join(f"  {index}. {label}\n" for index, label in enumerate(CHECKPOINT_LABELS, 1))
        + "Routes: public-dev -> preview and exact-plan wait; "
        "private-runner -> image, Foundation, enrollment, and state checkpoints\n"
        "Safety: no route fallback, unsealed apply, or readiness claim\n"
    )


_INTROS = tuple(
    (mode, _intro(mode)) for mode in ("mutation-enabled preflight", "read-only inspection")
)


class FoundationProgressStream:
    """Compact known renderer output; pass all other text through without waiting for EOF.

    The compatibility adapter activates only after the complete fixed Genesis introduction.
    Unknown versions and malformed records remain native diagnostics. No record advances the
    coordinator state machine, writes status, or grants approval.
    """

    def __init__(
        self,
        *,
        output: Callable[[str], None],
        checkpoint: Callable[[FoundationCheckpoint], None],
        heartbeat: Callable[[], None],
        mode: Callable[[str], None],
    ) -> None:
        self._output = output
        self._checkpoint = checkpoint
        self._heartbeat = heartbeat
        self._mode = mode
        self._intro_buffer = ""
        self._pending = ""
        self._started = False
        self._native_only = False
        self._native_line = False

    def feed(self, text: str) -> None:
        """Consume bounded pieces, promptly forwarding an unknown unterminated diagnostic."""
        for offset in range(0, len(text), _CHUNK_SIZE):
            self._feed(text[offset : offset + _CHUNK_SIZE])

    def _feed(self, text: str) -> None:
        if self._native_only:
            self._output(text)
            return
        if not self._started:
            self._intro_buffer += text
            for mode, introduction in _INTROS:
                if self._intro_buffer.startswith(introduction):
                    text = self._intro_buffer[len(introduction) :]
                    self._intro_buffer = ""
                    self._started = True
                    self._mode(mode)
                    break
            else:
                if any(introduction.startswith(self._intro_buffer) for _, introduction in _INTROS):
                    return
                self._native_only = True
                self._output(self._intro_buffer)
                self._intro_buffer = ""
                return
        self._body(text)

    def _body(self, text: str) -> None:
        while text:
            part, newline, text = text.partition("\n")
            if self._native_line:
                self._output(part + newline)
                self._native_line = not bool(newline)
                continue
            self._pending += part
            if newline:
                line, self._pending = self._pending, ""
                candidate = line.lstrip(".")
                if not candidate and line:
                    self._heartbeat()
                elif (record := parse_checkpoint(candidate)) is not None:
                    self._checkpoint(record)
                else:
                    self._output(line + newline)
                continue
            candidate = self._pending.lstrip(".")
            possible = not candidate or any(
                prefix.startswith(candidate) or candidate.startswith(prefix) for prefix in _PREFIXES
            )
            if possible and len(self._pending) <= _MAX_LINE:
                if not candidate and self._pending:
                    self._heartbeat()
                return
            self._output(self._pending)
            self._pending = ""
            self._native_line = True

    def finish(self) -> None:
        """Preserve incomplete records; heartbeat dots alone never imply completion."""
        if self._intro_buffer:
            self._output(self._intro_buffer)
            self._intro_buffer = ""
        if self._pending:
            if self._pending.strip("."):
                self._output(self._pending)
            else:
                self._heartbeat()
            self._pending = ""
