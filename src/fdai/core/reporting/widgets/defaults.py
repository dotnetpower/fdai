"""Ship-with-upstream default widget builders.

:func:`install_default_widgets` registers every builder documented in
``docs/roadmap/reporting-subsystem.md`` on a
:class:`~fdai.core.reporting.registry.WidgetRegistry`. A fork calls it at
its composition root, then may :meth:`WidgetRegistry.register` its own
custom builders (or overwrite the defaults - last-write wins).

The registry seeded here is intentionally a **superset** of the widget
types any single report uses, so a fork does not need to re-register
every builder to author a new YAML report.
"""

from __future__ import annotations

from collections.abc import Iterable

from fdai.core.reporting.contracts import WidgetBuilder
from fdai.core.reporting.registry import WidgetRegistry
from fdai.core.reporting.widgets.annotations import (
    FreeTextBuilder,
    ImageBuilder,
    NoteBuilder,
)
from fdai.core.reporting.widgets.flows import (
    FunnelBuilder,
    SankeyBuilder,
    TreemapBuilder,
)
from fdai.core.reporting.widgets.graphs import (
    BarChartBuilder,
    ChangeBuilder,
    DistributionBuilder,
    HeatmapBuilder,
    QueryValueBuilder,
    TimeseriesBuilder,
)
from fdai.core.reporting.widgets.lists import (
    ListStreamBuilder,
    TableBuilder,
    TopListBuilder,
)
from fdai.core.reporting.widgets.reliability import SloSummaryBuilder


def default_widget_builders() -> Iterable[WidgetBuilder]:
    """Return one instance of every upstream widget builder.

    ``group`` is intentionally absent - the engine special-cases it.
    """
    return (
        # graphs
        TimeseriesBuilder(),
        QueryValueBuilder(),
        ChangeBuilder(),
        DistributionBuilder(),
        HeatmapBuilder(),
        BarChartBuilder(),
        # lists
        TableBuilder(),
        TopListBuilder(),
        ListStreamBuilder(),
        # flows
        FunnelBuilder(),
        SankeyBuilder(),
        TreemapBuilder(),
        # reliability
        SloSummaryBuilder(),
        # annotations
        FreeTextBuilder(),
        NoteBuilder(),
        ImageBuilder(),
    )


def install_default_widgets(registry: WidgetRegistry) -> WidgetRegistry:
    """Register every default builder on ``registry`` and return it."""
    for builder in default_widget_builders():
        registry.register(builder)
    return registry


__all__ = ["default_widget_builders", "install_default_widgets"]
