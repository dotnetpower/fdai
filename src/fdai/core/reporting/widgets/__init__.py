"""Widget-builder catalog.

One file per widget family (graphs / lists / flows / reliability /
annotations); :mod:`.defaults` returns every upstream builder in one
call. A fork adds its own by implementing
:class:`~fdai.core.reporting.contracts.WidgetBuilder` and calling
:meth:`WidgetRegistry.register` at the composition root.
"""

from __future__ import annotations

from fdai.core.reporting.widgets.annotations import (
    FreeTextBuilder,
    ImageBuilder,
    NoteBuilder,
)
from fdai.core.reporting.widgets.defaults import (
    default_widget_builders,
    install_default_widgets,
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

__all__ = [
    "BarChartBuilder",
    "ChangeBuilder",
    "DistributionBuilder",
    "FreeTextBuilder",
    "FunnelBuilder",
    "HeatmapBuilder",
    "ImageBuilder",
    "ListStreamBuilder",
    "NoteBuilder",
    "QueryValueBuilder",
    "SankeyBuilder",
    "SloSummaryBuilder",
    "TableBuilder",
    "TimeseriesBuilder",
    "TopListBuilder",
    "TreemapBuilder",
    "default_widget_builders",
    "install_default_widgets",
]
