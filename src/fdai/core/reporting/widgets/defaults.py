"""Ship-with-upstream default widget builders.

:func:`install_default_widgets` registers every builder documented in
``docs/roadmap/interfaces/reporting-subsystem.md`` on a
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
    IframeBuilder,
    ImageBuilder,
    NoteBuilder,
)
from fdai.core.reporting.widgets.architecture import (
    GeomapBuilder,
    HostmapBuilder,
    TopologyMapBuilder,
)
from fdai.core.reporting.widgets.composite import SplitGraphBuilder
from fdai.core.reporting.widgets.cost import (
    BudgetSummaryBuilder,
    CostSummaryBuilder,
)
from fdai.core.reporting.widgets.flows import (
    FunnelBuilder,
    RetentionBuilder,
    SankeyBuilder,
    TreemapBuilder,
)
from fdai.core.reporting.widgets.graphs import (
    BarChartBuilder,
    ChangeBuilder,
    DistributionBuilder,
    GaugeBuilder,
    HeatmapBuilder,
    PieChartBuilder,
    ProgressBarBuilder,
    QueryValueBuilder,
    ScatterPlotBuilder,
    SparklineBuilder,
    TimeseriesBuilder,
)
from fdai.core.reporting.widgets.lists import (
    EventStreamBuilder,
    ListStreamBuilder,
    TableBuilder,
    TopListBuilder,
)
from fdai.core.reporting.widgets.reliability import (
    AlertStatusBuilder,
    CheckStatusBuilder,
    FlameGraphBuilder,
    ServiceSummaryBuilder,
    SloSummaryBuilder,
)
from fdai.core.reporting.widgets.workflow import ComparisonBuilder, ProcessStepsBuilder


def default_widget_builders() -> Iterable[WidgetBuilder]:
    """Return one instance of every upstream widget builder.

    ``group`` and ``tabs`` are intentionally absent - the engine
    special-cases them via
    :data:`~fdai.core.reporting.widgets.composite.GROUP_LIKE_WIDGET_TYPES`.
    """
    return (
        # graphs
        TimeseriesBuilder(),
        QueryValueBuilder(),
        ChangeBuilder(),
        DistributionBuilder(),
        HeatmapBuilder(),
        BarChartBuilder(),
        PieChartBuilder(),
        ScatterPlotBuilder(),
        SparklineBuilder(),
        GaugeBuilder(),
        ProgressBarBuilder(),
        # lists
        TableBuilder(),
        TopListBuilder(),
        ListStreamBuilder(),
        EventStreamBuilder(),
        # flows
        FunnelBuilder(),
        SankeyBuilder(),
        TreemapBuilder(),
        RetentionBuilder(),
        # reliability
        SloSummaryBuilder(),
        AlertStatusBuilder(),
        CheckStatusBuilder(),
        ServiceSummaryBuilder(),
        FlameGraphBuilder(),
        # architecture
        HostmapBuilder(),
        TopologyMapBuilder(),
        GeomapBuilder(),
        # cost
        CostSummaryBuilder(),
        BudgetSummaryBuilder(),
        # workflow presentation
        ProcessStepsBuilder(),
        ComparisonBuilder(),
        # composite / annotations
        SplitGraphBuilder(),
        FreeTextBuilder(),
        NoteBuilder(),
        ImageBuilder(),
        IframeBuilder(),
    )


def install_default_widgets(registry: WidgetRegistry) -> WidgetRegistry:
    """Register every default builder on ``registry`` and return it."""
    for builder in default_widget_builders():
        registry.register(builder)
    return registry


__all__ = ["default_widget_builders", "install_default_widgets"]
