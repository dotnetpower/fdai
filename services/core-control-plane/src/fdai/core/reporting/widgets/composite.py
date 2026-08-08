"""Composite widget builders: ``tabs``, ``split_graph``.

The engine special-cases *group-like* widget types so their ``children``
recurse without a datasource call. :data:`GROUP_LIKE_WIDGET_TYPES` is
the union of every such type; it is re-exported here so a fork can
register additional "container" types without editing the engine
(as long as it adds the type name to
:attr:`~fdai.core.reporting.config.ReportEngineConfig` in a future
extension - upstream keeps this frozen for now).

``split_graph`` is the one exception: it consumes a datasource result
and fans it out into per-series children the FE renders as small
multiples. The child list comes from :attr:`DataSet.series`, so the
report author configures one query and the FE gets N compact charts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import DataSet, WidgetSpec

GROUP_LIKE_WIDGET_TYPES: frozenset[str] = frozenset({"group", "tabs"})
"""Widget types the engine treats as composite containers.

The engine iterates ``spec.children`` and recurses; there is no
datasource call for these types.
"""


class SplitGraphBuilder:
    """Fan one time-series query out into N compact per-series charts.

    Data contract: consumes ``DataSet.series`` and emits
    ``{"panels": [{"label", "labels", "points"}]}``. The FE renders one
    small chart per panel using the same shape as ``sparkline`` /
    ``timeseries``.
    """

    type_name = "split_graph"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        return {
            "panels": [
                {
                    "label": s.label,
                    "labels": dict(s.labels),
                    "points": [list(p) for p in s.points],
                }
                for s in data.series
            ]
        }


__all__ = [
    "GROUP_LIKE_WIDGET_TYPES",
    "SplitGraphBuilder",
]
