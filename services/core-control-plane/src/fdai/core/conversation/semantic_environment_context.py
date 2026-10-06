"""Principal-scoped environment context for the question form and its blind reader.

The block names the resource groups this principal can read, so the model can tell a word
that is one exact container name from a fragment that resource names contain. It is model
context only: it is never evidence, never a source of mentions, and never quoted. Core still
binds every identity by exact lookup, and an answer reads only its verified plan.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.ontology.acl import ProjectionRequest

_LOGGER = logging.getLogger(__name__)

ENVIRONMENT_RESOURCE_GROUP_LIMIT = 200
ENVIRONMENT_READ_TIMEOUT_SECONDS = 1.5
_RESOURCE = "Resource"
_RESOURCE_GROUP_TYPE = "resource-group"
_CURRENT: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "semantic_environment_context", default=None
)


def current_environment_context() -> Mapping[str, Any] | None:
    """Return the environment context bound to the running form path, if any."""

    return _CURRENT.get()


@contextmanager
def bind_environment_context(value: Mapping[str, Any] | None) -> Iterator[None]:
    """Bind one turn's environment context for every form and blind-reader call it makes."""

    token = _CURRENT.set(value)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def safe_environment_context(
    environment: Mapping[str, Any] | None,
    *,
    unsafe: Callable[[str], bool],
) -> dict[str, Any] | None:
    """Return a model-bound copy with every unsafe name withheld and counted.

    A name whose decoding reveals a secret or an exact identifier is left out rather than
    altered, and the block then says it is incomplete, so the model never treats the list
    as whole when it isn't.
    """

    if not environment:
        return None
    groups = [
        item for item in environment.get("resource_groups") or () if isinstance(item, Mapping)
    ]
    safe = [
        {"name": str(item.get("name") or ""), "location": str(item.get("location") or "")}
        for item in groups
        if not any(
            unsafe(value)
            for value in (str(item.get("name") or ""), str(item.get("location") or ""))
        )
    ]
    withheld = len(groups) - len(safe)
    payload: dict[str, Any] = {
        "kind": str(environment.get("kind") or "resource_groups"),
        "complete": environment.get("complete") is True and withheld == 0,
        "resource_groups": safe,
    }
    if withheld:
        payload["withheld"] = withheld
    return payload


async def resource_group_context(
    gateway: SecuredObjectSetQueryGateway,
    *,
    projection_request: ProjectionRequest,
    purpose: str,
    as_of: datetime | Callable[[], datetime],
    limit: int = ENVIRONMENT_RESOURCE_GROUP_LIMIT,
) -> dict[str, Any] | None:
    """Read the resource groups the principal can see, or ``None`` when the read fails.

    The list is marked complete only when the source is complete, the read wasn't cut, and
    every group fits the bound; otherwise the block says so instead of implying the list is
    whole.
    """

    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name=_RESOURCE),
        predicates=(
            ObjectPredicate(
                property="type",
                operator=ObjectPredicateOperator.EQUALS,
                equals=_RESOURCE_GROUP_TYPE,
            ),
        ),
        as_of=as_of() if callable(as_of) else as_of,
        purpose=purpose,
        limit=limit + 1,
        include_relationships=False,
    )
    try:
        async with asyncio.timeout(ENVIRONMENT_READ_TIMEOUT_SECONDS):
            secured = await gateway.materialize(definition, projection_request=projection_request)
    except Exception as exc:  # noqa: BLE001 - context is optional; the turn proceeds without it
        _LOGGER.info(
            "semantic_environment_context_unavailable",
            extra={"failure_type": type(exc).__name__},
        )
        return None
    groups = sorted(
        {
            (str(record.properties.get("name") or ""), str(record.properties.get("location") or ""))
            for record in secured.materialization.graph.objects
            if record.properties.get("name")
        }
    )
    shown = groups[:limit]
    complete = (
        secured.receipt.source_complete and not secured.receipt.truncated and len(groups) <= limit
    )
    return {
        "kind": "resource_groups",
        "complete": complete,
        "resource_groups": [{"name": name, "location": location} for name, location in shown],
    }


__all__ = [
    "ENVIRONMENT_RESOURCE_GROUP_LIMIT",
    "bind_environment_context",
    "current_environment_context",
    "resource_group_context",
    "safe_environment_context",
]
