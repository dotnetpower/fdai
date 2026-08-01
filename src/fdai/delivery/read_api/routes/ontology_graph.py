"""Read-only ``GET /ontology/graph`` route.

Returns the rendered Mermaid ``classDiagram`` for the loaded ObjectType /
LinkType catalog plus the ActionType safety-contract catalog. The rendered graph
is deterministic - a fork's PR that adds an ObjectType shows a
diffable change in the exported Markdown / SPA snapshot.

Registered by :func:`~fdai.delivery.read_api.main.build_app` only when
:attr:`~fdai.delivery.read_api.main.ReadApiConfig.ontology_object_types`
AND :attr:`~fdai.delivery.read_api.main.ReadApiConfig.ontology_link_types`
are both non-empty. Reader-role gate; GET-only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.ontology_explorer import render_ontology_mermaid
from fdai.core.ontology_platform import CompiledInterfaceCatalog, platform_manifest
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.state_store import StateStore

DEFAULT_ROUTE_PATH = "/ontology/graph"


def make_ontology_graph_route(
    *,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    action_types: Sequence[OntologyActionType] = (),
    status_reader: StateStore | None = None,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
) -> Route:
    """Return a Starlette :class:`Route` serving the ontology graph."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        include_props = request.query_params.get("include_properties", "true").lower() != "false"
        try:
            property_limit = int(request.query_params.get("property_limit", "8"))
        except ValueError:
            return JSONResponse(
                {"error": {"status": 400, "message": "property_limit MUST be an integer"}},
                status_code=400,
            )
        if property_limit < 1:
            return JSONResponse(
                {"error": {"status": 400, "message": "property_limit MUST be >= 1"}},
                status_code=400,
            )
        if property_limit > 100:
            # Cap the render cost - a caller asking for a 1000-property
            # graph per node forces the SPA to buffer megabytes of nodes.
            return JSONResponse(
                {"error": {"status": 400, "message": "property_limit MUST be <= 100"}},
                status_code=400,
            )

        rendered = render_ontology_mermaid(
            object_types,
            link_types,
            include_properties=include_props,
            property_limit=property_limit,
        )

        # Structured nodes + edges so the FE can draw a custom graph
        # when the Mermaid classDiagram is too dense to read (the SPA
        # renders a semantic-cluster layout by default and keeps the
        # Mermaid source as a fallback / copy option).
        nodes = [
            {
                "name": ot.name,
                "key": ot.key,
                "property_count": len(ot.properties),
                "properties": sorted(ot.properties.keys()),
                "description": ot.description,
                "lifecycle": ot.lifecycle.model_dump(mode="json")
                if ot.lifecycle is not None
                else None,
                "provenance": ot.provenance.model_dump(mode="json")
                if ot.provenance is not None
                else None,
            }
            for ot in object_types
        ]
        edges = [
            {
                "name": lt.name,
                "from_type": lt.from_type,
                "to_type": lt.to_type,
                "cardinality": lt.cardinality.value
                if hasattr(lt.cardinality, "value")
                else str(lt.cardinality),
                "is_transitive": lt.is_transitive,
                "is_causal": lt.is_causal,
                "temporal_order": lt.temporal_order,
                "order_by_property": lt.order_by_property,
                "description": lt.description,
                "provenance": lt.provenance.model_dump(mode="json")
                if lt.provenance is not None
                else None,
            }
            for lt in link_types
        ]
        actions = [
            action_type.model_dump(mode="json", exclude_none=True)
            for action_type in sorted(action_types, key=lambda item: item.name)
        ]
        release = build_ontology_release(
            object_types=object_types,
            link_types=link_types,
            action_types=action_types,
        )
        ontology_platform = platform_manifest(
            release=release,
            interfaces=CompiledInterfaceCatalog(interfaces={}, concrete_types={}),
            action_types=action_types,
            functions=(),
        )
        operating_model = {"status": "unavailable"}
        if status_reader is not None:
            from fdai.runtime.operating_model import OPERATING_MODEL_STATUS_KEY

            stored_status = await status_reader.read_state(OPERATING_MODEL_STATUS_KEY)
            if stored_status is not None:
                operating_model = {
                    key: stored_status[key]
                    for key in (
                        "schema_version",
                        "status",
                        "source_revision",
                        "object_count",
                        "link_count",
                    )
                    if key in stored_status
                }
        return JSONResponse(
            {
                "mermaid": rendered.mermaid,
                "object_type_count": rendered.object_type_count,
                "link_type_count": rendered.link_type_count,
                "action_type_count": len(actions),
                "object_types": sorted(o.name for o in object_types),
                "link_types": sorted(link.name for link in link_types),
                "action_types": actions,
                "nodes": nodes,
                "edges": edges,
                "operating_model": operating_model,
                "ontology_platform": ontology_platform,
            }
        )

    return Route(path, handler, methods=["GET"])


__all__ = ["DEFAULT_ROUTE_PATH", "make_ontology_graph_route"]
