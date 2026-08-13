#!/usr/bin/env python3
"""Record aggregate-only Azure discovery coverage evidence without tenant identifiers."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.core.discovery.router import BackendEligibility, compile_discovery_routes
from fdai.delivery.azure.discovery_coverage import (
    build_discovery_coverage_receipt,
    discovery_coverage_claims,
    reconcile_discovery_coverage,
)
from fdai.delivery.azure.discovery_explanation import render_coverage_canary_command
from fdai.delivery.azure.discovery_profiles import (
    AZURE_DISCOVERY_CATALOG_VERSION,
    default_azure_discovery_profiles,
)
from fdai.delivery.azure.discovery_receipts import build_provider_coverage_canary_receipt
from fdai_service_contracts.discovery import (
    DiscoveryIntent,
    DiscoveryLimits,
    DiscoveryOperationProfile,
    DiscoveryProfile,
    DiscoveryQueryPlan,
    DiscoveryResultKind,
    DiscoveryScopeKind,
    DiscoveryUniverse,
    discovery_intent_digest,
)
from fdai_service_contracts.discovery_evidence import (
    DiscoveryCoverageReceipt,
    ProviderExecutionReceipt,
)
from fdai_service_contracts.ontology_query import content_digest

_AZURE_CLI_VERSION = "2.87.0"
_RESOURCE_GRAPH_EXTENSION_VERSION = "2.1.1"
_ARG_API_VERSION = "2022-10-01"
_MAX_PROVIDER_TYPES = 256


class CanaryError(RuntimeError):
    """Fail-closed canary error whose message contains no provider response data."""


def _run_az(arguments: list[str], *, stage: str) -> object:
    try:
        completed = subprocess.run(
            ["az", *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CanaryError(f"Azure CLI operation failed during {stage}") from exc
    if completed.returncode != 0:
        raise CanaryError(f"Azure CLI operation failed during {stage}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CanaryError(f"Azure CLI returned invalid JSON during {stage}") from exc


def _verify_context(expected_subscription_id: str) -> tuple[str, str]:
    payload = _run_az(["account", "show", "--output", "json"], stage="context verification")
    if not isinstance(payload, dict):
        raise CanaryError("Azure CLI context response has an invalid shape")
    subscription_id = payload.get("id")
    tenant_id = payload.get("tenantId")
    if (
        subscription_id != expected_subscription_id
        or not isinstance(tenant_id, str)
        or not tenant_id
        or payload.get("state") != "Enabled"
    ):
        raise CanaryError("Azure CLI context does not match the enabled expected subscription")
    return subscription_id, tenant_id


def _verify_versions() -> None:
    payload = _run_az(["version", "--output", "json"], stage="version verification")
    if not isinstance(payload, dict):
        raise CanaryError("Azure CLI version response has an invalid shape")
    extensions = payload.get("extensions")
    if (
        payload.get("azure-cli") != _AZURE_CLI_VERSION
        or not isinstance(extensions, dict)
        or extensions.get("resource-graph") != _RESOURCE_GRAPH_EXTENSION_VERSION
    ):
        raise CanaryError("Azure CLI or Resource Graph extension version does not match the pin")


def _complete_rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        raise CanaryError("Azure Resource Graph response has an invalid shape")
    rows = payload.get("data")
    count = payload.get("count")
    total_records = payload.get("total_records")
    skip_token = payload.get("skip_token")
    if (
        not isinstance(rows, list)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or not isinstance(total_records, int)
        or isinstance(total_records, bool)
        or count != len(rows)
        or total_records != len(rows)
        or skip_token not in {None, ""}
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise CanaryError("Azure Resource Graph response is incomplete or invalid")
    return rows


def _resource_group_count(payload: object) -> int:
    rows = _complete_rows(payload)
    if len(rows) != 1:
        raise CanaryError("Resource-container canary did not return one aggregate row")
    discovered_count = rows[0].get("discovered_count")
    if not isinstance(discovered_count, int) or isinstance(discovered_count, bool):
        raise CanaryError("Resource-container canary count is invalid")
    return discovered_count


def _resource_type_summary(payload: object) -> tuple[int, int, str]:
    rows = _complete_rows(payload)
    counts: list[int] = []
    provider_types: set[str] = set()
    for row in rows:
        provider_type = row.get("type")
        resource_count = row.get("resource_count")
        if (
            not isinstance(provider_type, str)
            or not provider_type
            or not isinstance(resource_count, int)
            or isinstance(resource_count, bool)
        ):
            raise CanaryError("ARM-resource canary aggregate row is invalid")
        provider_types.add(provider_type.casefold())
        counts.append(resource_count)
    if len(provider_types) != len(rows) or len(provider_types) > _MAX_PROVIDER_TYPES:
        raise CanaryError("ARM-resource canary provider-type coverage exceeds its bound")
    return sum(counts), len(provider_types), content_digest(tuple(sorted(provider_types)))


def _coverage_plan(
    *,
    profile: DiscoveryProfile,
    operation: DiscoveryOperationProfile,
    scope_digest: str,
    authorization_ceiling_digest: str,
) -> DiscoveryQueryPlan:
    result_kind = (
        DiscoveryResultKind.COUNT
        if operation.universes == (DiscoveryUniverse.RESOURCE_CONTAINERS,)
        else DiscoveryResultKind.TYPES
    )
    limits = DiscoveryLimits(max_results=1 if result_kind is DiscoveryResultKind.COUNT else 1_000)
    values: dict[str, object] = {
        "result_kind": result_kind,
        "universes": operation.universes,
        "scope_kind": DiscoveryScopeKind.SUBSCRIPTION,
        "scope_digest": scope_digest,
        "predicates": (),
        "limits": limits,
        "include_command_explanation": False,
        "unresolved_modifiers": (),
        "execution_authority": False,
    }
    intent = DiscoveryIntent.model_validate(
        {"intent_digest": discovery_intent_digest(**values), **values}
    )
    eligibility = BackendEligibility(
        operation_id=operation.operation_id,
        available=True,
        complete=True,
        scope_digest=scope_digest,
        predicate_digest=content_digest([]),
        output_schema_id=operation.output_schema_id,
        freshness_seconds=0,
    )
    decision = compile_discovery_routes(
        intent=intent,
        profile=profile,
        authorization_ceiling_digest=authorization_ceiling_digest,
        eligibility=(eligibility,),
    )[0]
    if decision.plan is None:
        raise CanaryError("Registered Azure coverage plan is unavailable")
    return decision.plan


def _query_canary(
    *,
    expected_subscription_id: str,
    plan: DiscoveryQueryPlan,
    operation: DiscoveryOperationProfile,
) -> object:
    _verify_context(expected_subscription_id)
    rendered = render_coverage_canary_command(plan=plan, operation=operation)
    if rendered.kql_template is None:
        raise CanaryError("Registered Azure coverage canary has no query")
    limit = rendered.argv[rendered.argv.index("--first") + 1]
    return _run_az(
        [
            "graph",
            "query",
            "--subscriptions",
            expected_subscription_id,
            "--graph-query",
            rendered.kql_template,
            "--first",
            limit,
            "--output",
            "json",
        ],
        stage=f"{rendered.command_id} execution",
    )


def _evidence_payload(*, expected_subscription_id: str, observed_at: datetime) -> dict[str, Any]:
    subscription_id, tenant_id = _verify_context(expected_subscription_id)
    _verify_versions()
    scope_digest = content_digest(
        {"cloud": "azure", "scope_kind": "subscription", "subscription_id": subscription_id}
    )
    authorization_ceiling_digest = content_digest(
        {
            "identity_profile": "azure.reader",
            "subscription_id": subscription_id,
            "tenant_id": tenant_id,
        }
    )
    profiles = default_azure_discovery_profiles()
    coverage_receipts = []
    execution_receipts = []
    aggregate_proofs = []
    platform_version = (
        f"arg@{_ARG_API_VERSION}+azure-cli@{_AZURE_CLI_VERSION}+"
        f"resource-graph@{_RESOURCE_GRAPH_EXTENSION_VERSION}"
    )
    for profile in profiles:
        operation = next(
            item for item in profile.operations if item.backend.value == "resource_graph"
        )
        plan = _coverage_plan(
            profile=profile,
            operation=operation,
            scope_digest=scope_digest,
            authorization_ceiling_digest=authorization_ceiling_digest,
        )
        raw_aggregate = _query_canary(
            expected_subscription_id=expected_subscription_id,
            plan=plan,
            operation=operation,
        )
        if plan.universes == (DiscoveryUniverse.RESOURCE_CONTAINERS,):
            discovered_count = _resource_group_count(raw_aggregate)
            provider_type_count = 1
            provider_type_set_digest = content_digest((profile.provider_type.casefold(),))
        else:
            discovered_count, provider_type_count, provider_type_set_digest = (
                _resource_type_summary(raw_aggregate)
            )
        execution_receipt = build_provider_coverage_canary_receipt(
            plan=plan,
            operation=operation,
            discovered_count=discovered_count,
        )
        execution_receipts.append(execution_receipt)
        coverage_receipts.append(
            build_discovery_coverage_receipt(
                profile=profile,
                plan=plan,
                execution_receipt=execution_receipt,
                observed_provider_types=(),
                discovered_count=discovered_count,
                platform_version=platform_version,
                source="live_canary",
                observed_at=observed_at,
            )
        )
        aggregate_proofs.append(
            {
                "universe": plan.universes[0].value,
                "discovered_count": discovered_count,
                "provider_type_count": provider_type_count,
                "provider_type_set_digest": provider_type_set_digest,
            }
        )
    reconciliation = reconcile_discovery_coverage(
        claims=discovery_coverage_claims(profiles),
        receipts=tuple(coverage_receipts),
        evaluated_at=observed_at,
        max_age_seconds=3_600,
    )
    if not reconciliation.complete:
        raise CanaryError("Azure discovery coverage reconciliation is incomplete")
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "evidence_kind": "azure_discovery_live_canary",
        "profile_revision": AZURE_DISCOVERY_CATALOG_VERSION,
        "platform_versions": [
            f"azure-resource-graph-api@{_ARG_API_VERSION}",
            f"azure-cli@{_AZURE_CLI_VERSION}",
            f"resource-graph-extension@{_RESOURCE_GRAPH_EXTENSION_VERSION}",
        ],
        "profile_digests": [profile.profile_digest for profile in profiles],
        "generated_at": observed_at.isoformat().replace("+00:00", "Z"),
        "execution_receipts": [item.model_dump(mode="json") for item in execution_receipts],
        "coverage_receipts": [item.model_dump(mode="json") for item in coverage_receipts],
        "aggregate_proofs": aggregate_proofs,
        "reconciliation": {
            "matched_receipt_digests": list(reconciliation.matched_receipt_digests),
            "gaps": [],
            "complete": reconciliation.complete,
            "reconciliation_digest": reconciliation.reconciliation_digest,
            "execution_authority": reconciliation.execution_authority,
        },
        "execution_authority": False,
    }
    payload = {**body, "evidence_digest": content_digest(body)}
    validate_evidence_payload(payload)
    return payload


def validate_evidence_payload(payload: object) -> None:
    """Validate retained evidence against current profiles without provider access."""

    if not isinstance(payload, dict):
        raise CanaryError("Azure discovery evidence has an invalid shape")
    body = {key: value for key, value in payload.items() if key != "evidence_digest"}
    if payload.get("evidence_digest") != content_digest(body):
        raise CanaryError("Azure discovery evidence digest does not match its content")
    profiles = default_azure_discovery_profiles()
    expected_versions = [
        f"azure-resource-graph-api@{_ARG_API_VERSION}",
        f"azure-cli@{_AZURE_CLI_VERSION}",
        f"resource-graph-extension@{_RESOURCE_GRAPH_EXTENSION_VERSION}",
    ]
    if (
        payload.get("schema_version") != "1.0.0"
        or payload.get("evidence_kind") != "azure_discovery_live_canary"
        or payload.get("profile_revision") != AZURE_DISCOVERY_CATALOG_VERSION
        or payload.get("platform_versions") != expected_versions
        or payload.get("profile_digests") != [profile.profile_digest for profile in profiles]
        or payload.get("execution_authority") is not False
    ):
        raise CanaryError("Azure discovery evidence metadata does not match the catalog")
    try:
        generated_at_raw = payload["generated_at"]
        if not isinstance(generated_at_raw, str):
            raise TypeError
        generated_at = datetime.fromisoformat(generated_at_raw.replace("Z", "+00:00"))
        execution_raw = payload["execution_receipts"]
        coverage_raw = payload["coverage_receipts"]
        aggregate_proofs = payload["aggregate_proofs"]
        reconciliation_raw = payload["reconciliation"]
        if (
            not isinstance(execution_raw, list)
            or not isinstance(coverage_raw, list)
            or not isinstance(aggregate_proofs, list)
            or not isinstance(reconciliation_raw, dict)
        ):
            raise TypeError
        executions = tuple(ProviderExecutionReceipt.model_validate(item) for item in execution_raw)
        coverage = tuple(DiscoveryCoverageReceipt.model_validate(item) for item in coverage_raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise CanaryError("Azure discovery evidence contains an invalid receipt") from exc
    if len(executions) != 2 or len(coverage) != 2:
        raise CanaryError("Azure discovery evidence must contain exactly two coverage claims")
    expected_proof_counts = {item.universe.value: item.discovered_count for item in coverage}
    if (
        len(aggregate_proofs) != 2
        or any(
            not isinstance(proof, dict)
            or proof.get("universe") not in expected_proof_counts
            or proof.get("discovered_count") != expected_proof_counts[proof["universe"]]
            or not isinstance(proof.get("provider_type_count"), int)
            or isinstance(proof.get("provider_type_count"), bool)
            or proof["provider_type_count"] < 0
            or not isinstance(proof.get("provider_type_set_digest"), str)
            or not proof["provider_type_set_digest"].startswith("sha256:")
            for proof in aggregate_proofs
        )
        or any(item.observed_provider_types for item in coverage)
    ):
        raise CanaryError("Azure discovery aggregate proof is invalid")
    execution_digests = {item.receipt_digest for item in executions}
    if (
        len(execution_digests) != 2
        or any(item.execution_receipt_digest not in execution_digests for item in coverage)
        or any(item.observed_at != generated_at for item in coverage)
    ):
        raise CanaryError("Azure discovery evidence receipt linkage is invalid")
    reconciliation = reconcile_discovery_coverage(
        claims=discovery_coverage_claims(profiles),
        receipts=coverage,
        evaluated_at=generated_at,
        max_age_seconds=3_600,
    )
    expected_reconciliation = {
        "matched_receipt_digests": list(reconciliation.matched_receipt_digests),
        "gaps": [],
        "complete": True,
        "reconciliation_digest": reconciliation.reconciliation_digest,
        "execution_authority": False,
    }
    if not reconciliation.complete or reconciliation_raw != expected_reconciliation:
        raise CanaryError("Azure discovery evidence reconciliation is invalid")


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    """Verify the active CLI context, run bounded canaries, and write sanitized evidence."""

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--subscription-id")
    mode.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/azure-discovery-live-evidence.json"),
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.validate:
            validate_evidence_payload(json.loads(arguments.output.read_text(encoding="utf-8")))
            print("record-azure-discovery-canary: retained evidence is valid")
            return 0
        if arguments.subscription_id is None:
            raise CanaryError("Azure subscription id is required for live recording")
        payload = _evidence_payload(
            expected_subscription_id=arguments.subscription_id,
            observed_at=datetime.now(UTC),
        )
        _write_atomic(arguments.output, payload)
    except (CanaryError, json.JSONDecodeError, OSError) as exc:
        print(f"record-azure-discovery-canary: {exc}", file=sys.stderr)
        return 1
    print("record-azure-discovery-canary: validated 2 aggregate-only coverage claims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
