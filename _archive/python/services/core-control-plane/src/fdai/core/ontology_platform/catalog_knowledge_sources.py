"""Source loaders for rules, controls, WARA, WAF, MCSB, baselines, probes, and cloud reference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .catalog_knowledge_loader import (
    CloudReferenceTopicRecord,
    RuleAndControlRecord,
    _canonical_digest,
)


def load_rules_and_controls_records(root: Path) -> tuple[RuleAndControlRecord, ...]:
    records: list[RuleAndControlRecord] = []
    _append_atomic_rules(root, records)
    _append_framework_controls(root, records)
    _append_wara_guidance_controls(root, records)
    _append_best_practices(root, records)
    _append_mcsb_compliance_controls(root, records)
    _append_configuration_baselines(root, records)
    _append_probes_insights_and_mechanisms(root, records)
    return tuple(sorted(records, key=lambda item: item.record_id))


def _append_atomic_rules(root: Path, records: list[RuleAndControlRecord]) -> None:
    rule_dirs = [
        root / "rule-catalog" / "catalog",
        (
            root
            / "extensions"
            / "cost-governance"
            / "src"
            / "fdai_cost_governance"
            / "resources"
            / "rules"
        ),
    ]
    for rule_dir in rule_dirs:
        if not rule_dir.is_dir():
            continue
        for path in sorted(rule_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or "id" not in raw:
                continue
            rule_id = str(raw["id"])
            remediation = raw.get("remediation") or {}
            check_logic = raw.get("check_logic") or {}
            prov = raw.get("provenance") or {}
            metadata: dict[str, Any] = {
                "id": rule_id,
                "version": str(raw.get("version", "1.0.0")),
                "source": str(raw.get("source", "")),
                "resource_type": str(raw.get("resource_type", "")),
                "applies_to": list(raw.get("applies_to") or ()),
                "triggered_by": list(raw.get("triggered_by") or ()),
                "evaluates": list(raw.get("evaluates") or ()),
                "policy_reference": str(check_logic.get("reference", "")),
                "remediation_template_ref": str(remediation.get("template_ref", "")),
                "remediates": str(raw.get("remediates", "")),
                "source_url": str(prov.get("source_url", "")),
            }
            summary = (
                f"Atomic rule {rule_id} on {metadata['resource_type']} evaluating "
                f"{', '.join(metadata['evaluates'])} via {metadata['policy_reference']} "
                f"and remediating with {metadata['remediates']}"
            )
            _add_record(
                records,
                record_id=f"rule:{rule_id}",
                domain="rule",
                title=rule_id,
                summary=summary,
                resource_type=metadata["resource_type"] or None,
                category=str(raw.get("category", "governance")),
                severity=str(raw.get("severity", "medium")),
                metadata=metadata,
            )


def _append_framework_controls(root: Path, records: list[RuleAndControlRecord]) -> None:
    fw_dir = root / "rule-catalog" / "frameworks"
    if not fw_dir.is_dir():
        return
    for path in sorted(fw_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        fw_id = str(raw["id"])
        fw_name = str(raw.get("name", fw_id))
        for area in raw.get("areas") or ():
            area_id = str(area.get("id", "general"))
            for ctrl in area.get("controls") or ():
                ctrl_id = str(ctrl.get("id", ""))
                title = str(ctrl.get("title", ctrl_id))
                metadata = {
                    "framework_id": fw_id,
                    "framework_name": fw_name,
                    "area": area_id,
                    "control_id": ctrl_id,
                    "best_practice_ref": ctrl.get("best_practice_ref"),
                    "objective_refs": list(ctrl.get("objective_refs") or ()),
                    "mapping_status": str(ctrl.get("mapping_status", "")),
                    "source_url": str(area.get("source_url", "")),
                }
                _add_record(
                    records,
                    record_id=f"framework_control:{fw_id}:{ctrl_id}",
                    domain="framework_control",
                    title=f"{fw_id.upper()} {ctrl_id} - {title}",
                    summary=f"{fw_name} ({area_id}) control {ctrl_id}: {title}",
                    resource_type=None,
                    category=area_id,
                    severity=None,
                    metadata=metadata,
                )
        for ctrl in raw.get("controls") or ():
            ctrl_id = str(ctrl.get("id", ""))
            title = str(ctrl.get("title", ctrl_id))
            desc = str(ctrl.get("description", title))
            metadata = {
                "framework_id": fw_id,
                "framework_name": fw_name,
                "control_id": ctrl_id,
                "description": desc,
                "objective_refs": list(ctrl.get("objective_refs") or ()),
                "mapping_status": str(ctrl.get("mapping_status", "")),
                "source_url": str(ctrl.get("source_url", "")),
            }
            _add_record(
                records,
                record_id=f"framework_control:{fw_id}:{ctrl_id}",
                domain="framework_control",
                title=f"{fw_id.upper()} {ctrl_id} - {title}",
                summary=desc,
                resource_type=None,
                category="governance",
                severity=None,
                metadata=metadata,
            )


def _append_wara_guidance_controls(root: Path, records: list[RuleAndControlRecord]) -> None:
    en_path = root / "rule-catalog" / "guidance" / "azure-wara" / "controls.tsv"
    ko_path = root / "rule-catalog" / "guidance" / "azure-wara" / "controls-ko.tsv"
    if not en_path.is_file():
        return
    ko_map: dict[str, tuple[str, str]] = {}
    if ko_path.is_file():
        for line in ko_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                ko_map[parts[0].strip()] = (parts[1].strip(), parts[2].strip())
    for line in en_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        guid_prefix, mechanism, focus_en, obs_en = (p.strip() for p in parts[:4])
        focus_ko, obs_ko = ko_map.get(guid_prefix, ("", ""))
        metadata = {
            "guid_prefix": guid_prefix,
            "mechanism": mechanism,
            "focus_en": focus_en,
            "observation_en": obs_en,
            "focus_ko": focus_ko,
            "observation_ko": obs_ko,
        }
        summary = f"{focus_en}: {obs_en}" + (f" / {focus_ko}: {obs_ko}" if focus_ko else "")
        _add_record(
            records,
            record_id=f"wara:{guid_prefix}",
            domain="wara",
            title=f"WARA {guid_prefix} - {focus_en}",
            summary=summary,
            resource_type=None,
            category=mechanism,
            severity=None,
            metadata=metadata,
        )


def _append_best_practices(root: Path, records: list[RuleAndControlRecord]) -> None:
    bp_dir = root / "rule-catalog" / "best-practices"
    if not bp_dir.is_dir():
        return
    for path in sorted(bp_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        bp_id = str(raw["id"])
        title = str(raw.get("title", bp_id))
        rationale = str(raw.get("rationale", ""))
        prov = raw.get("provenance") or {}
        metadata = {
            "id": bp_id,
            "framework": str(raw.get("framework", "")),
            "control_id": str(raw.get("control_id", "")),
            "requirement_mode": str(raw.get("requirement_mode", "all")),
            "requirements": list(raw.get("requirements") or ()),
            "source_url": str(prov.get("source_url", "")),
        }
        _add_record(
            records,
            record_id=f"best_practice:{bp_id}",
            domain="best_practice",
            title=title,
            summary=rationale,
            resource_type=None,
            category=str(raw.get("category", "reliability")),
            severity=str(raw.get("severity", "medium")),
            metadata=metadata,
        )


def _append_mcsb_compliance_controls(root: Path, records: list[RuleAndControlRecord]) -> None:
    controls_path = root / "rule-catalog" / "compliance" / "mcsb" / "v1" / "controls.yaml"
    crosswalk_path = root / "rule-catalog" / "compliance" / "mcsb" / "v1" / "crosswalk.yaml"
    if not controls_path.is_file():
        return
    raw_controls = yaml.safe_load(controls_path.read_text(encoding="utf-8")) or {}
    crosswalk_by_id: dict[str, dict[str, Any]] = {}
    if crosswalk_path.is_file():
        raw_cw = yaml.safe_load(crosswalk_path.read_text(encoding="utf-8")) or {}
        for item in raw_cw.get("mappings") or ():
            if isinstance(item, dict) and "control_id" in item:
                crosswalk_by_id[str(item["control_id"])] = item
    source_url = str((raw_controls.get("source") or {}).get("source_url", ""))
    for ctrl in raw_controls.get("controls") or ():
        ctrl_id = str(ctrl.get("id", ""))
        domain_code = str(ctrl.get("domain", ""))
        title = str(ctrl.get("title", ctrl_id))
        cw = crosswalk_by_id.get(ctrl_id, {})
        rule_ids = list(cw.get("rule_ids") or ())
        obs_ids = list(cw.get("runtime_observation_ids") or ())
        metadata = {
            "benchmark": "mcsb-v1",
            "control_id": ctrl_id,
            "domain_code": domain_code,
            "coverage": str(cw.get("coverage", "unmapped")),
            "rule_ids": rule_ids,
            "runtime_observation_ids": obs_ids,
            "source_url": source_url,
        }
        _add_record(
            records,
            record_id=f"mcsb:{ctrl_id}",
            domain="mcsb_compliance",
            title=f"MCSB {ctrl_id} - {title}",
            summary=(
                f"MCSB v1 {ctrl_id} ({domain_code}): {title}; "
                f"mapped rules={rule_ids}, runtime observations={obs_ids}"
            ),
            resource_type=None,
            category="security",
            severity="high" if rule_ids or obs_ids else "medium",
            metadata=metadata,
        )


def _append_configuration_baselines(root: Path, records: list[RuleAndControlRecord]) -> None:
    bl_dir = root / "rule-catalog" / "baselines" / "configuration"
    if not bl_dir.is_dir():
        return
    for path in sorted(bl_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        bl_id = str(raw["id"])
        title = str(raw.get("title", bl_id))
        controls = list(raw.get("controls") or ())
        prov = raw.get("provenance") or {}
        res_type = str(raw.get("resource_type", ""))
        metadata: dict[str, Any] = {
            "id": bl_id,
            "resource_type": res_type,
            "controls": controls,
            "source_url": str(prov.get("source_url", "")),
        }
        _add_record(
            records,
            record_id=f"baseline:{bl_id}",
            domain="baseline",
            title=title,
            summary=f"Configuration baseline {bl_id} requiring controls: {', '.join(controls)}",
            resource_type=res_type or None,
            category="security",
            severity="high",
            metadata=metadata,
        )


def _append_probes_insights_and_mechanisms(root: Path, records: list[RuleAndControlRecord]) -> None:
    probes_dir = root / "rule-catalog" / "probes"
    if probes_dir.is_dir():
        for path in sorted(probes_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or "id" not in raw:
                continue
            probe_id = str(raw["id"])
            desc = str(raw.get("description", probe_id))
            _add_record(
                records,
                record_id=f"probe:{probe_id}",
                domain="probe",
                title=f"Live Probe {probe_id}",
                summary=desc,
                resource_type=None,
                category="reliability",
                severity=None,
                metadata=raw,
            )
    insights_path = root / "rule-catalog" / "operational-insights" / "catalog.yaml"
    if insights_path.is_file():
        raw_ins = yaml.safe_load(insights_path.read_text(encoding="utf-8")) or {}
        for recipe in raw_ins.get("recipes") or ():
            rec_id = str(recipe.get("recipe_id", ""))
            title = str(recipe.get("title", rec_id))
            desc = str(recipe.get("description", title))
            _add_record(
                records,
                record_id=f"operational_insight:{rec_id}",
                domain="operational_insight",
                title=title,
                summary=desc,
                resource_type=None,
                category=str(recipe.get("category", "reliability")),
                severity=str(recipe.get("severity", "medium")),
                metadata=recipe,
            )
    mech_path = root / "rule-catalog" / "vocabulary" / "causal-mechanisms.yaml"
    if mech_path.is_file():
        raw_mech = yaml.safe_load(mech_path.read_text(encoding="utf-8")) or {}
        for mech in raw_mech.get("mechanisms") or ():
            mech_id = str(mech.get("id", ""))
            desc = str(mech.get("description", mech_id))
            _add_record(
                records,
                record_id=f"causal_mechanism:{mech_id}",
                domain="causal_mechanism",
                title=f"Causal Mechanism {mech_id}",
                summary=desc,
                resource_type=None,
                category="reliability",
                severity="high",
                metadata=mech,
            )


def _add_record(
    records: list[RuleAndControlRecord],
    *,
    record_id: str,
    domain: str,
    title: str,
    summary: str,
    resource_type: str | None,
    category: str,
    severity: str | None,
    metadata: dict[str, Any],
) -> None:
    payload = {
        "record_id": record_id,
        "domain": domain,
        "title": title,
        "summary": summary,
        "resource_type": resource_type,
        "category": category,
        "severity": severity,
        "metadata": metadata,
    }
    blob = " ".join(
        (
            record_id,
            domain,
            title,
            summary,
            resource_type or "",
            category,
            severity or "",
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        )
    ).lower()
    records.append(
        RuleAndControlRecord(
            record_id=record_id,
            domain=domain,
            title=title,
            summary=summary,
            resource_type=resource_type,
            category=category,
            severity=severity,
            metadata=metadata,
            search_blob=blob,
            content_digest=_canonical_digest(payload),
        )
    )


def load_cloud_reference_records(root: Path) -> tuple[CloudReferenceTopicRecord, ...]:
    path = root / "config" / "cloud-reference-corpus.yaml"
    if not path.is_file():
        return ()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    topics: list[CloudReferenceTopicRecord] = []
    for item in raw.get("topics") or ():
        if not isinstance(item, dict) or "topic_id" not in item:
            continue
        topic_id = str(item["topic_id"])
        resource_type = str(item.get("resource_type", ""))
        category = str(item.get("category", "architecture"))
        title_en = str(item.get("title_en", ""))
        title_ko = str(item.get("title_ko", ""))
        summary_en = str(item.get("summary_en", ""))
        summary_ko = str(item.get("summary_ko", ""))
        query_terms = tuple(str(t) for t in (item.get("query_terms") or ()))
        options = tuple(dict(opt) for opt in (item.get("options") or ()))
        cni_models = tuple(dict(mode) for mode in (item.get("cni_models") or ()))
        evaluated_property = (
            str(item["evaluated_property"]) if item.get("evaluated_property") else None
        )
        related_rules = tuple(str(r) for r in (item.get("related_rules") or ()))
        related_controls = tuple(str(c) for c in (item.get("related_controls") or ()))
        related_actions = tuple(str(a) for a in (item.get("related_actions") or ()))
        related_workflows = tuple(str(w) for w in (item.get("related_workflows") or ()))
        source_url = str(item.get("source_url", ""))
        retrieved_at = str(item.get("retrieved_at", ""))
        payload = {
            "topic_id": topic_id,
            "resource_type": resource_type,
            "category": category,
            "title_en": title_en,
            "title_ko": title_ko,
            "summary_en": summary_en,
            "summary_ko": summary_ko,
            "query_terms": query_terms,
            "options": options,
            "cni_models": cni_models,
            "evaluated_property": evaluated_property,
            "related_rules": related_rules,
            "related_controls": related_controls,
            "related_actions": related_actions,
            "related_workflows": related_workflows,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
        }
        topics.append(
            CloudReferenceTopicRecord(
                topic_id=topic_id,
                resource_type=resource_type,
                category=category,
                title_en=title_en,
                title_ko=title_ko,
                summary_en=summary_en,
                summary_ko=summary_ko,
                query_terms=query_terms,
                options=options,
                cni_models=cni_models,
                evaluated_property=evaluated_property,
                related_rules=related_rules,
                related_controls=related_controls,
                related_actions=related_actions,
                related_workflows=related_workflows,
                source_url=source_url,
                retrieved_at=retrieved_at,
                content_digest=_canonical_digest(payload),
            )
        )
    return tuple(sorted(topics, key=lambda item: item.topic_id))
