"""Production composition for Mimir operational catalog review packages."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path

import httpx
import yaml

from fdai.agents import CatalogReviewBindings
from fdai.core.control_loop import ControlLoop
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
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_MAX_SCENARIOS = 5_000
_MAX_SCENARIO_BYTES = 1024 * 1024
_PREFIX = "FDAI_CATALOG_REVIEW_"


def build_operational_catalog_review_bindings(
    *,
    control_loop: ControlLoop,
    http_client: httpx.AsyncClient | None,
    environment: Mapping[str, str],
    catalog_root: Path,
    policies_root: Path,
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
            "FDAI_GITOPS_TOKEN",
            "FDAI_GITOPS_OWNER",
            "FDAI_GITOPS_REPO",
        )
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise RuntimeError("catalog review configuration is incomplete: " + ", ".join(missing))
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
        baseline_rules=control_loop.rules,
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
        token=required["FDAI_GITOPS_TOKEN"],
    )
    return CatalogReviewBindings(
        compiler=CatalogCandidateCompiler(
            validator=validator,
            catalog_version=rule_reference_catalog_digest(control_loop.rules),
            schema_version="2.0.0",
        ),
        publisher=GitOpsCatalogReviewPublisher(publisher=gitops),
    )


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


__all__ = ["build_operational_catalog_review_bindings"]
