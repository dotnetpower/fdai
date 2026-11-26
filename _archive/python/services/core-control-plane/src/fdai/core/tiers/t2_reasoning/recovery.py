"""Bounded T2 proposer failover and sanitized attempt receipts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from fdai.core.quality_gate.gate import QualityCandidate

if TYPE_CHECKING:
    from fdai.core.tiers.t2_reasoning.tier import T2ProposalContext, T2Proposer

ReserveAttempt = Callable[[], Awaitable[bool]]


class T2FailureClass(StrEnum):
    """Sanitized failure classes safe for durable evidence."""

    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    PROVIDER_ERROR = "provider_error"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class T2AttemptReceipt:
    """One bounded proposer attempt without endpoint or exception text."""

    event_id: str
    correlation_id: str
    route_ref: str
    preferred_route_ref: str
    attempt: int
    candidate_count: int
    status: str
    failure_class: T2FailureClass | None
    retryable: bool
    terminal: bool
    recovered: bool
    observed_at: str

    def to_dict(self) -> dict[str, object]:
        """Return the stable machine-record projection."""

        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "route_ref": self.route_ref,
            "preferred_route_ref": self.preferred_route_ref,
            "attempt": self.attempt,
            "candidate_count": self.candidate_count,
            "status": self.status,
            "failure_class": self.failure_class.value if self.failure_class is not None else None,
            "retryable": self.retryable,
            "terminal": self.terminal,
            "recovered": self.recovered,
            "observed_at": self.observed_at,
        }


class T2RecoveryObserver(Protocol):
    """Durably observe one sanitized proposer attempt."""

    async def observe(self, receipt: T2AttemptReceipt) -> None: ...


class T2RouteSelector(Protocol):
    """Return the preferred route ref from durable control-plane state."""

    async def preferred_route(self, available_routes: tuple[str, ...]) -> str: ...


class T2ProposerBudgetExhaustedError(RuntimeError):
    """No declared call budget remains for another proposer candidate."""


class T2ProposerCandidatesExhaustedError(RuntimeError):
    """Every bounded proposer candidate failed."""


class BoundedFailoverT2Proposer:
    """Try at most two distinct proposer routes under per-attempt budget."""

    __slots__ = ("_candidates", "_clock", "_observer", "_route_selector")

    def __init__(
        self,
        *,
        candidates: Sequence[tuple[str, T2Proposer]],
        observer: T2RecoveryObserver | None = None,
        route_selector: T2RouteSelector | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        bounded = tuple(candidates)
        if not 1 <= len(bounded) <= 2:
            raise ValueError("T2 proposer failover requires one or two candidates")
        route_refs = tuple(route_ref for route_ref, _ in bounded)
        if len(route_refs) != len(set(route_refs)):
            raise ValueError("T2 proposer route refs MUST be unique")
        if any(
            not route_ref
            or len(route_ref) > 64
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
                for character in route_ref
            )
            for route_ref in route_refs
        ):
            raise ValueError("T2 proposer route refs MUST be bounded lowercase identifiers")
        self._candidates = bounded
        self._observer = observer
        self._route_selector = route_selector
        self._clock = clock

    def bind_observer(self, observer: T2RecoveryObserver) -> None:
        """Bind the runtime observer before the control loop starts."""

        if self._observer is not None and self._observer is not observer:
            raise RuntimeError("T2 recovery observer is already bound")
        self._observer = observer

    def bind_route_selector(self, selector: T2RouteSelector) -> None:
        """Bind the runtime route registry before the control loop starts."""

        if self._route_selector is not None and self._route_selector is not selector:
            raise RuntimeError("T2 proposer route selector is already bound")
        self._route_selector = selector

    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        """Reject unbudgeted direct use; T2Tier supplies the shared reservation."""

        del context
        raise RuntimeError("bounded T2 failover requires the T2Tier attempt budget")

    async def propose_with_budget(
        self,
        *,
        context: T2ProposalContext,
        reserve_attempt: ReserveAttempt,
    ) -> QualityCandidate | None:
        """Try candidates in order, reserving every actual model invocation."""

        failed = False
        candidates = await self._ordered_candidates()
        candidate_count = len(candidates)
        preferred_route_ref = candidates[0][0]
        for index, (route_ref, proposer) in enumerate(candidates, start=1):
            if not await reserve_attempt():
                await self._emit(
                    context=context,
                    route_ref=route_ref,
                    preferred_route_ref=preferred_route_ref,
                    attempt=index,
                    status="skipped",
                    failure_class=T2FailureClass.BUDGET_EXHAUSTED,
                    retryable=False,
                    terminal=True,
                    recovered=False,
                )
                raise T2ProposerBudgetExhaustedError("T2 proposer failover budget exhausted")
            try:
                candidate = await proposer.propose(context=context)
            except Exception as exc:  # noqa: BLE001 - candidate provider boundary
                failed = True
                terminal = index == candidate_count
                await self._emit(
                    context=context,
                    route_ref=route_ref,
                    preferred_route_ref=preferred_route_ref,
                    attempt=index,
                    status="failed",
                    failure_class=_classify_failure(exc),
                    retryable=_retryable(exc),
                    terminal=terminal,
                    recovered=False,
                )
                if terminal:
                    raise T2ProposerCandidatesExhaustedError(
                        "all bounded T2 proposer candidates failed"
                    ) from exc
                continue
            await self._emit(
                context=context,
                route_ref=route_ref,
                preferred_route_ref=preferred_route_ref,
                attempt=index,
                status="abstained" if candidate is None else "succeeded",
                failure_class=None,
                retryable=False,
                terminal=True,
                recovered=failed and candidate is not None,
            )
            return candidate
        raise AssertionError("bounded candidates are non-empty")

    async def _ordered_candidates(self) -> tuple[tuple[str, T2Proposer], ...]:
        selector = self._route_selector
        if selector is None:
            return self._candidates
        try:
            preferred = await selector.preferred_route(
                tuple(route_ref for route_ref, _ in self._candidates)
            )
        except Exception:  # noqa: BLE001 - selector outage retains bounded failover
            return self._candidates
        selected = tuple(candidate for candidate in self._candidates if candidate[0] == preferred)
        if not selected:
            return self._candidates
        return selected + tuple(
            candidate for candidate in self._candidates if candidate[0] != preferred
        )

    async def _emit(
        self,
        *,
        context: T2ProposalContext,
        route_ref: str,
        preferred_route_ref: str,
        attempt: int,
        status: str,
        failure_class: T2FailureClass | None,
        retryable: bool,
        terminal: bool,
        recovered: bool,
    ) -> None:
        if self._observer is None:
            return
        observed_at = self._clock()
        if observed_at.tzinfo is None:
            raise ValueError("T2 recovery receipt clock MUST be timezone-aware")
        await self._observer.observe(
            T2AttemptReceipt(
                event_id=str(context.event.event_id),
                correlation_id=str(context.event.correlation_id or context.event.event_id),
                route_ref=route_ref,
                preferred_route_ref=preferred_route_ref,
                attempt=attempt,
                candidate_count=len(self._candidates),
                status=status,
                failure_class=failure_class,
                retryable=retryable,
                terminal=terminal,
                recovered=recovered,
                observed_at=observed_at.isoformat(),
            )
        )


def _classify_failure(exc: Exception) -> T2FailureClass:
    if isinstance(exc, TimeoutError):
        return T2FailureClass.TIMEOUT
    if isinstance(exc, (ValueError, TypeError)):
        return T2FailureClass.INVALID_RESPONSE
    return T2FailureClass.PROVIDER_ERROR


def _retryable(exc: Exception) -> bool:
    return not isinstance(exc, (ValueError, TypeError))


__all__ = [
    "BoundedFailoverT2Proposer",
    "ReserveAttempt",
    "T2AttemptReceipt",
    "T2FailureClass",
    "T2ProposerBudgetExhaustedError",
    "T2ProposerCandidatesExhaustedError",
    "T2RecoveryObserver",
    "T2RouteSelector",
]
