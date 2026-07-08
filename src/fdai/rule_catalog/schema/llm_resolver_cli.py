"""CLI entrypoint for the LLM bootstrap resolver.

Offline-first: the CLI accepts JSON fixture inputs so it is fully
testable without any Azure SDK. Real Azure-backed queries plug in later
via ``--use-azure-sdk`` (deferred - see W-C in
[dev-and-deploy-parity.md](../../../../docs/roadmap/dev-and-deploy-parity.md)).

Usage
-----

.. code-block:: bash

    python -m fdai.rule_catalog.schema.llm_resolver_cli \\
        --registry rule-catalog/llm-registry.yaml \\
        --region koreacentral \\
        --subscription-id 00000000-0000-0000-0000-000000000000 \\
        --deployer-object-id 00000000-0000-0000-0000-000000000001 \\
        --catalog-fixture tests/scenarios/llm/catalog.koreacentral.json \\
        --permission-fixture tests/scenarios/llm/permission.granted.json \\
        --quota-fixture tests/scenarios/llm/quota.default.json \\
        --out resolved-models.json

Exit codes
----------

- ``0`` - resolved (all capabilities RESOLVED, CAPACITY_REDUCED, or HIL_ONLY
  according to environment).
- ``2`` - resolver hard error (mixed-model invariant violated, config missing).
- ``64`` - usage error (bad CLI args).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from fdai.rule_catalog.schema.llm_registry import load_llm_registry_from_yaml
from fdai.rule_catalog.schema.llm_resolver import (
    CatalogQuery,
    PermissionQuery,
    QuotaQuery,
    ResolvedModels,
    ResolverError,
    collect_narrator,
    resolve,
)

# ---------------------------------------------------------------------------
# Fixture-backed query implementations (offline path)
# ---------------------------------------------------------------------------


class _FixtureCatalog(CatalogQuery):
    """Map of ``{region: [family, family, ...]}``."""

    def __init__(self, data: dict[str, list[str]]) -> None:
        self._by_region = {k: set(v) for k, v in data.items()}

    def families_in_region(self, region: str) -> set[str]:
        return set(self._by_region.get(region, set()))


class _FixturePermission(PermissionQuery):
    """Map of ``{subscription_id: [principal_object_id, ...]}`` for holders of the role."""

    def __init__(self, holders: dict[str, list[str]]) -> None:
        self._by_sub = {k: set(v) for k, v in holders.items()}

    def principal_has_cognitive_services_contributor(
        self, *, subscription_id: str, principal_object_id: str
    ) -> bool:
        return principal_object_id in self._by_sub.get(subscription_id, set())


class _FixtureQuota(QuotaQuery):
    """Map of ``{(region, publisher, family): capacity_tpm}``."""

    def __init__(self, entries: list[dict[str, str | int]]) -> None:
        self._by_key: dict[tuple[str, str, str], int] = {}
        for e in entries:
            self._by_key[(str(e["region"]), str(e["publisher"]), str(e["family"]))] = int(
                e["capacity_tpm"]
            )

    def available_capacity_tpm(self, *, region: str, publisher: str, family: str) -> int:
        return self._by_key.get((region, publisher, family), 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdai-llm-resolver",
        description=(
            "Resolve the LLM capability preferences registry into a "
            "resolved-models.json for the bootstrap flow. Offline-only in "
            "this build; SDK-backed queries land in a later phase."
        ),
    )
    parser.add_argument("--registry", type=Path, required=True, help="Path to llm-registry.yaml")
    parser.add_argument("--region", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--deployer-object-id", required=True)
    parser.add_argument(
        "--catalog-fixture",
        type=Path,
        required=True,
        help="JSON file: {region: [family, ...]} - offline stand-in for the catalog API.",
    )
    parser.add_argument(
        "--permission-fixture",
        type=Path,
        required=True,
        help="JSON file: {subscription_id: [principal_object_id, ...]} - role holders.",
    )
    parser.add_argument(
        "--quota-fixture",
        type=Path,
        required=True,
        help="JSON list: [{region, publisher, family, capacity_tpm}, ...].",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write resolved-models.json here; omit for stdout.",
    )
    parser.add_argument(
        "--narrator-endpoint",
        default=None,
        help=(
            "Azure OpenAI endpoint (https://<name>.openai.azure.com/) used to populate "
            "resolved-models.json's `narrator` + `narrator_candidates` fields. "
            "When omitted the narrator fields are skipped and the read-api chat "
            "backend stays disabled."
        ),
    )
    parser.add_argument(
        "--narrator-api-version",
        default="2024-08-01-preview",
        help="API version stamped on every narrator candidate (default: %(default)s).",
    )
    parser.add_argument(
        "--narrator-capability",
        default="t1.judge",
        help=(
            "Which registry capability's preferences drive narrator candidate "
            "collection (default: %(default)s). All preferences with a family in "
            "the region catalog and non-zero quota become candidates, in preference "
            "order."
        ),
    )
    return parser


def _load_json_file(path: Path) -> object:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        registry = load_llm_registry_from_yaml(args.registry)
    except (OSError, ValueError) as exc:
        print(f"error: failed to load registry: {exc}", file=sys.stderr)
        return 2

    try:
        catalog_data = _load_json_file(args.catalog_fixture)
        permission_data = _load_json_file(args.permission_fixture)
        quota_data = _load_json_file(args.quota_fixture)
    except (OSError, ValueError) as exc:
        print(f"error: failed to load fixture: {exc}", file=sys.stderr)
        return 2

    if not isinstance(catalog_data, dict):
        print(
            "error: --catalog-fixture MUST be a JSON object mapping region -> families",
            file=sys.stderr,
        )
        return 2
    if not isinstance(permission_data, dict):
        print(
            "error: --permission-fixture MUST be a JSON object mapping subscription_id -> holders",
            file=sys.stderr,
        )
        return 2
    if not isinstance(quota_data, list):
        print("error: --quota-fixture MUST be a JSON array of quota entries", file=sys.stderr)
        return 2

    try:
        resolved = resolve(
            registry=registry,
            region=args.region,
            subscription_id=args.subscription_id,
            deployer_object_id=args.deployer_object_id,
            catalog=_FixtureCatalog(catalog_data),
            permission=_FixturePermission(permission_data),
            quota=_FixtureQuota(quota_data),
        )
    except ResolverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Optional: enrich with narrator + narrator_candidates when the caller
    # provided an endpoint. Kept out of ``resolve()`` so the pure resolver
    # stays orthogonal to how the console consumes the output.
    if args.narrator_endpoint:
        winner, candidates = collect_narrator(
            registry=registry,
            region=args.region,
            catalog=_FixtureCatalog(catalog_data),
            quota=_FixtureQuota(quota_data),
            endpoint=args.narrator_endpoint,
            api_version=args.narrator_api_version,
            capability_name=args.narrator_capability,
        )
        resolved = ResolvedModels(
            schema_version=resolved.schema_version,
            region=resolved.region,
            subscription_id=resolved.subscription_id,
            deployer_object_id=resolved.deployer_object_id,
            mixed_model_mode=resolved.mixed_model_mode,
            capabilities=resolved.capabilities,
            narrator=winner,
            narrator_candidates=candidates,
        )

    payload = resolved.to_json()
    if args.out is None:
        sys.stdout.write(payload)
    else:
        args.out.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
