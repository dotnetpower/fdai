"""CLI entrypoint for the LLM bootstrap resolver.

Offline-first: the CLI accepts JSON fixture inputs so it is fully
testable without any Azure SDK. Real Azure-backed queries plug in later
via ``--use-azure-sdk`` (deferred - see W-C in
[dev-and-deploy-parity.md](../../../../docs/roadmap/deployment/dev-and-deploy-parity.md)).

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
from typing import Any

from fdai.rule_catalog.schema.llm_registry import load_llm_registry_from_yaml
from fdai.rule_catalog.schema.llm_resolver import (
    CatalogQuery,
    PermissionQuery,
    QuotaQuery,
    ResolvedModels,
    ResolverError,
    collect_narrator,
    collect_narrator_deployments,
    collect_primary_candidates,
    collect_primary_deployments,
    resolve,
)
from fdai.rule_catalog.schema.provisioning_assessment import (
    ProvisioningReport,
    ProvisioningSeverity,
    assess_provisioning,
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
        default=None,
        help="JSON file: {region: [family, ...]} - offline stand-in for the catalog API.",
    )
    parser.add_argument(
        "--permission-fixture",
        type=Path,
        default=None,
        help="JSON file: {subscription_id: [principal_object_id, ...]} - role holders.",
    )
    parser.add_argument(
        "--quota-fixture",
        type=Path,
        default=None,
        help="JSON list: [{region, publisher, family, capacity_tpm}, ...].",
    )
    parser.add_argument(
        "--use-azure-cli",
        action="store_true",
        help=(
            "Query the real Azure catalog / role assignments / quota via the "
            "``az`` CLI instead of fixtures. Requires ``az login`` to have "
            "already produced a valid token; fails-closed on any subprocess or "
            "JSON error. Mutually exclusive with the ``--*-fixture`` flags."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write resolved-models.json here; omit for stdout.",
    )
    parser.add_argument(
        "--assess-fail-on",
        choices=["none", "degraded", "critical"],
        default="none",
        help=(
            "Exit non-zero (3) when the provisioning completeness assessment "
            "reaches this severity (default: none = report to stderr only). "
            "Use 'critical' in CI to block a deploy whose core tier or "
            "mixed-model T2 quorum cannot form."
        ),
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
        "--emit-primary-pool",
        action="store_true",
        help=(
            "Also emit the same-publisher latency pool for t2.reasoner.primary "
            "(``reasoner_primary_candidates`` + one Terraform deployment per "
            "candidate). Requires --narrator-endpoint (the AOAI account endpoint "
            "that hosts the deployments). Opt-in, invariant-safe - see "
            "docs/roadmap/architecture/llm-strategy.md T2 Primary Latency Pool. "
            "Consumed only when llm.t2_primary_latency_routing is enabled."
        ),
    )
    parser.add_argument(
        "--primary-api-version",
        default="2024-06-01",
        help="API version stamped on every primary pool candidate (default: %(default)s).",
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


class _ArgValidationError(ValueError):
    """Raised when CLI arg combinations are inconsistent (mutex, missing, ...)."""


def _build_queries(
    args: argparse.Namespace,
) -> tuple[CatalogQuery, PermissionQuery, QuotaQuery]:
    """Build the three resolver queries from either fixtures or the az CLI.

    Two modes are mutually exclusive:

    - **fixture mode** (default): all three ``--*-fixture`` paths MUST
      be provided; each is JSON-decoded and wrapped in the local
      ``_Fixture*`` classes. Used by CI + offline dev.
    - **az CLI mode** (``--use-azure-cli``): the three fixture flags
      MUST be omitted; each query hits ``az cognitiveservices ...`` /
      ``az role assignment ...`` via
      :mod:`fdai.delivery.azure.llm.resolver_queries`. Requires an
      existing ``az login`` (respects ``AZURE_CONFIG_DIR``).
    """
    fixture_flags = [args.catalog_fixture, args.permission_fixture, args.quota_fixture]
    fixtures_given = any(f is not None for f in fixture_flags)
    if args.use_azure_cli and fixtures_given:
        raise _ArgValidationError(
            "--use-azure-cli is mutually exclusive with --catalog-fixture / "
            "--permission-fixture / --quota-fixture"
        )
    if not args.use_azure_cli and not all(f is not None for f in fixture_flags):
        raise _ArgValidationError(
            "fixture mode requires --catalog-fixture, --permission-fixture, "
            "and --quota-fixture (or pass --use-azure-cli)"
        )
    if args.use_azure_cli:
        from fdai.delivery.azure.llm.resolver_queries import (
            AzureCliCatalogQuery,
            AzureCliPermissionQuery,
            AzureCliQuotaQuery,
        )

        return AzureCliCatalogQuery(), AzureCliPermissionQuery(), AzureCliQuotaQuery()

    catalog_data = _load_json_file(args.catalog_fixture)
    permission_data = _load_json_file(args.permission_fixture)
    quota_data = _load_json_file(args.quota_fixture)
    if not isinstance(catalog_data, dict):
        raise _ArgValidationError(
            "--catalog-fixture MUST be a JSON object mapping region -> families"
        )
    if not isinstance(permission_data, dict):
        raise _ArgValidationError(
            "--permission-fixture MUST be a JSON object mapping subscription_id -> holders"
        )
    if not isinstance(quota_data, list):
        raise _ArgValidationError("--quota-fixture MUST be a JSON array of quota entries")
    return (
        _FixtureCatalog(catalog_data),
        _FixturePermission(permission_data),
        _FixtureQuota(quota_data),
    )


_SEVERITY_RANK: dict[ProvisioningSeverity, int] = {
    ProvisioningSeverity.OK: 0,
    ProvisioningSeverity.DEGRADED: 1,
    ProvisioningSeverity.CRITICAL: 2,
}


def _print_assessment(report: ProvisioningReport) -> None:
    """Report the provisioning completeness assessment to stderr.

    A ``critical`` roll-up is prefixed ``A2 alert:`` - the same operational
    category the runtime uses when a resolved deployment is silently
    missing its T2 quorum. Never touches stdout (which carries the JSON).
    """

    prefix = "A2 alert: " if report.severity is ProvisioningSeverity.CRITICAL else ""
    print(
        f"{prefix}provisioning assessment: severity={report.severity.value} "
        f"quorum_ok={report.quorum_ok}",
        file=sys.stderr,
    )
    for cap in report.degraded:
        print(
            f"  - {cap.name} [{cap.tier.value}] {cap.state.value}: {cap.impact}",
            file=sys.stderr,
        )


def _assessment_exit_code(report: ProvisioningReport, fail_on: str) -> int:
    if fail_on == "none":
        return 0
    threshold = (
        ProvisioningSeverity.CRITICAL if fail_on == "critical" else ProvisioningSeverity.DEGRADED
    )
    if _SEVERITY_RANK[report.severity] >= _SEVERITY_RANK[threshold]:
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        registry = load_llm_registry_from_yaml(args.registry)
    except (OSError, ValueError) as exc:
        print(f"error: failed to load registry: {exc}", file=sys.stderr)
        return 2

    try:
        catalog_query, permission_query, quota_query = _build_queries(args)
    except _ArgValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        resolved = resolve(
            registry=registry,
            region=args.region,
            subscription_id=args.subscription_id,
            deployer_object_id=args.deployer_object_id,
            catalog=catalog_query,
            permission=permission_query,
            quota=quota_query,
        )
    except ResolverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Optional: enrich with narrator + narrator_candidates when the caller
    # provided an endpoint. Kept out of ``resolve()`` so the pure resolver
    # stays orthogonal to how the console consumes the output.
    narrator_winner = None
    narrator_candidates: tuple[Any, ...] = ()
    primary_candidates: tuple[Any, ...] = ()
    extra_deployments: tuple[Any, ...] = ()
    if args.narrator_endpoint:
        narrator_winner, narrator_candidates = collect_narrator(
            registry=registry,
            region=args.region,
            catalog=catalog_query,
            quota=quota_query,
            endpoint=args.narrator_endpoint,
            api_version=args.narrator_api_version,
            capability_name=args.narrator_capability,
        )
        # Terraform-side companion: one ResolvedCapability per candidate so
        # ``azurerm_cognitive_deployment`` gets created for each family the
        # router might pick. Merged into the existing capabilities list;
        # the LLM module iterates for_each without additional wiring.
        extra_deployments = collect_narrator_deployments(
            registry=registry,
            region=args.region,
            catalog=catalog_query,
            quota=quota_query,
            capability_name=args.narrator_capability,
        )

    if args.emit_primary_pool:
        if not args.narrator_endpoint:
            print(
                "error: --emit-primary-pool requires --narrator-endpoint "
                "(the AOAI account endpoint that hosts the pool deployments)",
                file=sys.stderr,
            )
            return 2
        try:
            _primary_winner, primary_candidates = collect_primary_candidates(
                registry=registry,
                region=args.region,
                catalog=catalog_query,
                quota=quota_query,
                endpoint=args.narrator_endpoint,
                api_version=args.primary_api_version,
            )
            extra_deployments = extra_deployments + collect_primary_deployments(
                registry=registry,
                region=args.region,
                catalog=catalog_query,
                quota=quota_query,
            )
        except ResolverError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    if args.narrator_endpoint or args.emit_primary_pool:
        resolved = ResolvedModels(
            schema_version=resolved.schema_version,
            region=resolved.region,
            subscription_id=resolved.subscription_id,
            deployer_object_id=resolved.deployer_object_id,
            mixed_model_mode=resolved.mixed_model_mode,
            capabilities=resolved.capabilities + extra_deployments,
            narrator=narrator_winner,
            narrator_candidates=narrator_candidates,
            reasoner_primary_candidates=primary_candidates,
        )

    report = assess_provisioning(registry=registry, resolved=resolved)
    _print_assessment(report)

    payload = resolved.to_json()
    if args.out is None:
        sys.stdout.write(payload)
    else:
        args.out.write_text(payload, encoding="utf-8")
    return _assessment_exit_code(report, args.assess_fail_on)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
