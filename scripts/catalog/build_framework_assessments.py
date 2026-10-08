#!/usr/bin/env python3
"""Build reviewed WAF and CAF assessment catalogs from pinned source catalogs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.framework_assessment import canonical_digest
from fdai.rule_catalog.schema.framework_catalog import FrameworkDefinition, load_framework_catalog

_DEFAULT_FRESHNESS_DAYS = {
    "rule": 1,
    "artifact": 180,
    "metric": 30,
    "drill": 365,
    "approval": 180,
    "observation": 1,
}
_PRODUCERS = {
    "rule": "t0-rule-evaluator",
    "artifact": "architecture-review-evidence-provider",
    "metric": "architecture-review-evidence-provider",
    "drill": "architecture-review-evidence-provider",
    "approval": "human-approval-ledger",
    "observation": "estate-observation-provider",
}


def _load_yaml_object(path: Path) -> dict[str, Any]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML object")
    return raw


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _source_revision_digest(framework: FrameworkDefinition) -> str:
    return canonical_digest(
        sorted({resolved.resolved_ref for resolved in framework.resolved_controls()})
    )


def _requirement_id(kind: str, source_ref: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in ".:-" else "-"
        for character in source_ref.casefold()
    ).strip("-")
    return f"{kind}:{normalized}"


def _crosswalk_key(item: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(item["target_kind"]),
        str(item.get("target_ref") or ""),
        str(item["relationship"]),
    )


def _specification_digest(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "specification_digest": canonical_digest(value)}


def _catalog_digest(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "catalog_digest": canonical_digest(value)}


def build_waf_catalog(
    *,
    framework: FrameworkDefinition,
    framework_path: Path,
    best_practice_root: Path,
) -> dict[str, Any]:
    """Derive strict evidence specifications from every pinned WAF BestPractice."""

    practices = load_best_practice_catalog(best_practice_root, strict=False)
    by_control = {
        practice.control_id: practice
        for practice in practices
        if practice.framework == framework.id
    }
    controls: list[dict[str, Any]] = []
    for resolved in framework.resolved_controls():
        source = resolved.control
        practice = by_control.get(source.id)
        if practice is None:
            raise ValueError(f"WAF control {source.id!r} has no BestPractice")
        owner_slots = sorted(
            {
                requirement.ref
                for requirement in practice.requirements
                if requirement.kind.value == "approval"
            }
        )
        if not owner_slots:
            raise ValueError(f"WAF control {source.id!r} has no accountable approval requirement")
        primary_owner = owner_slots[0]
        evidence: list[dict[str, Any]] = []
        crosswalk: list[dict[str, object]] = [
            {
                "target_kind": "best_practice",
                "target_ref": f"{practice.id}@{practice.version}",
                "relationship": "full",
            }
        ]
        for requirement in practice.requirements:
            kind = requirement.kind.value
            freshness_days = requirement.freshness_days or _DEFAULT_FRESHNESS_DAYS[kind]
            evidence.append(
                {
                    "requirement_id": _requirement_id(kind, requirement.ref),
                    "kind": kind,
                    "source_ref": requirement.ref,
                    "authoritative_producer": _PRODUCERS[kind],
                    "blocked_dependency": None,
                    "scope_contract": "exact-workload",
                    "generation_contract": "inventory" if kind == "rule" else "none",
                    "freshness_ceiling_seconds": freshness_days * 86_400,
                    "completeness_required": True,
                    "owner_slot": (requirement.ref if kind == "approval" else primary_owner),
                    "approval_roles": sorted({primary_owner, "framework-assessment-approver"}),
                    "failure_behavior": "unknown",
                    "evidence_role": "decisive",
                    "process_phase": "none",
                }
            )
            crosswalk.append(
                {
                    "target_kind": "rule" if kind == "rule" else "manual_evidence",
                    "target_ref": requirement.ref,
                    "relationship": "partial",
                }
            )
        for objective_ref in source.objective_refs:
            crosswalk.append(
                {
                    "target_kind": "control_objective",
                    "target_ref": objective_ref,
                    "relationship": "partial",
                }
            )
        specification = {
            "control_id": source.id,
            "title": source.title,
            "area": resolved.area or practice.category.value,
            "requirement_mode": practice.requirement_mode.value,
            "cadence_days": min(item["freshness_ceiling_seconds"] // 86_400 for item in evidence),
            "owner_slot": primary_owner,
            "evidence": sorted(evidence, key=lambda item: str(item["requirement_id"])),
            "crosswalk": sorted(
                {json.dumps(item, sort_keys=True): item for item in crosswalk}.values(),
                key=_crosswalk_key,
            ),
            "reviewer": "fdai-maintainers",
            "review_state": "reviewed",
        }
        controls.append(_specification_digest(specification))
    if len(by_control) != 59 or len(controls) != 59:
        raise ValueError("WAF assessment requires exactly 59 controls")
    catalog = {
        "schema_version": "1.0.0",
        "framework_id": framework.id,
        "framework_version": framework.version,
        "framework_scope": framework.scope,
        "source_revision_digest": _source_revision_digest(framework),
        "framework_definition_digest": _file_digest(framework_path),
        "expected_control_count": 59,
        "controls": sorted(controls, key=lambda item: str(item["control_id"])),
        "reviewer": "fdai-maintainers",
        "review_state": "reviewed",
    }
    return _catalog_digest(catalog)


def build_caf_catalog(
    *,
    framework: FrameworkDefinition,
    framework_path: Path,
    source_path: Path,
) -> dict[str, Any]:
    """Merge authored CAF evidence specifications with the pinned 15-area catalog."""

    source = _load_yaml_object(source_path)
    if source.get("framework_id") != framework.id or source.get("review_state") != "reviewed":
        raise ValueError("CAF assessment source identity or review state is invalid")
    defaults = source.get("defaults")
    controls_source = source.get("controls")
    if not isinstance(defaults, dict) or not isinstance(controls_source, dict):
        raise ValueError("CAF assessment source defaults and controls are required")
    resolved_by_id = {item.control.id: item for item in framework.resolved_controls()}
    if set(controls_source) != set(resolved_by_id) or len(resolved_by_id) != 15:
        raise ValueError("CAF assessment source MUST exactly cover 15 framework controls")

    controls: list[dict[str, Any]] = []
    for control_id in sorted(resolved_by_id):
        authored = controls_source[control_id]
        if not isinstance(authored, dict):
            raise ValueError(f"CAF control {control_id!r} source is malformed")
        owner_slot = str(authored["owner_slot"])
        evidence_source = authored.get("evidence")
        crosswalk_source = authored.get("crosswalk")
        if not isinstance(evidence_source, list) or not isinstance(crosswalk_source, list):
            raise ValueError(f"CAF control {control_id!r} evidence and crosswalk are required")
        evidence: list[dict[str, Any]] = []
        for raw in evidence_source:
            if not isinstance(raw, dict):
                raise ValueError(f"CAF control {control_id!r} evidence is malformed")
            kind = str(raw["kind"])
            source_ref = str(raw["source_ref"])
            evidence.append(
                {
                    "requirement_id": _requirement_id(kind, source_ref),
                    "kind": kind,
                    "source_ref": source_ref,
                    "authoritative_producer": raw.get(
                        "authoritative_producer",
                        defaults["authoritative_producer"],
                    ),
                    "blocked_dependency": raw.get("blocked_dependency"),
                    "scope_contract": defaults["scope_contract"],
                    "generation_contract": defaults["generation_contract"],
                    "freshness_ceiling_seconds": int(
                        raw.get(
                            "freshness_ceiling_seconds",
                            int(authored["cadence_days"]) * 86_400,
                        )
                    ),
                    "completeness_required": True,
                    "owner_slot": owner_slot,
                    "approval_roles": defaults["approval_roles"],
                    "failure_behavior": defaults["failure_behavior"],
                    "evidence_role": raw.get("evidence_role", "decisive"),
                    "process_phase": raw.get("process_phase", "none"),
                }
            )
        crosswalk = sorted(
            (dict(item) for item in crosswalk_source if isinstance(item, dict)),
            key=_crosswalk_key,
        )
        resolved = resolved_by_id[control_id]
        specification = {
            "control_id": control_id,
            "title": resolved.control.title,
            "area": resolved.area or "methodology",
            "requirement_mode": "all",
            "cadence_days": authored["cadence_days"],
            "owner_slot": owner_slot,
            "evidence": sorted(evidence, key=lambda item: str(item["requirement_id"])),
            "crosswalk": crosswalk,
            "reviewer": source["reviewer"],
            "review_state": source["review_state"],
        }
        controls.append(_specification_digest(specification))
    catalog = {
        "schema_version": "1.0.0",
        "framework_id": framework.id,
        "framework_version": framework.version,
        "framework_scope": framework.scope,
        "source_revision_digest": _source_revision_digest(framework),
        "framework_definition_digest": _file_digest(framework_path),
        "expected_control_count": 15,
        "controls": controls,
        "reviewer": source["reviewer"],
        "review_state": source["review_state"],
    }
    return _catalog_digest(catalog)


def build_mcsb_catalog(
    *,
    controls_path: Path,
    crosswalk_path: Path,
    source_path: Path,
) -> dict[str, Any]:
    """Decompose every MCSB v1 control into a manual requirement plus reviewed Rule bindings."""

    controls_doc = _load_yaml_object(controls_path)
    crosswalk_doc = _load_yaml_object(crosswalk_path)
    source = _load_yaml_object(source_path)
    if (
        source.get("framework_id") != "azure-mcsb"
        or source.get("review_state") != "reviewed"
        or source.get("benchmark_version") != controls_doc.get("benchmark_version")
    ):
        raise ValueError("MCSB assessment source identity or review state is invalid")
    defaults = source["defaults"]
    raw_controls = controls_doc.get("controls")
    if (
        not isinstance(raw_controls, list)
        or controls_doc.get("control_import_status") != "complete"
    ):
        raise ValueError("MCSB assessment requires a complete control import")
    mapped = {
        (str(item["control_id"]), str(rule_id))
        for item in crosswalk_doc.get("mappings", [])
        for rule_id in item.get("rule_ids", [])
    }
    bindings: dict[tuple[str, str], str] = {}
    for raw in source.get("rule_bindings", []):
        key = (str(raw["control_id"]), str(raw["rule_id"]))
        if key in bindings or raw.get("evidence_role") not in {"decisive", "supporting_only"}:
            raise ValueError(f"MCSB Rule binding {key} is duplicated or has an invalid role")
        if not str(raw.get("rationale", "")).strip():
            raise ValueError(f"MCSB Rule binding {key} needs a review rationale")
        bindings[key] = str(raw["evidence_role"])
    if set(bindings) != mapped:
        raise ValueError("MCSB Rule bindings MUST review exactly the crosswalk Rule mappings")
    source_meta = controls_doc["source"]
    controls: list[dict[str, Any]] = []
    for raw in raw_controls:
        control_id = str(raw["id"])
        domain = str(raw["domain"]).lower()
        owner_slot = f"mcsb-{domain}-owner"
        manual_ref = f"mcsb-{control_id.lower()}-control-evidence"
        evidence: list[dict[str, Any]] = [
            _mcsb_requirement(
                kind="artifact",
                source_ref=manual_ref,
                producer=str(defaults["manual_producer"]),
                freshness_days=int(defaults["manual_freshness_days"]),
                owner_slot=owner_slot,
                approval_roles=defaults["approval_roles"],
                evidence_role="decisive",
            )
        ]
        crosswalk: list[dict[str, object]] = [
            {"target_kind": "manual_evidence", "target_ref": manual_ref, "relationship": "partial"}
        ]
        for (bound_control, rule_id), role in sorted(bindings.items()):
            if bound_control != control_id:
                continue
            evidence.append(
                _mcsb_requirement(
                    kind="rule",
                    source_ref=rule_id,
                    producer=_PRODUCERS["rule"],
                    freshness_days=int(defaults["rule_freshness_days"]),
                    owner_slot=owner_slot,
                    approval_roles=defaults["approval_roles"],
                    evidence_role=role,
                )
            )
            crosswalk.append(
                {
                    "target_kind": "rule",
                    "target_ref": rule_id,
                    "relationship": "partial" if role == "decisive" else "supporting_only",
                }
            )
        specification = {
            "control_id": control_id,
            "title": str(raw["title"]),
            "area": domain,
            "requirement_mode": "all",
            "cadence_days": min(item["freshness_ceiling_seconds"] // 86_400 for item in evidence),
            "owner_slot": owner_slot,
            "evidence": sorted(evidence, key=lambda item: str(item["requirement_id"])),
            "crosswalk": sorted(crosswalk, key=_crosswalk_key),
            "reviewer": source["reviewer"],
            "review_state": source["review_state"],
        }
        controls.append(_specification_digest(specification))
    catalog = {
        "schema_version": "1.0.0",
        "framework_id": "azure-mcsb",
        "framework_version": str(source_meta["retrieved_at"])[:10],
        "framework_scope": "workload",
        "source_revision_digest": canonical_digest(
            {
                "resolved_ref": source_meta["resolved_ref"],
                "content_hash": source_meta["content_hash"],
            }
        ),
        "framework_definition_digest": _file_digest(controls_path),
        "expected_control_count": len(controls),
        "controls": sorted(controls, key=lambda item: str(item["control_id"])),
        "reviewer": source["reviewer"],
        "review_state": source["review_state"],
    }
    return _catalog_digest(catalog)


def _mcsb_requirement(
    *,
    kind: str,
    source_ref: str,
    producer: str,
    freshness_days: int,
    owner_slot: str,
    approval_roles: list[str],
    evidence_role: str,
) -> dict[str, Any]:
    return {
        "requirement_id": _requirement_id(kind, source_ref),
        "kind": kind,
        "source_ref": source_ref,
        "authoritative_producer": producer,
        "blocked_dependency": None,
        "scope_contract": "exact-workload",
        "generation_contract": "inventory" if kind == "rule" else "none",
        "freshness_ceiling_seconds": freshness_days * 86_400,
        "completeness_required": True,
        "owner_slot": owner_slot,
        "approval_roles": sorted(approval_roles),
        "failure_behavior": "unknown",
        "evidence_role": evidence_role,
        "process_phase": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-root", type=Path, default=Path("rule-catalog"))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("rule-catalog/framework-assessments/generated"),
    )
    args = parser.parse_args()

    framework_root = args.catalog_root / "frameworks"
    frameworks = {
        item.id: item
        for item in load_framework_catalog(
            framework_root,
            best_practices=load_best_practice_catalog(
                args.catalog_root / "best-practices",
                strict=False,
            ),
            objective_refs=frozenset({"reliability.node-pool.zone-failure-tolerance@1.0.0"}),
            additional_roots=(args.catalog_root / "collected/wara-aprl",),
        )
    }
    waf_path = framework_root / "azure-waf.yaml"
    caf_path = framework_root / "azure-caf.yaml"
    outputs = {
        "azure-waf.json": build_waf_catalog(
            framework=frameworks["azure-waf"],
            framework_path=waf_path,
            best_practice_root=args.catalog_root / "best-practices",
        ),
        "azure-caf.json": build_caf_catalog(
            framework=frameworks["azure-caf"],
            framework_path=caf_path,
            source_path=args.catalog_root / "framework-assessments/azure-caf.source.yaml",
        ),
        "azure-mcsb.json": build_mcsb_catalog(
            controls_path=args.catalog_root / "compliance/mcsb/v1/controls.yaml",
            crosswalk_path=args.catalog_root / "compliance/mcsb/v1/crosswalk.yaml",
            source_path=args.catalog_root / "framework-assessments/azure-mcsb.source.yaml",
        ),
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    for filename, value in outputs.items():
        (args.output_root / filename).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
