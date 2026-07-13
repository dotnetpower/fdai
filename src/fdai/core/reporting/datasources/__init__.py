"""Datasource adapters shipped upstream.

Every adapter wraps an existing seam (audit reader, report feed,
metric / log_query provider) without introducing a new one:

- :class:`~fdai.core.reporting.datasources.static.StaticDataSource` /
  :class:`~fdai.core.reporting.datasources.static.NoopDataSource` -
  fixed / empty result; test + fallback.
- :class:`~fdai.core.reporting.datasources.audit.AuditDataSource` -
  projects an audit reader (duck-typed :class:`AuditReader`) into
  table / count-by projections.
- :class:`~fdai.core.reporting.datasources.report_feed.ReportFeedDataSource` -
  wraps :class:`~fdai.core.report_feed.feed.ReportFeed`.
- :class:`~fdai.core.reporting.datasources.metric.MetricDataSource` -
  wraps :class:`~fdai.shared.providers.metric.MetricProvider`.
- :class:`~fdai.core.reporting.datasources.log_query.LogQueryDataSource` -
  wraps :class:`~fdai.shared.providers.log_query.LogQueryProvider`.

A fork registers additional datasources by implementing
:class:`~fdai.core.reporting.contracts.ReportDataSource` and calling
:meth:`~fdai.core.reporting.registry.DataSourceRegistry.register` at
the composition root.
"""

from __future__ import annotations

from fdai.core.reporting.datasources.audit import AuditDataSource, AuditReader
from fdai.core.reporting.datasources.callable import (
    CallableDataSource,
    CallableQueryFn,
)
from fdai.core.reporting.datasources.filesystem import FilesystemManifestDataSource
from fdai.core.reporting.datasources.log_query import LogQueryDataSource
from fdai.core.reporting.datasources.metric import MetricDataSource
from fdai.core.reporting.datasources.ontology import OntologyDataSource
from fdai.core.reporting.datasources.report_feed import ReportFeedDataSource
from fdai.core.reporting.datasources.static import NoopDataSource, StaticDataSource

__all__ = [
    "AuditDataSource",
    "AuditReader",
    "CallableDataSource",
    "CallableQueryFn",
    "FilesystemManifestDataSource",
    "LogQueryDataSource",
    "MetricDataSource",
    "NoopDataSource",
    "OntologyDataSource",
    "ReportFeedDataSource",
    "StaticDataSource",
]
