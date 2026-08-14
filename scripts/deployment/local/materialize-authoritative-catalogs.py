#!/usr/bin/env python3
"""Materialize immutable repository catalog projections for the Operator API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from fdai.agents import PANTHEON_SPECS
from fdai.core.ontology_explorer import render_ontology_mermaid
from fdai.delivery.ontology_console_projection import (
    build_catalog_topology,
    semantic_model_profile,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

RULE_LIST_KEY = "operator-projection:workflow:rule.list"
ONTOLOGY_GRAPH_KEY = "operator-projection:operations:ontology.graph"
MAX_BODY_BYTES = 512_000
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def catalog_snapshots(repo_root: Path) -> dict[str, dict[str, object]]:
    """Load reviewed declarations and return deterministic JSON-only projections."""
    catalog_root = repo_root / "rule-catalog"
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        catalog_root,
        schema_registry=registry,
        probes_root=catalog_root / "probes",
    )
    resource_type_documents = _mapping_list(
        _yaml_mapping(catalog_root / "vocabulary/resource-types.yaml").get("types"),
        field="resource-types.types",
    )
    resource_types = load_resource_type_registry_from_mapping(
        _yaml_mapping(catalog_root / "vocabulary/resource-types.yaml")
    )
    signal_types = load_signal_type_registry_from_mapping(
        _yaml_mapping(catalog_root / "vocabulary/signal-types.yaml")
    )
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
        policies_root=repo_root / "policies",
        remediation_root=catalog_root / "remediation",
    )
    rule_documents = [
        _yaml_mapping(path) for path in sorted((catalog_root / "catalog").glob("*.yaml"))
    ]
    workflow_documents = [
        _yaml_mapping(path) for path in sorted((catalog_root / "workflows").glob("*.yaml"))
    ]
    agent_documents = [
        {
            "name": spec.name,
            "layer": spec.layer.value,
            "reports_to": spec.reports_to,
            "owns": sorted(spec.owns),
            "actions": sorted(set(spec.executes) | set(spec.initiates)),
        }
        for spec in PANTHEON_SPECS
    ]
    return {
        RULE_LIST_KEY: _revisioned(
            _rule_snapshot(
                rules,
                policies_root=repo_root / "policies",
                remediation_root=catalog_root / "remediation",
            )
        ),
        ONTOLOGY_GRAPH_KEY: _revisioned(
            _ontology_snapshot(
                ontology,
                resource_types=resource_type_documents,
                rules=rule_documents,
                workflows=workflow_documents,
                agents=agent_documents,
            )
        ),
    }


def _rule_snapshot(
    rules: Sequence[Rule],
    *,
    policies_root: Path,
    remediation_root: Path,
) -> dict[str, object]:
    ordered = sorted(
        rules,
        key=lambda rule: (-_SEVERITY_RANK.get(rule.severity.value, 0), rule.id),
    )
    summaries = [_rule_summary(rule) for rule in ordered]
    details = {
        f"active:{rule.id}": _rule_detail(
            rule,
            policies_root=policies_root,
            remediation_root=remediation_root,
        )
        for rule in sorted(rules, key=lambda item: item.id)
    }
    return {"rules": summaries, "details": details}


def _rule_summary(rule: Rule) -> dict[str, object]:
    provenance = rule.provenance
    return {
        "id": rule.id,
        "origin": "active",
        "version": str(rule.version),
        "source": rule.source.value,
        "severity": rule.severity.value,
        "category": rule.category.value,
        "resource_type": rule.resource_type,
        "check_logic": rule.check_logic.model_dump(mode="json"),
        "remediation": rule.remediation.model_dump(mode="json"),
        "remediates": rule.remediates,
        "provenance": {
            "source_url": provenance.source_url,
            "license": provenance.license,
            "redistribution": provenance.redistribution.value,
        },
    }


def _rule_detail(
    rule: Rule,
    *,
    policies_root: Path,
    remediation_root: Path,
) -> dict[str, object]:
    check_logic_body = _read_reference(
        policies_root,
        rule.check_logic.reference,
        prefix="policies/",
    )
    detail = _rule_summary(rule)
    detail.update(
        {
            "schema_version": str(rule.schema_version),
            "alternatives": list(rule.alternatives),
            "parameters": dict(rule.parameters),
            "applies_to": {"resource_types": list(rule.applies_to)},
            "check_logic_body": check_logic_body,
            "remediation_body": _read_reference(
                remediation_root,
                rule.remediation.template_ref,
                prefix="remediation/",
            ),
            "explanation": _rule_explanation(rule, check_logic_body),
            "provenance": rule.provenance.model_dump(mode="json"),
        }
    )
    return detail


def _rule_explanation(rule: Rule, check_logic_body: str | None) -> dict[str, object]:
    metadata = _rego_metadata(check_logic_body) if check_logic_body else None
    if metadata and (metadata.get("title") or metadata.get("description")):
        return {
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "source": "rego_metadata",
            "details": {},
        }
    parameters = rule.parameters
    if "azure_policy_display_name" in parameters:
        return {
            "title": parameters.get("azure_policy_display_name"),
            "description": None,
            "source": "azure_policy",
            "details": {
                key: parameters[key]
                for key in ("azure_policy_effect_default", "azure_policy_category")
                if parameters.get(key) is not None
            },
        }
    if "kube_bench_id" in parameters:
        return {
            "title": (
                f"CIS {parameters.get('kube_bench_ruleset', '')} "
                f"{parameters.get('kube_bench_id', '')}"
            ).strip(),
            "description": None,
            "source": "kube_bench",
            "details": {
                key: parameters[key]
                for key in ("kube_bench_audit", "kube_bench_scored")
                if parameters.get(key) is not None
            },
        }
    return {"title": None, "description": None, "source": None, "details": {}}


def _rego_metadata(body: str) -> Mapping[str, Any] | None:
    lines = body.splitlines()
    try:
        start = next(
            index + 1
            for index, line in enumerate(lines)
            if line.strip() in {"# METADATA", "#METADATA"}
        )
    except StopIteration:
        return None
    collected: list[str] = []
    for line in lines[start:]:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            break
        content = stripped[1:]
        collected.append(content[1:] if content.startswith(" ") else content)
    if not collected:
        return None
    try:
        parsed = yaml.safe_load("\n".join(collected))
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _read_reference(root: Path, reference: str, *, prefix: str) -> str | None:
    if not reference.startswith(prefix):
        return None
    relative = Path(reference.removeprefix(prefix))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
        return None
    try:
        with candidate.open("rb") as stream:
            raw = stream.read(MAX_BODY_BYTES + 1)
    except OSError:
        return None
    truncated = len(raw) > MAX_BODY_BYTES
    body = raw[:MAX_BODY_BYTES].decode("utf-8", errors="replace")
    return body + "\n... [truncated]" if truncated else body


def _ontology_snapshot(
    ontology: OntologyCatalog,
    *,
    resource_types: Sequence[Mapping[str, object]],
    rules: Sequence[Mapping[str, object]],
    workflows: Sequence[Mapping[str, object]],
    agents: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    object_types = sorted(ontology.object_types, key=lambda item: item.name)
    interface_types = sorted(ontology.interface_types, key=lambda item: item.name)
    link_types = sorted(ontology.link_types, key=lambda item: item.name)
    action_types = sorted(ontology.action_types, key=lambda item: item.name)
    function_types = sorted(ontology.function_types, key=lambda item: item.name)
    release = ontology.build_release()
    rendered = render_ontology_mermaid(object_types, link_types)
    return {
        "schema_version": "2.0.0",
        "ontology_release_digest": release.digest,
        "mutation_authority": False,
        "semantic_model": semantic_model_profile(ontology),
        "catalog_topology": build_catalog_topology(
            ontology=ontology,
            resource_types=resource_types,
            rules=rules,
            workflows=workflows,
            agents=agents,
        ),
        "mermaid": rendered.mermaid,
        "object_type_count": len(object_types),
        "interface_type_count": len(interface_types),
        "link_type_count": len(link_types),
        "action_type_count": len(action_types),
        "function_type_count": len(function_types),
        "object_types": [item.name for item in object_types],
        "interface_types": [
            item.model_dump(mode="json", exclude_none=True) for item in interface_types
        ],
        "link_types": [item.name for item in link_types],
        "action_types": [item.model_dump(mode="json", exclude_none=True) for item in action_types],
        "function_types": [
            item.model_dump(mode="json", exclude_none=True) for item in function_types
        ],
        "nodes": [
            {
                "name": item.name,
                "key": item.key,
                "property_count": len(item.properties),
                "properties": sorted(item.properties),
                "description": item.description,
                "lifecycle": (
                    item.lifecycle.model_dump(mode="json", exclude_none=True)
                    if item.lifecycle is not None
                    else None
                ),
            }
            for item in object_types
        ],
        "edges": [
            {
                "name": item.name,
                "from_type": item.from_type,
                "to_type": item.to_type,
                "cardinality": item.cardinality.value,
                "is_transitive": item.is_transitive,
                "is_causal": item.is_causal,
                "temporal_order": item.temporal_order,
                "description": item.description,
            }
            for item in link_types
        ],
    }


def _revisioned(payload: dict[str, object]) -> dict[str, object]:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {"_revision": "sha256:" + hashlib.sha256(encoded).hexdigest(), **payload}


def _yaml_mapping(path: Path) -> Mapping[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise RuntimeError(f"catalog document MUST be a mapping: {path}")
    return raw


def _mapping_list(value: object, *, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise RuntimeError(f"{field} MUST be a list of mappings")
    return value


async def materialize(repo_root: Path) -> None:
    """Write both immutable snapshots to their Operator projection keys."""
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN MUST be configured")
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    for key, payload in catalog_snapshots(repo_root).items():
        await store.write_state(key, payload)


def main() -> int:
    """Materialize repository catalogs without emitting deployment values."""
    repo_root = Path(__file__).resolve().parents[3]
    asyncio.run(materialize(repo_root))
    print("authoritative Rule and ontology catalog projections refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
