"""Composition helpers for the reporting subsystem.

Assembles a :class:`~fdai.core.reporting.engine.ReportEngine` from the
upstream defaults so a fork composition root can wire the whole
subsystem in one call.

Usage sketch (a fork composition root calls this factory and hands the
result to ``fdai.delivery.read_api.routes.reporting.ReportingConfig``):

- import ``default_reporting_engine`` from :mod:`fdai.core.reporting.composition`;
- call it with the seams the fork has wired (any missing datasource
  falls back to :class:`NoopDataSource` under the same name);
- pass the returned ``(engine, formats)`` pair into the delivery-side
  ``ReportingConfig`` and mount it on ``ReadApiConfig.reporting``.

Every argument is optional; the missing datasources fall back to
:class:`~fdai.core.reporting.datasources.static.NoopDataSource` under
the well-known names (``audit`` / ``report_feed`` / ``metric`` /
``log_query``) so a sample YAML that references them still loads and
renders as "no data" instead of failing.

The helper never imports ``delivery/`` so ``core/reporting`` stays
framework-neutral (the delivery-side ``ReportingConfig`` takes this
engine + format registry as input).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fdai.core.reporting.catalog import load_report_catalog
from fdai.core.reporting.datasources import (
    AuditDataSource,
    AuditReader,
    LogQueryDataSource,
    MetricDataSource,
    NoopDataSource,
    OntologyDataSource,
    ReportFeedDataSource,
)
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.formats import install_default_formats
from fdai.core.reporting.registry import (
    DataSourceRegistry,
    FormatRegistry,
    ReportCatalog,
    WidgetRegistry,
)
from fdai.core.reporting.widgets import install_default_widgets

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fdai.core.report_feed.feed import ReportFeed
    from fdai.shared.providers.log_query import LogQueryProvider
    from fdai.shared.providers.metric import MetricProvider
    from fdai.shared.providers.ontology_instance import OntologyInstanceStore
    from fdai.shared.providers.process_runtime import ProcessRuntimeStore


_KNOWN_DATASOURCE_NAMES: frozenset[str] = frozenset(
    {"audit", "report_feed", "metric", "log_query", "ontology"}
)


def default_reporting_engine(
    *,
    reports_root: Path | None = None,
    audit_reader: AuditReader | None = None,
    report_feed: ReportFeed | None = None,
    metric_provider: MetricProvider | None = None,
    log_query_provider: LogQueryProvider | None = None,
    ontology_store: OntologyInstanceStore | None = None,
    process_store: ProcessRuntimeStore | None = None,
) -> tuple[ReportEngine, FormatRegistry]:
    """Build the upstream reporting engine + a default format registry.

    The engine ships with every default widget builder registered. Each
    of the four "real" datasource kinds is wired when its provider is
    supplied and stubbed with a :class:`NoopDataSource` under the same
    name otherwise, so a report YAML that references an unwired source
    still loads and renders as an empty widget instead of failing at
    catalog-load time.

    ``reports_root`` (typically ``rule-catalog/reports``) is loaded and
    validated up-front against the wired widget / datasource sets so a
    typo in a YAML fails at composition, not at first render. Passing
    ``None`` leaves the catalog empty; the fork can then register
    additional specs directly on the returned engine.
    """
    widgets = install_default_widgets(WidgetRegistry())
    sources = DataSourceRegistry()

    if audit_reader is not None:
        sources.register(AuditDataSource(reader=audit_reader))
    else:
        sources.register(NoopDataSource(name="audit"))

    if report_feed is not None:
        sources.register(ReportFeedDataSource(feed=report_feed))
    else:
        sources.register(NoopDataSource(name="report_feed"))

    if metric_provider is not None:
        sources.register(MetricDataSource(provider=metric_provider))
    else:
        sources.register(NoopDataSource(name="metric"))

    if log_query_provider is not None:
        sources.register(LogQueryDataSource(provider=log_query_provider))
    else:
        sources.register(NoopDataSource(name="log_query"))

    if ontology_store is not None and process_store is not None:
        sources.register(OntologyDataSource(ontology=ontology_store, processes=process_store))
    else:
        sources.register(NoopDataSource(name="ontology"))

    catalog = ReportCatalog()
    if reports_root is not None:
        specs = load_report_catalog(
            reports_root,
            allowed_widget_types=frozenset(widgets.types()) | {"group"},
            allowed_datasources=frozenset(sources.names()),
        )
        catalog = ReportCatalog(specs)

    engine = ReportEngine(catalog=catalog, sources=sources, widgets=widgets)
    formats = install_default_formats(FormatRegistry())
    return engine, formats


__all__ = ["default_reporting_engine"]
