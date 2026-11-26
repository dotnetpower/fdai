"""Run one frozen-scenario Mimir catalog review with no activation authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from fdai.agents import CatalogReviewBindings
from fdai.core.operational_learning import CatalogReviewPublicationReceipt
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.governance_catalog import load_governance_catalog
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.runtime.operational_catalog_review import (
    CatalogReviewCatalog,
    build_protected_operational_catalog_review_bindings,
)
from fdai.runtime.operational_catalog_review_audit import (
    StateStoreAuditedCatalogReviewPublisher,
)
from fdai.runtime.operational_catalog_review_frozen import (
    build_frozen_operational_cases,
    load_frozen_review_manifest,
)
from fdai.runtime.operational_catalog_review_pantheon import (
    CatalogReviewPantheonDependencies,
    build_deployed_catalog_review_dependencies,
    run_catalog_review_pantheon,
)
from fdai.runtime.rule_profile import bind_rule_profile
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_REVISION = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class _CatalogSnapshot(CatalogReviewCatalog):
    action_types: Sequence[OntologyActionType]
    rules: Sequence[Rule]


@dataclass(frozen=True, slots=True)
class CatalogReviewTriggerConfig:
    """Exact deployed inputs for one bounded frozen review."""

    source_revision: str
    frozen_manifest: Path
    timeout_seconds: int

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
        *,
        asset_root: Path,
    ) -> CatalogReviewTriggerConfig:
        if environment.get("FDAI_EXECUTION_VENUE", "").strip() != "deployed":
            raise RuntimeError("catalog review trigger requires the deployed execution venue")
        if environment.get("FDAI_CATALOG_REVIEW_PROTECTED_BINDING", "").strip() != "1":
            raise RuntimeError("catalog review private GitOps binding is unavailable")
        source_revision = environment.get("FDAI_CATALOG_REVIEW_SOURCE_REVISION", "").strip()
        if _REVISION.fullmatch(source_revision) is None:
            raise RuntimeError("catalog review trigger source revision is invalid")
        manifest_value = environment.get("FDAI_CATALOG_REVIEW_FROZEN_MANIFEST", "").strip()
        if not manifest_value:
            raise RuntimeError("catalog review frozen manifest binding is unavailable")
        manifest = Path(manifest_value)
        if manifest.is_absolute() or ".." in manifest.parts:
            raise RuntimeError("catalog review frozen manifest binding is invalid")
        manifest = asset_root / manifest
        timeout_raw = environment.get("FDAI_CATALOG_REVIEW_TIMEOUT_SECONDS", "240").strip()
        try:
            timeout_seconds = int(timeout_raw)
        except ValueError as exc:
            raise RuntimeError("catalog review trigger timeout is invalid") from exc
        if not 1 <= timeout_seconds <= 300:
            raise RuntimeError("catalog review trigger timeout is outside its bounded range")
        return cls(
            source_revision=source_revision,
            frozen_manifest=manifest,
            timeout_seconds=timeout_seconds,
        )


async def run_operational_catalog_review_trigger(
    *,
    environment: Mapping[str, str],
    http_client: httpx.AsyncClient,
    asset_root: Path,
    bindings: CatalogReviewBindings | None = None,
    catalog: CatalogReviewCatalog | None = None,
    dependencies: CatalogReviewPantheonDependencies | None = None,
) -> dict[str, object]:
    """Publish one inert draft through Mimir and return only sanitized evidence."""

    config = CatalogReviewTriggerConfig.from_environment(
        environment,
        asset_root=asset_root,
    )
    manifest, manifest_digest = load_frozen_review_manifest(config.frozen_manifest)
    cases = build_frozen_operational_cases(
        manifest,
        manifest_digest=manifest_digest,
        source_revision=config.source_revision,
    )
    bound_environment = {
        **environment,
        "FDAI_CATALOG_REVIEW_SOURCE_REVISION": config.source_revision,
        "FDAI_CATALOG_REVIEW_EXPECTED_SCENARIO_SET_VERSION": str(manifest["scenario_set_version"]),
    }
    selected_catalog = catalog or _load_catalog(
        catalog_root=asset_root / "rule-catalog",
        policies_root=asset_root / "policies",
        environment=bound_environment,
    )
    selected_bindings = bindings or await build_protected_operational_catalog_review_bindings(
        control_loop=selected_catalog,
        http_client=http_client,
        environment=bound_environment,
        catalog_root=asset_root / "rule-catalog",
        policies_root=asset_root / "policies",
    )
    if selected_bindings is None or selected_bindings.publisher is None:
        raise RuntimeError("catalog review private GitOps binding is unavailable")
    selected_dependencies = dependencies or build_deployed_catalog_review_dependencies(
        environment=dict(bound_environment),
        http_client=http_client,
    )
    audited_bindings = CatalogReviewBindings(
        compiler=selected_bindings.compiler,
        publisher=StateStoreAuditedCatalogReviewPublisher(
            downstream=selected_bindings.publisher,
            state_store=selected_dependencies.state_store,
        ),
    )
    result = await run_catalog_review_pantheon(
        dependencies=selected_dependencies,
        bindings=audited_bindings,
        cases=cases,
        source_revision=config.source_revision,
        timeout_seconds=config.timeout_seconds,
    )
    receipt = _sanitized_receipt(
        publication=result.publication,
        audit_digest=result.audit_digest,
        durable_intent_verified=result.durable_intent_verified,
        durable_terminal_verified=result.durable_terminal_verified,
        source_revision=config.source_revision,
    )
    return receipt


def _load_catalog(
    *,
    catalog_root: Path,
    policies_root: Path,
    environment: Mapping[str, str],
) -> _CatalogSnapshot:
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(catalog_root, schema_registry=registry)
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        policies_root=policies_root,
        remediation_root=catalog_root / "remediation",
    )
    profile = bind_rule_profile(rules, catalog_root=catalog_root, environ=environment)
    active = rules if profile is None else profile.rules
    governance = load_governance_catalog(
        catalog_root,
        known_rule_versions={rule.id: rule.version for rule in rules},
    )
    retired = {item.rule_id for item in governance.retirements if item.mode.value == "retired"}
    return _CatalogSnapshot(
        action_types=ontology.action_types,
        rules=tuple(rule for rule in active if rule.id not in retired),
    )


def _sanitized_receipt(
    *,
    publication: CatalogReviewPublicationReceipt,
    audit_digest: str,
    durable_intent_verified: bool,
    durable_terminal_verified: bool,
    source_revision: str,
) -> dict[str, object]:
    if (
        publication.candidate_digest is None
        or publication.binding_digest is None
        or publication.observation_digest is None
        or publication.head_sha is None
        or publication.review_document_digest is None
        or not publication.required_labels
        or publication.required_labels != publication.observed_labels
        or not {"draft", "shadow", "governance", "catalog-review"}.issubset(
            publication.required_labels
        )
        or not any(label.startswith("rule:") for label in publication.required_labels)
        or not any(label.startswith("action:") for label in publication.required_labels)
        or not durable_intent_verified
        or not durable_terminal_verified
    ):
        raise RuntimeError("catalog review durable publication evidence is incomplete")
    receipt: dict[str, object] = {
        "schema_version": "fdai.operational-catalog-review-trigger-receipt.v3",
        "state": "draft-review-published",
        "source_revision": source_revision,
        "candidate_digest": publication.candidate_digest,
        "package_digest": publication.package_digest,
        "binding_digest": publication.binding_digest,
        "publication_observation_digest": publication.observation_digest,
        "publication_head_sha": publication.head_sha,
        "review_document_digest": publication.review_document_digest,
        "durable_audit_digest": audit_digest,
        "durable_intent_verified": True,
        "durable_terminal_verified": True,
        "review_ref_digest": hashlib.sha256(publication.review_ref.encode()).hexdigest(),
        "already_existed": publication.already_existed,
        "required_labels": list(publication.required_labels),
        "observed_labels": list(publication.observed_labels),
        "draft": True,
        "mode": "shadow",
        "catalog_activation_performed": False,
        "code_path_merge_authority": False,
        "independent_pr_observation_required": True,
        "independent_pr_observation_verified": True,
        "independent_observation_scope": "gitops-pr",
        "managed_resource_mutation_status": "unknown",
        "managed_resource_mutation_performed": None,
        "grants_authority": False,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = _digest(receipt)
    return receipt


def _digest(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _run_from_environment() -> dict[str, object]:
    asset_root = repo_asset_root()
    async with httpx.AsyncClient() as client:
        return await run_operational_catalog_review_trigger(
            environment=os.environ,
            http_client=client,
            asset_root=asset_root,
        )


def main() -> int:
    """Run once and emit one sanitized JSON receipt."""

    try:
        receipt = asyncio.run(_run_from_environment())
    except (OSError, RuntimeError, ValueError, httpx.HTTPError, TimeoutError) as exc:
        print(
            f"operational-catalog-review-trigger: failed ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 3
    print(json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CatalogReviewTriggerConfig",
    "main",
    "run_operational_catalog_review_trigger",
]
