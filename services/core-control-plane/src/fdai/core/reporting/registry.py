"""In-memory registries for the reporting engine.

Four typed containers with a uniform ``register`` / ``get`` /
``list`` (or ``names`` / ``types``) surface:

- :class:`DataSourceRegistry` - by :attr:`ReportDataSource.name`.
- :class:`WidgetRegistry` - by :attr:`WidgetBuilder.type_name`.
- :class:`FormatRegistry` - by :attr:`FormatEncoder.name`.
- :class:`ReportCatalog` - by :attr:`ReportSpec.id`.

Registration is idempotent for **encoders and datasources** (last-write
wins - a fork intentionally overrides an upstream default), but a
:class:`ReportCatalog` rejects duplicate ids on register to catch the
common "two YAMLs claim the same id" mistake at composition time.
"""

from __future__ import annotations

from collections.abc import Iterable

from fdai.core.reporting.contracts import (
    DataSourceNotFoundError,
    FormatEncoder,
    FormatNotFoundError,
    ReportDataSource,
    ReportNotFoundError,
    WidgetBuilder,
    WidgetTypeNotFoundError,
)
from fdai.core.reporting.models import DataSourceProvenance, ReportSpec


class DataSourceRegistry:
    """Datasource lookup by name; last-write-wins on re-register."""

    __slots__ = ("_by_name", "_provenance")

    def __init__(self, sources: Iterable[ReportDataSource] = ()) -> None:
        self._by_name: dict[str, ReportDataSource] = {}
        self._provenance: dict[str, DataSourceProvenance] = {}
        for source in sources:
            self.register(source)

    def register(
        self,
        source: ReportDataSource,
        *,
        provenance: DataSourceProvenance | None = None,
    ) -> None:
        self._by_name[source.name] = source
        self._provenance[source.name] = provenance or DataSourceProvenance(
            datasource=source.name,
            source=source.name,
        )

    def get(self, name: str) -> ReportDataSource:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise DataSourceNotFoundError(name) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))

    def provenance(self, name: str) -> DataSourceProvenance:
        try:
            return self._provenance[name]
        except KeyError as exc:
            raise DataSourceNotFoundError(name) from exc

    def provenances(self) -> tuple[DataSourceProvenance, ...]:
        return tuple(self._provenance[name] for name in sorted(self._provenance))


class WidgetRegistry:
    """Widget builder lookup by type name; last-write-wins on re-register."""

    __slots__ = ("_by_type",)

    def __init__(self, builders: Iterable[WidgetBuilder] = ()) -> None:
        self._by_type: dict[str, WidgetBuilder] = {}
        for builder in builders:
            self.register(builder)

    def register(self, builder: WidgetBuilder) -> None:
        self._by_type[builder.type_name] = builder

    def get(self, type_name: str) -> WidgetBuilder:
        try:
            return self._by_type[type_name]
        except KeyError as exc:
            raise WidgetTypeNotFoundError(type_name) from exc

    def types(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_type))


class FormatRegistry:
    """Format encoder lookup by name; last-write-wins on re-register."""

    __slots__ = ("_by_name",)

    def __init__(self, encoders: Iterable[FormatEncoder] = ()) -> None:
        self._by_name: dict[str, FormatEncoder] = {}
        for encoder in encoders:
            self.register(encoder)

    def register(self, encoder: FormatEncoder) -> None:
        self._by_name[encoder.name] = encoder

    def get(self, name: str) -> FormatEncoder:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise FormatNotFoundError(name) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))


class ReportCatalog:
    """Loaded :class:`ReportSpec` catalog, keyed by report id.

    Register rejects duplicate ids so two YAMLs claiming the same id
    fail at composition time, not at first render.
    """

    __slots__ = ("_by_id",)

    def __init__(self, specs: Iterable[ReportSpec] = ()) -> None:
        self._by_id: dict[str, ReportSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ReportSpec) -> None:
        if spec.id in self._by_id:
            raise ValueError(f"duplicate report id: {spec.id!r}")
        self._by_id[spec.id] = spec

    def get(self, report_id: str) -> ReportSpec:
        try:
            return self._by_id[report_id]
        except KeyError as exc:
            raise ReportNotFoundError(report_id) from exc

    def list(self) -> tuple[ReportSpec, ...]:
        return tuple(self._by_id[k] for k in sorted(self._by_id))


__all__ = [
    "DataSourceRegistry",
    "FormatRegistry",
    "ReportCatalog",
    "WidgetRegistry",
]
