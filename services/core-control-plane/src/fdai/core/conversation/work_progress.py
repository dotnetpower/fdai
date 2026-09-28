"""Pin one turn's work progress shape before its governed read plan runs.

The pin is presentation density derived from the compiled plan. It is recorded for the durable
projection and published best-effort on the progress stream ahead of the plan's first node, and
it never carries evidence or authority.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from fdai_service_contracts.ontology_query import OntologyQueryPlan
from fdai_service_contracts.semantic_work_progress import (
    WorkProgressShape,
    derive_work_progress_shape,
)

_LOGGER = logging.getLogger(__name__)
WorkProgressPublisher = Callable[[WorkProgressShape], Awaitable[None]]


@dataclass(slots=True)
class WorkProgressRecorder:
    """Retain the single pin of one turn so every terminal can persist it."""

    shape: WorkProgressShape | None = None


_PUBLISHER: ContextVar[WorkProgressPublisher | None] = ContextVar(
    "semantic_work_progress_publisher",
    default=None,
)
_RECORDER: ContextVar[WorkProgressRecorder | None] = ContextVar(
    "semantic_work_progress_recorder",
    default=None,
)


@contextmanager
def bind_semantic_work_progress_publisher(publisher: WorkProgressPublisher) -> Iterator[None]:
    """Bind the progress-stream publisher for one consumed request."""

    token = _PUBLISHER.set(publisher)
    try:
        yield
    finally:
        _PUBLISHER.reset(token)


@contextmanager
def record_semantic_work_progress() -> Iterator[WorkProgressRecorder]:
    """Bind a recorder that tasks created inside the block share with the caller."""

    recorder = WorkProgressRecorder()
    token = _RECORDER.set(recorder)
    try:
        yield recorder
    finally:
        _RECORDER.reset(token)


async def publish_work_progress_pin(plan: OntologyQueryPlan) -> None:
    """Record and publish the pin for the turn's governed plan before its first node runs.

    The compiler plans once, so only the first pin of a turn is kept. A plan outside the contract
    bounds is not pinned, and a publication failure never delays or fails the read.
    """

    recorder = _RECORDER.get()
    if recorder is not None and recorder.shape is not None:
        return
    shape = derive_work_progress_shape((node.node_id, node.depends_on) for node in plan.nodes)
    if shape is None:
        return
    if recorder is not None:
        recorder.shape = shape
    publisher = _PUBLISHER.get()
    if publisher is None:
        return
    try:
        await publisher(shape)
    except Exception:  # noqa: BLE001 - best-effort presentation progress cannot control the read
        _LOGGER.warning("semantic_work_progress_publish_failed")


__all__ = [
    "WorkProgressRecorder",
    "bind_semantic_work_progress_publisher",
    "publish_work_progress_pin",
    "record_semantic_work_progress",
]
