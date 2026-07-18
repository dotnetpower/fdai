"""Widget-builder catalog.

One file per widget family (graphs / lists / flows / reliability /
annotations / architecture / cost / composite); :mod:`.defaults`
returns every upstream builder in one call. A fork adds its own by
implementing :class:`~fdai.core.reporting.contracts.WidgetBuilder` and
calling :meth:`WidgetRegistry.register` at the composition root.
"""

from __future__ import annotations

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
from fdai.core.reporting.widgets.composite import (
    GROUP_LIKE_WIDGET_TYPES,
    SplitGraphBuilder,
)
from fdai.core.reporting.widgets.cost import (
    BudgetSummaryBuilder,
    CostSummaryBuilder,
)
from fdai.core.reporting.widgets.defaults import (
    default_widget_builders,
    install_default_widgets,
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

__all__ = [
    "AlertStatusBuilder",
    "BarChartBuilder",
    "BudgetSummaryBuilder",
    "ChangeBuilder",
    "CheckStatusBuilder",
    "CostSummaryBuilder",
    "ComparisonBuilder",
    "DistributionBuilder",
    "EventStreamBuilder",
    "FlameGraphBuilder",
    "FreeTextBuilder",
    "FunnelBuilder",
    "GROUP_LIKE_WIDGET_TYPES",
    "GaugeBuilder",
    "GeomapBuilder",
    "HeatmapBuilder",
    "HostmapBuilder",
    "IframeBuilder",
    "ImageBuilder",
    "ListStreamBuilder",
    "NoteBuilder",
    "PieChartBuilder",
    "ProgressBarBuilder",
    "ProcessStepsBuilder",
    "QueryValueBuilder",
    "RetentionBuilder",
    "SankeyBuilder",
    "ScatterPlotBuilder",
    "ServiceSummaryBuilder",
    "SloSummaryBuilder",
    "SparklineBuilder",
    "SplitGraphBuilder",
    "TableBuilder",
    "TimeseriesBuilder",
    "TopListBuilder",
    "TopologyMapBuilder",
    "TreemapBuilder",
    "default_widget_builders",
    "install_default_widgets",
]
