"""Production composition for Mimir operational catalog review packages."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

import httpx
import yaml
from fdai_github_app_auth import GitHubAppTokenProvider, TokenProvider

from fdai.agents import CatalogReviewBindings
from fdai.core.operational_learning import CatalogCandidateCompiler
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator
from fdai.delivery.gitops_pr import (
    DeterministicCatalogValidator,
    GitOpsCatalogReviewPublisher,
    GitOpsPrAdapter,
    GitOpsPrConfig,
)
from fdai.rule_catalog.schema.catalog_search import rule_reference_catalog_digest
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.runtime.catalog_review_github import verify_catalog_review_github_app
from fdai.runtime.github_auth import build_github_token_provider
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_MAX_SCENARIOS = 5_000
_MAX_SCENARIO_BYTES = 1024 * 1024
_PREFIX = "FDAI_CATALOG_REVIEW_"
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class CatalogReviewCatalog(Protocol):
    """Catalog projection required by the review-only compiler."""

    @property
    def action_types(self) -> Sequence[OntologyActionType]: ...

    @property
    def rules(self) -> Sequence[Rule]: ...


def build_operational_catalog_review_bindings(
    *,
    control_loop: CatalogReviewCatalog,
    http_client: httpx.AsyncClient | None,
    environment: Mapping[str, str],
    catalog_root: Path,
    policies_root: Path,
    token_provider: TokenProvider | None = None,
    verified_binding_digest: str | None = None,
) -> CatalogReviewBindings | None:
    """Build O3 bindings only from one complete deployment configuration."""
    enabled = environment.get("FDAI_CATALOG_REVIEW_ENABLED", "").strip().casefold()
    configured = any(
        value.strip()
        for key, value in environment.items()
        if key.startswith(_PREFIX) and key != "FDAI_CATALOG_REVIEW_ENABLED"
    )
    if enabled not in {"", "0", "false", "no", "off", "1", "true", "yes", "on"}:
        raise RuntimeError("FDAI_CATALOG_REVIEW_ENABLED has an invalid boolean value")
    if enabled not in {"1", "true", "yes", "on"}:
        if configured:
            raise RuntimeError("catalog review settings require FDAI_CATALOG_REVIEW_ENABLED=1")
        return None
    if http_client is None:
        raise RuntimeError("catalog review requires the shared HTTP client")
    required = {
        name: environment.get(name, "").strip()
        for name in (
            "FDAI_CATALOG_REVIEW_SCENARIO_DIR",
            "FDAI_CATALOG_REVIEW_SCENARIO_SET_ID",
            "FDAI_CATALOG_REVIEW_POLICY_VERSION",
            "FDAI_GITOPS_OWNER",
            "FDAI_GITOPS_REPO",
        )
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise RuntimeError("catalog review configuration is incomplete: " + ", ".join(missing))
    source_revision = environment.get("FDAI_CATALOG_REVIEW_SOURCE_REVISION", "").strip()
    if source_revision and _REVISION.fullmatch(source_revision) is None:
        raise RuntimeError("catalog review source revision is invalid")
    expected_scenario_set = environment.get(
        "FDAI_CATALOG_REVIEW_EXPECTED_SCENARIO_SET_VERSION", ""
    ).strip()
    if expected_scenario_set and _IDENTIFIER.fullmatch(expected_scenario_set) is None:
        raise RuntimeError("catalog review expected scenario set is invalid")
    selected_token_provider = token_provider or build_github_token_provider(
        environment,
        http_client=http_client,
        repository=required["FDAI_GITOPS_REPO"],
        permissions=(
            ("contents", "write"),
            ("issues", "write"),
            ("metadata", "read"),
            ("pull_requests", "write"),
        ),
    )
    if selected_token_provider is None:
        raise RuntimeError("catalog review private GitOps credential binding is unavailable")
    scenario_dir = Path(required["FDAI_CATALOG_REVIEW_SCENARIO_DIR"])
    if not scenario_dir.is_absolute():
        scenario_dir = catalog_root.parent / scenario_dir
    scenarios = _load_scenarios(scenario_dir)
    registry = PackageResourceSchemaRegistry()
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    validator = DeterministicCatalogValidator(
        schema_registry=registry,
        action_type_names=frozenset(item.name for item in control_loop.action_types),
        resource_type_ids=frozenset(item.id for item in resource_types),
        baseline_rules=tuple(control_loop.rules),
        scenarios=scenarios,
        scenario_set_id=required["FDAI_CATALOG_REVIEW_SCENARIO_SET_ID"],
        replay_version="operational-catalog-replay-v1",
        policy_version=required["FDAI_CATALOG_REVIEW_POLICY_VERSION"],
        evaluator=OpaRegoEvaluator(policies_root=policies_root),
    )
    gitops = GitOpsPrAdapter(
        config=GitOpsPrConfig(
            owner=required["FDAI_GITOPS_OWNER"],
            repo=required["FDAI_GITOPS_REPO"],
            default_branch=(
                environment.get("FDAI_GITOPS_DEFAULT_BRANCH", "main").strip() or "main"
            ),
            branch_prefix="fdai/catalog-review",
            api_base=(
                environment.get(
                    "FDAI_GITOPS_API_BASE",
                    "https://api.github.com",
                ).strip()
                or "https://api.github.com"
            ),
        ),
        http_client=http_client,
        token_provider=selected_token_provider,
    )
    return CatalogReviewBindings(
        compiler=CatalogCandidateCompiler(
            validator=validator,
            catalog_version=rule_reference_catalog_digest(tuple(control_loop.rules)),
            schema_version="2.0.0",
            expected_fdai_revision=source_revision or None,
            expected_scenario_set_version=expected_scenario_set or None,
        ),
        publisher=GitOpsCatalogReviewPublisher(
            publisher=gitops,
            binding_digest=verified_binding_digest,
        ),
    )


async def build_protected_operational_catalog_review_bindings(
    *,
    control_loop: CatalogReviewCatalog,
    http_client: httpx.AsyncClient,
    environment: Mapping[str, str],
    catalog_root: Path,
    policies_root: Path,
) -> CatalogReviewBindings:
    """Build the one-shot path only after exact GitHub App scope readback."""

    if environment.get("FDAI_GITOPS_TOKEN", "").strip():
        raise RuntimeError("protected catalog review rejects static-token compatibility")
    owner = environment.get("FDAI_GITOPS_OWNER", "").strip()
    repo = environment.get("FDAI_GITOPS_REPO", "").strip()
    api_base = (
        environment.get("FDAI_GITOPS_API_BASE", "https://api.github.com").strip()
        or "https://api.github.com"
    )
    provider = build_github_token_provider(
        environment,
        http_client=http_client,
        repository=repo,
        permissions=(
            ("contents", "write"),
            ("issues", "write"),
            ("metadata", "read"),
            ("pull_requests", "write"),
        ),
    )
    if not owner or not repo or not isinstance(provider, GitHubAppTokenProvider):
        raise RuntimeError("protected catalog review requires GitHub App credentials")
    binding_digest = await verify_catalog_review_github_app(
        provider=provider,
        http_client=http_client,
        owner=owner,
        repo=repo,
        api_base=api_base,
    )
    bindings = build_operational_catalog_review_bindings(
        control_loop=control_loop,
        http_client=http_client,
        environment=environment,
        catalog_root=catalog_root,
        policies_root=policies_root,
        token_provider=provider,
        verified_binding_digest=binding_digest,
    )
    if bindings is None:
        raise RuntimeError("protected catalog review binding is disabled")
    return bindings


def _load_scenarios(directory: Path) -> tuple[dict[str, object], ...]:
    if not directory.is_dir():
        raise RuntimeError("catalog review scenario directory is unavailable")
    paths = sorted(directory.glob("*.json"))
    if not paths or len(paths) > _MAX_SCENARIOS:
        raise RuntimeError("catalog review scenario count is outside its bounded range")
    scenarios: list[dict[str, object]] = []
    for path in paths:
        value = json.loads(_read_bounded_scenario(path))
        if not isinstance(value, dict):
            raise RuntimeError("catalog review scenario MUST be a JSON object")
        scenarios.append(value)
    return tuple(scenarios)


def _read_bounded_scenario(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("catalog review scenario MUST be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("catalog review scenario MUST be a regular file")
        if metadata.st_size > _MAX_SCENARIO_BYTES:
            raise RuntimeError("catalog review scenario exceeds its byte limit")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            value = stream.read(_MAX_SCENARIO_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(value.encode("utf-8")) > _MAX_SCENARIO_BYTES:
        raise RuntimeError("catalog review scenario exceeds its byte limit")
    return value


__all__ = [
    "build_operational_catalog_review_bindings",
    "build_protected_operational_catalog_review_bindings",
]
