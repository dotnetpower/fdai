"""Callable datasource - wrap any sync/async callable as a datasource.

A fork's composition root can register ad-hoc data producers without
implementing the whole :class:`~fdai.core.reporting.contracts.ReportDataSource`
Protocol: hand :class:`CallableDataSource` a callable that returns a
:class:`~fdai.core.reporting.models.DataSet` and it becomes a
first-class datasource under any name.

The callable receives the same kwargs the Protocol does
(``spec``, ``since``, ``until``, ``variables``) so it has all the
context a full datasource would.

Read-only by contract - the datasource MUST NOT mutate state; the
adapter cannot enforce this beyond its Protocol shape.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from fdai.core.reporting.models import DataSet, QuerySpec

CallableQueryFn = Callable[..., DataSet | Awaitable[DataSet]]
"""Signature: ``(spec, *, since, until, variables) -> DataSet | Awaitable[DataSet]``."""


class CallableDataSource:
    """Adapt a plain callable (sync or async) into a
    :class:`~fdai.core.reporting.contracts.ReportDataSource`.
    """

    __slots__ = ("_name", "_fn")

    def __init__(self, *, name: str, fn: CallableQueryFn) -> None:
        if not callable(fn):
            raise TypeError("CallableDataSource requires a callable")
        self._name = name
        self._fn = fn

    @property
    def name(self) -> str:
        return self._name

    async def query(
        self,
        spec: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        result: Any = self._fn(spec, since=since, until=until, variables=variables)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, DataSet):
            raise TypeError(
                f"CallableDataSource {self._name!r} returned {type(result).__name__}, "
                "expected DataSet"
            )
        return result


__all__ = ["CallableDataSource", "CallableQueryFn"]
