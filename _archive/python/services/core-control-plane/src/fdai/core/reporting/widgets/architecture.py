"""Architecture-family widget builders: hostmap, topology_map, geomap.

The three widgets share a "nodes + optional edges + metric coloring" data
shape. Every builder is a pure transform - the FE decides tile layout,
graph layout, and map projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import DataSet, WidgetSpec


class HostmapBuilder:
    """Render rows as colored host tiles.

    Expects rows shaped ``{"host", "value", "group"?}``. ``group`` (when
    present) becomes a tile-cluster label. Field names overridable via
    ``options.host_field`` / ``options.value_field`` / ``options.group_field``.
    """

    type_name = "hostmap"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        host_field = str(spec.options.get("host_field", "host"))
        value_field = str(spec.options.get("value_field", "value"))
        group_field = str(spec.options.get("group_field", "group"))
        tiles: list[dict[str, Any]] = []
        for row in data.rows:
            tile: dict[str, Any] = {
                "host": row.get(host_field),
                "value": row.get(value_field),
            }
            if group_field in row:
                tile["group"] = row.get(group_field)
            tiles.append(tile)
        return {"tiles": tiles}


class TopologyMapBuilder:
    """Render a directed dependency graph.

    Expects two logical row shapes:

    - node rows: ``{"kind": "node", "id", "label"?, "group"?, "value"?}``.
    - edge rows: ``{"kind": "edge", "source", "target", "value"?}``.

    A row without an explicit ``kind`` is treated as an edge if it
    carries ``source`` + ``target``, otherwise as a node. The FE draws
    the graph; server-side we normalize into ``nodes`` / ``edges``.
    """

    type_name = "topology_map"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        for row in data.rows:
            kind = row.get("kind")
            if kind == "edge" or ("source" in row and "target" in row and kind is None):
                src = row.get("source")
                tgt = row.get("target")
                if src is None or tgt is None:
                    continue
                edges.append({"source": str(src), "target": str(tgt), "value": row.get("value")})
                nodes.setdefault(str(src), {"id": str(src)})
                nodes.setdefault(str(tgt), {"id": str(tgt)})
            else:
                node_id = row.get("id")
                if node_id is None:
                    continue
                nodes[str(node_id)] = {
                    "id": str(node_id),
                    "label": row.get("label"),
                    "group": row.get("group"),
                    "value": row.get("value"),
                }
        return {"nodes": list(nodes.values()), "edges": edges}


class GeomapBuilder:
    """Choropleth or point-map data.

    Expects rows shaped ``{"region"?, "lat"?, "lon"?, "value"?}``. A
    row with ``lat`` + ``lon`` becomes a point marker; a row with
    ``region`` becomes a choropleth area (the FE joins on region code).
    Field names overridable via ``options.region_field`` /
    ``options.lat_field`` / ``options.lon_field`` / ``options.value_field``.
    """

    type_name = "geomap"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        region_field = str(spec.options.get("region_field", "region"))
        lat_field = str(spec.options.get("lat_field", "lat"))
        lon_field = str(spec.options.get("lon_field", "lon"))
        value_field = str(spec.options.get("value_field", "value"))
        points: list[dict[str, Any]] = []
        areas: list[dict[str, Any]] = []
        for row in data.rows:
            if lat_field in row and lon_field in row:
                points.append(
                    {
                        "lat": row.get(lat_field),
                        "lon": row.get(lon_field),
                        "value": row.get(value_field),
                        "label": row.get("label"),
                    }
                )
            elif region_field in row:
                areas.append({"region": row.get(region_field), "value": row.get(value_field)})
        return {"points": points, "areas": areas}


__all__ = ["GeomapBuilder", "HostmapBuilder", "TopologyMapBuilder"]
