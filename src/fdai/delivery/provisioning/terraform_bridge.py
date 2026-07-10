"""Provisioning bridge - map ``terraform apply -json`` into ``provision.*``.

This is surface **A** (Day-1 bootstrap) of the Genesis provisioning
experience. At Day-1 the operator console does not exist yet - it is one of
the resources being provisioned - so the Genesis screen runs *locally*,
driven by the real Terraform apply that ``azd up`` performs.

Terraform's ``-json`` machine output emits one JSON object per line. This
module is a **pure** state machine that folds those lines into
:class:`~fdai.delivery.read_api.provision_stream.ProvisionEvent` s:

- the plan ``change_summary`` sets the denominator (how many resources will
  be touched),
- each ``apply_complete`` advances the fraction,
- a slow ``apply_progress`` (over a threshold) becomes an honest
  ``provision.waiting`` and its later completion a ``provision.resumed``,
- an ``apply_errored`` / error ``diagnostic`` becomes ``provision.failed``,
- the captured ``outputs`` supply the ``console_url``, and ``provision.done``
  is emitted once the apply ``change_summary`` and the ``outputs`` (which
  Terraform emits *after* it) have both been seen - or at end-of-stream via
  :meth:`TerraformProvisionBridge.finalize` when a stack declares no outputs.

No I/O lives here: a thin serve harness reads Terraform's stdout, calls
:meth:`TerraformProvisionBridge.feed`, and publishes the returned events onto
the SSE sink (:class:`SseProvisionPublisher`). The harness MUST call
:meth:`TerraformProvisionBridge.finalize` once when stdout closes so a
deferred ``provision.done`` is flushed. Keeping the fold pure makes the
mapping fully unit-testable against recorded Terraform log fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fdai.delivery.read_api.provision_stream import ProvisionEvent, ProvisionPhase

# Terraform output name that carries the operator-console URL. The value is
# decided in Terraform (infra/) - Python never computes a resource name or
# URL - so this is only the *key* to read, never the URL itself.
DEFAULT_CONSOLE_OUTPUT = "console_url"

# An `apply_progress` line reporting at least this many elapsed seconds for a
# resource is treated as an honest "still working" hold (provision.waiting).
DEFAULT_WAITING_THRESHOLD_SECONDS = 30.0


def parse_json_line(line: str) -> dict[str, Any] | None:
    """Parse one Terraform ``-json`` line, or ``None`` if it is not JSON.

    Terraform can interleave non-JSON noise (e.g. a warning banner) even in
    ``-json`` mode; those lines are skipped rather than raised on.
    """
    text = line.strip()
    if not text or text[0] != "{":
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _resource_addr(record: Mapping[str, Any]) -> str | None:
    hook = record.get("hook")
    if not isinstance(hook, Mapping):
        return None
    resource = hook.get("resource")
    if isinstance(resource, Mapping):
        addr = resource.get("addr")
        if isinstance(addr, str) and addr:
            return addr
    return None


def _elapsed_seconds(record: Mapping[str, Any]) -> float | None:
    hook = record.get("hook")
    if not isinstance(hook, Mapping):
        return None
    elapsed = hook.get("elapsed_seconds")
    if isinstance(elapsed, (int, float)):
        return float(elapsed)
    return None


def console_url_from_outputs(
    outputs: Mapping[str, Any], *, key: str = DEFAULT_CONSOLE_OUTPUT
) -> str | None:
    """Extract the console URL from a Terraform ``outputs`` message payload.

    The payload shape is ``{name: {value, type, sensitive, action}}``. Returns
    ``None`` when the key is absent or its value is not a non-empty string.
    """
    entry = outputs.get(key)
    if isinstance(entry, Mapping):
        value = entry.get("value")
        if isinstance(value, str) and value:
            return value
    # Some emitters flatten to name: value directly.
    if isinstance(entry, str) and entry:
        return entry
    return None


@dataclass(slots=True)
class TerraformProvisionBridge:
    """Stateful, pure fold from Terraform ``-json`` lines to provision events.

    Feed lines in order with :meth:`feed`; it returns zero or more
    :class:`ProvisionEvent` s to publish for that line. All state is internal
    counters - no I/O, no clock - so a recorded log replays deterministically.
    """

    console_output_key: str = DEFAULT_CONSOLE_OUTPUT
    waiting_threshold_seconds: float = DEFAULT_WAITING_THRESHOLD_SECONDS
    correlation_id: str | None = None

    _planned_total: int = field(default=0, init=False)
    _applied: int = field(default=0, init=False)
    _waiting: set[str] = field(default_factory=set, init=False)
    _console_url: str | None = field(default=None, init=False)
    _done: bool = field(default=False, init=False)
    _apply_finished: bool = field(default=False, init=False)

    @property
    def console_url(self) -> str | None:
        return self._console_url

    @property
    def fraction(self) -> float:
        if self._planned_total <= 0:
            return 0.0
        return min(1.0, self._applied / self._planned_total)

    def _event(self, phase: ProvisionPhase, **kwargs: Any) -> ProvisionEvent:
        return ProvisionEvent(phase=phase, correlation_id=self.correlation_id, **kwargs)

    def feed(self, line: str) -> list[ProvisionEvent]:
        record = parse_json_line(line)
        if record is None:
            return []
        return self.feed_record(record)

    def feed_record(self, record: Mapping[str, Any]) -> list[ProvisionEvent]:
        rec_type = record.get("type")
        if not isinstance(rec_type, str):
            return []

        if rec_type == "change_summary":
            return self._on_change_summary(record)
        if rec_type == "outputs":
            return self._capture_outputs(record)
        if rec_type == "apply_progress":
            return self._on_apply_progress(record)
        if rec_type == "apply_complete":
            return self._on_apply_complete(record)
        if rec_type == "apply_errored":
            return self._on_apply_errored(record)
        if rec_type == "diagnostic":
            return self._on_diagnostic(record)
        return []

    # -- per-type handlers --------------------------------------------------

    def _on_change_summary(self, record: Mapping[str, Any]) -> list[ProvisionEvent]:
        changes = record.get("changes")
        if not isinstance(changes, Mapping):
            return []
        operation = changes.get("operation")
        if operation == "plan":
            total = 0
            for key in ("add", "change", "remove", "import"):
                value = changes.get(key)
                if isinstance(value, int) and value > 0:
                    total += value
            self._planned_total = total
            return []
        if operation == "apply" and not self._done:
            # Terraform emits the `outputs` message AFTER the apply
            # change_summary, so emitting done here unconditionally would
            # always drop console_url. Mark the apply finished and emit only
            # once the URL is known (via _capture_outputs) or at end-of-stream
            # (via finalize()) when no outputs ever arrive.
            self._apply_finished = True
            return self._emit_done_if_ready()
        return []

    def _emit_done_if_ready(self, *, force: bool = False) -> list[ProvisionEvent]:
        """Emit ``provision.done`` once, when the apply is finished.

        Held back until :attr:`_console_url` is captured so the terminal
        event carries the operator-console link. ``force=True``
        (:meth:`finalize`) emits with a possibly-``None`` URL to guarantee
        done is not lost when a stack declares no outputs.
        """
        if not self._apply_finished or self._done:
            return []
        if self._console_url is None and not force:
            return []
        self._done = True
        return [self._event(ProvisionPhase.DONE, console_url=self._console_url, fraction=1.0)]

    def finalize(self) -> list[ProvisionEvent]:
        """Flush a deferred ``provision.done`` at end-of-stream.

        Call once after the last Terraform line. When the apply completed but
        done was held waiting for outputs that never arrived, this emits it
        now (``console_url`` may be ``None``). No-op when done already fired
        or the apply never completed - a failed / aborted run keeps its last
        honest state (a ``provision.failed`` and the stalled meter) rather
        than being papered over with a success.
        """
        return self._emit_done_if_ready(force=True)

    def _capture_outputs(self, record: Mapping[str, Any]) -> list[ProvisionEvent]:
        outputs = record.get("outputs")
        if isinstance(outputs, Mapping):
            url = console_url_from_outputs(outputs, key=self.console_output_key)
            if url is not None:
                self._console_url = url
        return self._emit_done_if_ready()

    def _on_apply_progress(self, record: Mapping[str, Any]) -> list[ProvisionEvent]:
        addr = _resource_addr(record)
        elapsed = _elapsed_seconds(record)
        if addr is None or elapsed is None:
            return []
        if elapsed >= self.waiting_threshold_seconds and addr not in self._waiting:
            self._waiting.add(addr)
            reason = f"still applying ({int(elapsed)}s elapsed)"
            return [self._event(ProvisionPhase.WAITING, node=addr, reason=reason)]
        return []

    def _on_apply_complete(self, record: Mapping[str, Any]) -> list[ProvisionEvent]:
        addr = _resource_addr(record)
        events: list[ProvisionEvent] = []
        if addr is not None and addr in self._waiting:
            self._waiting.discard(addr)
            events.append(self._event(ProvisionPhase.RESUMED, node=addr))
        self._applied += 1
        events.append(self._event(ProvisionPhase.PROGRESS, fraction=self.fraction, node=addr))
        return events

    def _on_apply_errored(self, record: Mapping[str, Any]) -> list[ProvisionEvent]:
        addr = _resource_addr(record) or "unknown"
        self._waiting.discard(addr)
        return [self._event(ProvisionPhase.FAILED, node=addr, reason="apply errored")]

    def _on_diagnostic(self, record: Mapping[str, Any]) -> list[ProvisionEvent]:
        diagnostic = record.get("diagnostic")
        if not isinstance(diagnostic, Mapping):
            return []
        if diagnostic.get("severity") != "error":
            return []
        summary = diagnostic.get("summary")
        reason = summary if isinstance(summary, str) and summary else "diagnostic error"
        addr = diagnostic.get("address")
        node = addr if isinstance(addr, str) and addr else "terraform"
        return [self._event(ProvisionPhase.FAILED, node=node, reason=reason)]


__all__ = [
    "DEFAULT_CONSOLE_OUTPUT",
    "DEFAULT_WAITING_THRESHOLD_SECONDS",
    "TerraformProvisionBridge",
    "console_url_from_outputs",
    "parse_json_line",
]
