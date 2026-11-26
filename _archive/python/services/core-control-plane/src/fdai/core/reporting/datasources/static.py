"""Static / dev-only datasources: canned DataSet + no-op.

These two exist for tests, demo dashboards, and as the upstream default
binding for a datasource slot the fork has not filled yet. Neither
performs I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai.core.reporting.models import DataSet, QuerySpec


class StaticDataSource:
    """Return a fixed :class:`DataSet` for every query.

    Constructor kwargs let a report YAML point ``query.datasource`` at a
    named source and get a deterministic result - useful for showcasing
    a widget shape in a demo dashboard without wiring a real backend.
    """

    __slots__ = ("_name", "_dataset")

    def __init__(self, *, name: str, dataset: DataSet) -> None:
        self._name = name
        self._dataset = dataset

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
        del spec, since, until, variables
        return self._dataset


class NoopDataSource:
    """Upstream default binding - empty result for every query.

    A YAML report that references a datasource the fork has not wired
    yet renders as "no data" instead of failing. The engine still
    records the widget with an empty ``data`` mapping.
    """

    __slots__ = ("_name",)

    def __init__(self, *, name: str = "noop") -> None:
        self._name = name

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
        del spec, since, until, variables
        return DataSet()


__all__ = ["NoopDataSource", "StaticDataSource"]
