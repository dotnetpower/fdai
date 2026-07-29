"""Read-only versioned MCSB control and implementation coverage projection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.rule_catalog.schema.mcsb_catalog import McsbCatalog, McsbControlMapping

DEFAULT_ROUTE_PATH = "/mcsb-controls"
DETAIL_ROUTE_PATH = "/mcsb-controls/{benchmark_version}/{control_id}"
DEFAULT_LIMIT = 100
MAX_LIMIT = 200


def _counts(values: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items(), key=lambda item: (-item[1], item[0])))


def _mapping_by_control(catalog: McsbCatalog) -> dict[str, McsbControlMapping]:
    return {mapping.control_id: mapping for mapping in catalog.mappings}


def _control_summary(catalog: McsbCatalog, index: int) -> dict[str, object]:
    control = catalog.controls[index]
    mapping = catalog.mappings[index]
    return {
        "control_id": control.id,
        "title": control.title,
        "domain": control.domain,
        "coverage": mapping.coverage.value,
        "rule_count": len(mapping.rule_ids),
        "runtime_observation_count": len(mapping.runtime_observation_ids),
        "manual_evidence_count": len(mapping.manual_evidence_refs),
    }


def _catalog_summary(catalog: McsbCatalog) -> dict[str, object]:
    return {
        "benchmark_version": catalog.benchmark_version,
        "title": catalog.title,
        "status": catalog.status,
        "control_import_status": catalog.control_import_status,
        "control_count": len(catalog.controls),
        "coverage_counts": catalog.coverage_counts(),
        "policy_profiles": [
            {
                "profile_id": profile.profile_id,
                "policy_ref_count": profile.policy_ref_count,
            }
            for profile in catalog.policy_profiles
        ],
    }


def make_mcsb_control_routes(
    *,
    catalogs: Sequence[McsbCatalog],
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
    detail_path: str = DETAIL_ROUTE_PATH,
) -> list[Route]:
    """Return immutable MCSB list/detail routes over validated catalogs."""

    ordered = tuple(sorted(catalogs, key=lambda catalog: catalog.benchmark_version))
    by_version = {catalog.benchmark_version: catalog for catalog in ordered}
    default_version = next(
        (catalog.benchmark_version for catalog in ordered if catalog.status == "stable"),
        ordered[0].benchmark_version,
    )

    def bad_request(message: str) -> Response:
        return JSONResponse({"error": {"status": 400, "message": message}}, status_code=400)

    async def list_handler(request: Request) -> Response:
        await authorize(request)
        params = request.query_params
        version = params.get("version", default_version).strip().lower()
        catalog = by_version.get(version)
        if catalog is None:
            return bad_request(f"unknown MCSB version {version!r}")
        domain = params.get("domain", "").strip().upper()
        coverage = params.get("coverage", "").strip().lower()
        needle = params.get("q", "").strip().lower()
        try:
            limit = int(params.get("limit", str(DEFAULT_LIMIT)))
            offset = int(params.get("offset", "0"))
        except ValueError:
            return bad_request("limit and offset MUST be integers")
        if limit < 1 or limit > MAX_LIMIT:
            return bad_request(f"limit MUST be between 1 and {MAX_LIMIT}")
        if offset < 0:
            return bad_request("offset MUST be >= 0")
        summaries = [_control_summary(catalog, index) for index in range(len(catalog.controls))]
        matched = [
            item
            for item in summaries
            if (not domain or item["domain"] == domain)
            and (not coverage or item["coverage"] == coverage)
            and (
                not needle
                or needle in f"{item['control_id']} {item['title']} {item['domain']}".lower()
            )
        ]
        return JSONResponse(
            {
                "benchmark": _catalog_summary(catalog),
                "versions": [_catalog_summary(item) for item in ordered],
                "total": len(summaries),
                "filtered_total": len(matched),
                "offset": offset,
                "limit": limit,
                "facets": {
                    "by_domain": _counts([str(item["domain"]) for item in summaries]),
                    "by_coverage": _counts([str(item["coverage"]) for item in summaries]),
                },
                "controls": matched[offset : offset + limit],
                "evaluation_source": "catalog_crosswalk",
            }
        )

    async def detail_handler(request: Request) -> Response:
        await authorize(request)
        version = request.path_params["benchmark_version"].lower()
        control_id = request.path_params["control_id"].upper()
        catalog = by_version.get(version)
        if catalog is None:
            return JSONResponse(
                {"error": {"status": 404, "message": f"unknown MCSB version {version!r}"}},
                status_code=404,
            )
        controls = {control.id: control for control in catalog.controls}
        control = controls.get(control_id)
        if control is None:
            return JSONResponse(
                {"error": {"status": 404, "message": f"unknown MCSB control {control_id!r}"}},
                status_code=404,
            )
        mapping = _mapping_by_control(catalog)[control_id]
        return JSONResponse(
            {
                **_control_summary(catalog, catalog.controls.index(control)),
                "benchmark_version": catalog.benchmark_version,
                "rule_ids": list(mapping.rule_ids),
                "runtime_observation_ids": list(mapping.runtime_observation_ids),
                "manual_evidence_refs": list(mapping.manual_evidence_refs),
                "source": {
                    "source_url": catalog.source.source_url,
                    "artifact_url": catalog.source.artifact_url,
                    "resolved_ref": catalog.source.resolved_ref,
                    "content_hash": catalog.source.content_hash,
                    "license": catalog.source.license,
                    "redistribution": catalog.source.redistribution,
                    "retrieved_at": catalog.source.retrieved_at,
                },
                "evaluation_source": "catalog_crosswalk",
            }
        )

    return [
        Route(path, list_handler, methods=["GET"]),
        Route(detail_path, detail_handler, methods=["GET"]),
    ]


__all__ = ["DEFAULT_ROUTE_PATH", "DETAIL_ROUTE_PATH", "make_mcsb_control_routes"]
