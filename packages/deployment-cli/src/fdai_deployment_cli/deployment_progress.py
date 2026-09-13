"""Presentation-only activity stream for the local standalone deployment coordinator.

The context-local display never writes operational evidence or grants authority. Callers advance
phases only after their existing checks pass, and explicitly confirm the final ready result.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Self

from rich.console import Console, Group
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from fdai_deployment_cli.foundation_progress import FoundationCheckpoint

StageName = Literal[
    "azure",
    "kit",
    "discovery",
    "foundation",
    "identity",
    "transfer",
    "substrate",
    "images",
    "capability",
    "migration",
    "application",
    "verification",
    "cleanup",
]
_STAGES: tuple[tuple[StageName, str], ...] = (
    ("azure", "Azure sign-in"),
    ("kit", "Signed deployment kit"),
    ("discovery", "Foundation discovery"),
    ("foundation", "Foundation checkpoints"),
    ("identity", "Application identity"),
    ("transfer", "Managed-host transfer"),
    ("substrate", "Private infrastructure"),
    ("images", "Runtime images"),
    ("capability", "Capability mode"),
    ("migration", "Database and catalogs"),
    ("application", "Application deployment"),
    ("verification", "Health and zero-change plan"),
    ("cleanup", "Cleanup and final receipt"),
)
_STATES = {
    "pending": ("--", "dim"),
    "running": ("RUN", "cyan"),
    "waiting": ("WAIT", "yellow"),
    "done": ("OK", "green"),
    "failed": ("FAIL", "red"),
    "interrupted": ("STOP", "yellow"),
    "incomplete": ("HOLD", "yellow"),
}
_CURRENT: ContextVar[DeploymentProgress | None] = ContextVar("deployment_progress", default=None)


@dataclass
class _Phase:
    label: str
    state: str = "pending"
    started: float | None = None
    ended: float | None = None


class DeploymentProgress:
    """Stream colored phase events and refresh only current work on stderr.

    Suspend redraw before native details or an approval prompt owns the terminal. Events remain
    in scrollback; redraw never replays them. Errors propagate unchanged, without retries or
    inferred operational success. Plain output contains no terminal control sequences.
    """

    def __init__(
        self,
        *,
        mode: str = "auto",
        console: Console | None = None,
        clock: Callable[[], float] = time.monotonic,
        auto_refresh: bool = True,
    ) -> None:
        if mode not in {"auto", "plain", "off"}:
            raise ValueError("deployment progress mode must be auto, plain, or off")
        self.console = console or Console(
            stderr=True, force_terminal=sys.stderr.isatty(), markup=False, highlight=False
        )
        self.enabled = mode != "off"
        self.dynamic = (
            mode == "auto"
            and self.console.is_terminal
            and os.environ.get("TERM") != "dumb"
            and "NO_COLOR" not in os.environ
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._phases = {name: _Phase(label) for name, label in _STAGES}
        self._active: StageName | None = None
        self._detail = "Preparing the local coordinator"
        self._headline = "Deployment in progress"
        self._style = "cyan"
        self._started = clock()
        self._ended: float | None = None
        self._ready = False
        self._suspended = 0
        self._last_download_notice = 0
        self._checkpoint: FoundationCheckpoint | None = None
        self._checkpoint_signal: float | None = None
        self._foundation_mode = ""
        self._token: Token[DeploymentProgress | None] | None = None
        self._spinner = Spinner("dots", style="bold cyan")
        self._auto_refresh = auto_refresh
        self._live = self._new_live()

    def _new_live(self) -> Live:
        """Start each terminal ownership interval with an empty cursor footprint."""

        return Live(
            get_renderable=self.render,
            console=self.console,
            auto_refresh=self._auto_refresh,
            refresh_per_second=4,
            transient=True,
            redirect_stdout=False,
            redirect_stderr=True,
        )

    def __enter__(self) -> Self:
        self._token = _CURRENT.set(self)
        try:
            self._emit(Text("FDAI | Azure deployment", style="bold cyan"))
            if self.dynamic:
                self._start_live()
        except BaseException:
            _CURRENT.reset(self._token)
            self._token = None
            raise
        return self

    def _start_live(self) -> None:
        """Restore partial Rich startup on interrupts before its render hook exists."""

        try:
            self._live.start(refresh=True)
        except BaseException as error:
            try:
                self._live.stop()
            except (OSError, ValueError, IndexError):
                error.add_note("Progress startup cleanup could not write to the terminal.")
            finally:
                try:
                    if self.dynamic:
                        self.console.show_cursor(True)
                except (OSError, ValueError):
                    error.add_note("The terminal was unavailable while restoring the cursor.")
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, traceback
        try:
            with self._lock:
                self._ended = self._clock()
                if exc is not None:
                    interrupted = isinstance(exc, KeyboardInterrupt)
                    self._headline = (
                        "Deployment interrupted" if interrupted else "Deployment failed"
                    )
                    self._style = "yellow" if interrupted else "red"
                    self._detail = "Preserve state and claims; recovery needs a reviewed plan."
                    if self._active is not None:
                        phase = self._phases[self._active]
                        phase.state = "interrupted" if interrupted else "failed"
                        phase.ended = self._ended
                elif not self._ready:
                    self._headline = "Deployment ended without a ready result"
                    self._style = "yellow"
                    if self._active is not None:
                        phase = self._phases[self._active]
                        phase.state = "incomplete"
                        phase.ended = self._ended
            if self.dynamic:
                self._live.stop()
                if not self._ready and self._active is not None:
                    self._phase_event(self._active)
                self.console.print(self.render())
            elif self.enabled:
                if exc is not None and self._active is not None:
                    self._phase_event(self._active)
                self._plain(self._headline)
        except (OSError, ValueError):
            if exc is None:
                raise
            exc.add_note("Progress output failed; the original deployment error is preserved.")
        finally:
            if self._token is not None:
                _CURRENT.reset(self._token)
                self._token = None

    def begin(self, name: StageName) -> None:
        """Advance only after the caller's existing checks; retain one event per transition."""

        with self._lock:
            if name == self._active:
                return
            previous = self._active
            now = self._clock()
            if previous is not None:
                self._phases[previous].state = "done"
                self._phases[previous].ended = now
            self._active = name
            self._phases[name].state = "running"
            self._phases[name].started = now
            self._detail = ""
            self._checkpoint = None
            self._checkpoint_signal = None
            self._foundation_mode = ""
        if previous is not None:
            self._phase_event(previous)
        self._phase_event(name)
        self._refresh()

    def detail(self, text: str, *, log: bool = True) -> None:
        """Show bounded application-owned text, never raw provider output or secrets."""

        text = "".join(character if character.isprintable() else " " for character in text)[:160]
        with self._lock:
            changed = text != self._detail
            self._detail = text
        if changed and log:
            self._emit(Text(f"      {text}", style="dim"))
        if log:
            self._refresh()

    def reset_foundation(self) -> None:
        """Begin a new display-only child pass without changing the coordinator phase."""
        with self._lock:
            self._checkpoint = None
            self._checkpoint_signal = None
            self._foundation_mode = ""
        self.detail("Starting Foundation checkpoints")

    def foundation_mode(self, mode: str) -> None:
        """Retain the recognized child mode, never an approval or readiness decision."""
        with self._lock:
            self._foundation_mode = mode
        self.detail(f"{mode.capitalize()} | exact plan approvals remain required")

    def foundation_checkpoint(self, value: FoundationCheckpoint) -> None:
        """Append distinct checked child transitions without completing a coordinator phase."""
        with self._lock:
            changed = value != self._checkpoint
            self._checkpoint = value
            self._checkpoint_signal = self._clock()
        if changed and self.dynamic:
            status = "REPORTED COMPLETE" if value.state == "COMPLETE" else value.state
            line = Text(f"  [{value.number:02}/{value.total}] ", style="magenta")
            line.append(f"{status} ", style=f"bold {_checkpoint_style(value)}")
            line.append(value.label)
            line.append(f" | {value.completed}/{value.total} complete", style="dim")
            self._emit(line)
        self._refresh()

    def foundation_signal(self) -> None:
        """Refresh observed activity only; a heartbeat never adds history or completes work."""
        with self._lock:
            self._checkpoint_signal = self._clock()
        self._refresh()

    def downloaded(self, byte_count: int) -> None:
        """Report bytes actually read, without inventing a total, ETA, or verification."""

        notice = self._last_download_notice == 0 or (
            byte_count - self._last_download_notice >= 64 * 1024 * 1024
        )
        self.detail(
            f"{byte_count / (1024 * 1024):.1f} MiB received; verification pending", log=notice
        )
        if notice:
            self._last_download_notice = byte_count

    def ready(self) -> None:
        """Finish presentation only after the caller has a verified deployment-ready result."""

        with self._lock:
            if self._active is not None:
                self._phases[self._active].state = "done"
                self._phases[self._active].ended = self._clock()
            self._ready = True
            self._headline = "Deployment ready"
            self._style = "green"
            self._detail = "Subscription-wide assurance remains open."
        if self._active is not None:
            self._phase_event(self._active)
        self._refresh()

    @contextmanager
    def terminal_output(self, label: str, *, approval: bool = False) -> Iterator[None]:
        """Yield the terminal to existing details or prompts without reading stdin."""

        with self._lock:
            phase = self._phases.get(self._active) if self._active is not None else None
            previous_state = phase.state if phase is not None else "running"
            if phase is not None and approval:
                phase.state = "waiting"
            self._suspended += 1
        if self.dynamic and self._suspended == 1:
            self._live.stop()
        line = Text(
            f"[{'WAIT' if approval else 'INFO'}] ", style="bold yellow" if approval else "cyan"
        )
        line.append(label, style="default")
        self._emit(line)
        succeeded = False
        try:
            yield
            succeeded = True
        finally:
            with self._lock:
                if phase is not None:
                    phase.state = previous_state
                self._suspended -= 1
            if self.dynamic and self._suspended == 0 and succeeded:
                self._live = self._new_live()
                self._start_live()

    def render(self) -> Group:
        """Render at most six unboxed lines of current work, never replaying past events."""
        with self._lock:
            now = self._ended if self._ended is not None else self._clock()
            phase = self._phases.get(self._active) if self._active is not None else None
            state = phase.state if phase is not None else "running"
            label = phase.label if phase is not None else "Preparing"
            duration = _elapsed(
                phase.started if phase else None,
                phase.ended if phase is not None and phase.ended is not None else now,
            )
            completed = sum(item.state == "done" for item in self._phases.values())
            elapsed = _elapsed(self._started, now)
            headline, style, detail = self._headline, self._style, self._detail
            checkpoint = self._checkpoint
            age = _elapsed(self._checkpoint_signal, now)
        status, phase_style = _STATES[state]
        row = Table.grid(padding=(0, 1), expand=True)
        row.add_column(width=4)
        row.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        row.add_column(no_wrap=True)
        row.add_row(
            self._spinner if state == "running" else Text(status, style=f"bold {phase_style}"),
            Text(label, style=f"bold {phase_style}"),
            Text(duration, style="dim"),
        )
        lines = [
            Text(f"FDAI | {headline}", style=f"bold {style}", no_wrap=True, overflow="ellipsis"),
            Text(f"{completed}/{len(_STAGES)} phases | elapsed {elapsed}", style="dim"),
        ]
        children: list[Text] = []
        if checkpoint is not None:
            child_style = _checkpoint_style(checkpoint)
            child_state = (
                "Reported complete"
                if checkpoint.state == "COMPLETE"
                else checkpoint.state.capitalize()
            )
            children = [
                Text(
                    f"{checkpoint.number:02}/{checkpoint.total} {checkpoint.label}",
                    style=f"bold {child_style}",
                    no_wrap=True,
                    overflow="ellipsis",
                ),
                Text(
                    f"{child_state} | {checkpoint.completed}/{checkpoint.total} complete | "
                    f"{checkpoint.skipped} skipped | last activity {age}",
                    style=child_style,
                    no_wrap=True,
                    overflow="ellipsis",
                ),
            ]
        return Group(
            *lines,
            row,
            *children,
            Text(detail, style=style, no_wrap=True, overflow="ellipsis"),
        )

    def _refresh(self) -> None:
        if self.dynamic and self._suspended == 0 and self._token is not None:
            self._live.refresh()

    def _emit(self, text: Text) -> None:
        """Serialize one event through Rich outside the state lock; keep plain output literal."""
        if self.dynamic:
            self.console.print(text)
        elif self.enabled:
            self._plain(text.plain)

    def _plain(self, text: str) -> None:
        self.console.file.write(text + "\n")
        self.console.file.flush()

    def _phase_event(self, name: StageName) -> None:
        with self._lock:
            phase = self._phases[name]
            index = list(self._phases).index(name) + 1
            status, style = _STATES[phase.state]
            end = phase.ended if phase.ended is not None else self._clock()
            duration = _elapsed(phase.started, end)
            line = Text(f"[{index:02}/{len(_STAGES)}] ", style="dim")
            line.append(f"{status:4} ", style=f"bold {style}")
            line.append(phase.label, style=style)
            line.append(f" ({duration})", style="dim")
        self._emit(line)


def _checkpoint_style(value: FoundationCheckpoint) -> str:
    if value.state in {"BLOCKED", "FAILED"}:
        return "red"
    return "yellow" if value.state == "WAITING" else "cyan"


def _elapsed(start: float | None, end: float) -> str:
    seconds = max(0, int(end - start)) if start is not None else 0
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def begin_stage(name: StageName) -> None:
    """Advance the active local display, or do nothing outside an interactive coordinator."""

    if (progress := _CURRENT.get()) is not None:
        progress.begin(name)


def progress_detail(text: str) -> None:
    """Publish one application-owned presentation detail without persisting it."""

    if (progress := _CURRENT.get()) is not None:
        progress.detail(text)


def downloaded_bytes(count: int) -> None:
    """Publish an observed byte count without changing artifact verification."""

    if (progress := _CURRENT.get()) is not None:
        progress.downloaded(count)


@contextmanager
def terminal_output(label: str, *, approval: bool = False) -> Iterator[None]:
    """Pause the active display around existing subprocess output or human confirmation."""

    progress = _CURRENT.get()
    if progress is None:
        yield
    else:
        with progress.terminal_output(label, approval=approval):
            yield
