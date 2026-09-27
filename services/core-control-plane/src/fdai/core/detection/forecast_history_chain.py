"""Pure stateful-chain derivation and retained-window reconciliation for forecast history.

A derived chain restates one clean, positively checkpointed source read. Each instant carries at
most one mapped state regardless of record order. The proven state is restated once per
lookback-aligned grid instant, so overlapping episodes share one `checkpoint` anchor instead of
multiplying restatements beyond the collector's bounded read. Complete coverage may be appended
only when every stored transition in the window is re-asserted by the current read.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.detection.forecast_history import FORECAST_HISTORY_CHECKPOINT_STATE
from fdai.core.detection.forecast_history_source import ForecastSourceRecord
from fdai.core.ontology_platform.state_transitions import OperationalStateTransition

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ChainStep:
    """One derived edge; its identity names the source event or the grid restatement."""

    identity: tuple[str, ...]
    from_state: str
    to_state: str
    effective_at: datetime
    evidence_ref: str


def anchor_instant(horizon_started_at: datetime, *, step_seconds: int) -> datetime:
    """Return the latest grid instant in `(horizon start - step, horizon start]`."""
    step = timedelta(seconds=step_seconds)
    return _EPOCH + ((horizon_started_at - _EPOCH) // step) * step


def derive_state_chain(
    mapped: Sequence[tuple[ForecastSourceRecord, str]],
    *,
    initial: str,
    initial_ref: str,
    start_at: datetime,
    anchor_at: datetime,
    tokens: set[str],
) -> tuple[ChainStep, ...]:
    """Group records by instant first, then restate the state proven at the anchor instant."""
    instants: dict[datetime, list[tuple[ForecastSourceRecord, str]]] = {}
    for record, state in mapped:
        instants.setdefault(record.effective_at, []).append((record, state))
    if any(len({state for _record, state in group}) > 1 for group in instants.values()) or any(
        state != initial for _record, state in instants.get(start_at, ())
    ):
        tokens.add("conflicting_source_record")
        return ()
    steps: list[ChainStep] = []
    running, running_ref = initial, initial_ref
    anchor: tuple[str, str] | None = None
    changed_at_anchor = False
    for instant in sorted(instants):
        if anchor is None and instant > anchor_at:
            anchor = (running, running_ref)
        record, state = min(
            instants[instant],
            key=lambda item: (
                item[0].recorded_at,
                item[0].source_event_id,
                item[0].source_revision,
            ),
        )
        if state != running:
            steps.append(
                ChainStep(
                    ("state", record.source_event_id, record.source_revision),
                    running,
                    state,
                    instant,
                    record.evidence_ref,
                )
            )
            changed_at_anchor = changed_at_anchor or instant == anchor_at
            running = state
        running_ref = record.evidence_ref
    anchor_state, anchor_ref = anchor if anchor is not None else (running, running_ref)
    if not changed_at_anchor:
        steps.append(
            ChainStep(
                ("checkpoint", anchor_at.isoformat(), anchor_state, anchor_ref),
                FORECAST_HISTORY_CHECKPOINT_STATE,
                anchor_state,
                anchor_at,
                anchor_ref,
            )
        )
    return tuple(sorted(steps, key=lambda item: item.effective_at))


def retained_limitations(
    retained: Iterable[OperationalStateTransition],
    derived: Sequence[OperationalStateTransition],
    *,
    initial: str | None,
) -> set[str]:
    """Explain why the stored window differs from the current read; empty means identical.

    A stored transition the read no longer asserts, including an earlier revision of a revised
    record, is withdrawn. A stored restatement must repeat the current chain state at a distinct
    instant. Event histories (`initial is None`) never carry restatements.
    """
    wanted = {item.idempotency_key: item for item in derived}
    chain = sorted(derived, key=lambda item: item.effective_at)
    instants = {item.effective_at for item in chain}
    tokens: set[str] = set()
    for item in retained:
        prior = wanted.get(item.idempotency_key)
        if prior is not None:
            if _content(prior) != _content(item):
                tokens.add("conflicting_retained_record")
        elif item.from_state != FORECAST_HISTORY_CHECKPOINT_STATE:
            tokens.add("retained_record_withdrawn")
        elif (
            initial is None
            or item.effective_at in instants
            or _state_at(chain, item.effective_at, initial) != item.to_state
        ):
            tokens.add("conflicting_retained_record")
    return tokens


def _state_at(chain: Sequence[OperationalStateTransition], at: datetime, initial: str) -> str:
    state = initial
    for item in chain:
        if item.effective_at > at:
            break
        state = item.to_state
    return state


def _content(item: OperationalStateTransition) -> tuple[object, ...]:
    return (item.from_state, item.to_state, item.effective_at, item.evidence_refs)


__all__ = ["ChainStep", "anchor_instant", "derive_state_chain", "retained_limitations"]
