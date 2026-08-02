"""Reporting-subsystem Protocols (seams) + typed error hierarchy.

Three seams, one per registry:

- :class:`ReportDataSource` - async, I/O-bound; produces a
  :class:`~fdai.core.reporting.models.DataSet` for one widget query.
- :class:`WidgetBuilder` - sync, CPU-only; pure transform from a
  :class:`~fdai.core.reporting.models.DataSet` to the widget's ``data``
  mapping.
- :class:`FormatEncoder` - sync, CPU-only; encodes a rendered report to
  bytes for delivery (JSON / Markdown / CSV / ...).

Async/sync split matches ``coding-conventions.instructions.md § Safety``:
I/O-bound seams are async, CPU / startup-only seams stay sync.

The Protocols are ``runtime_checkable`` so tests can assert conformance
without a full type-checker pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from fdai.core.reporting.models import DataSet, QuerySpec, RenderedReport, WidgetSpec


class ReportingError(RuntimeError):
    """Base error for the reporting subsystem.

    Every fail-closed exit in the engine raises a subclass, so a caller
    can distinguish reporting errors from unrelated crashes.
    """


class ReportNotFoundError(ReportingError):
    """A report id was requested that the catalog does not know."""


class DataSourceNotFoundError(ReportingError):
    """A widget references a datasource the registry does not know."""


class WidgetTypeNotFoundError(ReportingError):
    """A widget references a type the registry does not know."""


class FormatNotFoundError(ReportingError):
    """A caller asked for an output format the registry does not know."""


class VariableRejectedError(ReportingError):
    """A caller-supplied variable override failed validation.

    Raised for both "not declared" and "not in the allowlist" cases so
    the Operator API can map the whole family to HTTP 400 without leaking
    which of the two conditions tripped.
    """


@runtime_checkable
class ReportDataSource(Protocol):
    """A named producer of :class:`DataSet`s for widget queries.

    Async by contract - a real backend (Postgres, KQL, PromQL, Kafka)
    would block the event loop otherwise; matches the discipline of the
    five wire-level provider Protocols in :mod:`fdai.shared.providers`.

    A datasource MUST be read-only: it MUST NOT mutate state, MUST NOT
    hold the executor identity, and MUST NOT call an action delivery
    adapter (``app-shape.instructions.md § Layer Boundaries``).
    """

    @property
    def name(self) -> str:
        """Stable identifier used by :class:`QuerySpec.datasource`."""
        ...

    async def query(
        self,
        spec: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        """Execute one widget query.

        ``since`` / ``until`` are the resolved report time window (UTC).
        ``variables`` is the resolved variable map (defaults + validated
        overrides). The implementation MAY reference either via
        ``spec.parameters`` substitution.
        """
        ...


@runtime_checkable
class WidgetBuilder(Protocol):
    """Pure transform: :class:`DataSet` -> widget-specific ``data`` mapping.

    Sync by contract - builders are CPU-only. A builder MUST be a pure
    function of its inputs (deterministic, side-effect-free) so it can
    run under the same request scope as the datasource query without
    additional coordination.
    """

    @property
    def type_name(self) -> str:
        """Widget type as it appears in ``rule-catalog/reports/*.yaml``."""
        ...

    def build(
        self,
        *,
        spec: WidgetSpec,
        data: DataSet,
    ) -> Mapping[str, Any]:
        """Return the widget's ``data`` payload as a plain mapping.

        The engine wraps the return value in a
        :class:`~fdai.core.reporting.models.RenderedWidget` and never
        mutates it; a builder MAY return a ``dict`` or an
        immutable-mapping equivalent.
        """
        ...


@runtime_checkable
class FormatEncoder(Protocol):
    """Encode a :class:`RenderedReport` to bytes for delivery."""

    @property
    def name(self) -> str:
        """Format identifier as it appears in ``?format=<name>``."""
        ...

    @property
    def content_type(self) -> str:
        """HTTP ``Content-Type`` header value for the encoded payload."""
        ...

    def encode(self, report: RenderedReport) -> bytes:
        """Return the serialized report body."""
        ...


__all__ = [
    "DataSourceNotFoundError",
    "FormatEncoder",
    "FormatNotFoundError",
    "ReportDataSource",
    "ReportNotFoundError",
    "ReportingError",
    "VariableRejectedError",
    "WidgetBuilder",
    "WidgetTypeNotFoundError",
]
