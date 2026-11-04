"""Deterministic catalog, control, workflow, scenario, and cloud reference index."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "rule-catalog").is_dir() and (parent / "config").is_dir():
            return parent
    return current.parents[6]


@dataclass(frozen=True, slots=True)
class WorkflowCatalogEntry:
    workflow_id: str
    version: str
    source_scope: str
    description: str
    trigger_kind: str
    trigger_signal_or_event: str
    default_mode: str
    gate_refs: tuple[str, ...]
    action_type_refs: tuple[str, ...]
    compensated_by_refs: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]
    anti_scope: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class BusinessScenarioEntry:
    scenario_id: str
    profile_id: str
    service_id: str
    service_name: str
    criticality: str
    workloads: tuple[dict[str, str], ...]
    dependency_edges: tuple[dict[str, str], ...]
    slo_specs: tuple[dict[str, Any], ...]
    workflows: tuple[str, ...]
    decision_functions: tuple[str, ...]
    content_digest: str


@dataclass(frozen=True, slots=True)
class RuleAndControlRecord:
    record_id: str
    domain: str
    title: str
    summary: str
    resource_type: str | None
    category: str
    severity: str | None
    metadata: Mapping[str, Any]
    search_blob: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class CloudReferenceTopicRecord:
    topic_id: str
    resource_type: str
    category: str
    title_en: str
    title_ko: str
    summary_en: str
    summary_ko: str
    query_terms: tuple[str, ...]
    options: tuple[dict[str, Any], ...]
    cni_models: tuple[dict[str, Any], ...]
    evaluated_property: str | None
    related_rules: tuple[str, ...]
    related_controls: tuple[str, ...]
    related_actions: tuple[str, ...]
    related_workflows: tuple[str, ...]
    source_url: str
    retrieved_at: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class CatalogKnowledgeCorpus:
    repo_root: Path
    workflows: tuple[WorkflowCatalogEntry, ...]
    business_scenarios: tuple[BusinessScenarioEntry, ...]
    rules_and_controls: tuple[RuleAndControlRecord, ...]
    cloud_reference_topics: tuple[CloudReferenceTopicRecord, ...]
    corpus_digest: str

    def search_workflows(
        self,
        *,
        query: str = "",
        gate_ref: str | None = None,
        action_type_ref: str | None = None,
        limit: int = 20,
    ) -> tuple[WorkflowCatalogEntry, ...]:
        tokens = [tok for tok in query.lower().replace("-", " ").split() if tok]
        matched: list[tuple[int, WorkflowCatalogEntry]] = []
        for entry in self.workflows:
            if gate_ref and gate_ref not in entry.gate_refs:
                continue
            if action_type_ref and action_type_ref not in entry.action_type_refs:
                continue
            blob = " ".join(
                (
                    entry.workflow_id,
                    entry.description,
                    entry.trigger_signal_or_event,
                    entry.anti_scope,
                    " ".join(entry.gate_refs),
                    " ".join(entry.action_type_refs),
                    " ".join(entry.compensated_by_refs),
                )
            ).lower()
            score = _match_score(blob, query.lower().strip(), tokens)
            if not tokens or score > 0:
                matched.append((score, entry))
        matched.sort(key=lambda item: (-item[0], item[1].workflow_id))
        return tuple(item[1] for item in matched[:limit])

    def search_business_scenarios(
        self,
        *,
        query: str = "",
        service_id: str | None = None,
        limit: int = 20,
    ) -> tuple[BusinessScenarioEntry, ...]:
        tokens = [tok for tok in query.lower().replace("-", " ").split() if tok]
        matched: list[tuple[int, BusinessScenarioEntry]] = []
        for entry in self.business_scenarios:
            if service_id and entry.service_id != service_id:
                continue
            blob = json.dumps(
                {
                    "scenario_id": entry.scenario_id,
                    "profile_id": entry.profile_id,
                    "service_id": entry.service_id,
                    "service_name": entry.service_name,
                    "criticality": entry.criticality,
                    "workloads": entry.workloads,
                    "slos": entry.slo_specs,
                    "workflows": entry.workflows,
                    "decision_functions": entry.decision_functions,
                },
                ensure_ascii=False,
            ).lower()
            score = _match_score(blob, query.lower().strip(), tokens)
            if not tokens or score > 0:
                matched.append((score, entry))
        matched.sort(key=lambda item: (-item[0], item[1].scenario_id))
        return tuple(item[1] for item in matched[:limit])

    def search_rules_and_controls(
        self,
        *,
        query: str = "",
        domain: str = "all",
        resource_type: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> tuple[RuleAndControlRecord, ...]:
        tokens = [tok for tok in query.lower().replace("-", " ").split() if tok]
        matched: list[tuple[int, RuleAndControlRecord]] = []
        for record in self.rules_and_controls:
            if domain != "all" and record.domain != domain:
                continue
            if resource_type and record.resource_type != resource_type:
                continue
            if category and record.category.lower() != category.lower():
                continue
            score = _match_score(record.search_blob, query.lower().strip(), tokens)
            if not tokens or score > 0:
                matched.append((score, record))
        matched.sort(key=lambda item: (-item[0], item[1].record_id))
        return tuple(item[1] for item in matched[:limit])

    def search_cloud_reference(
        self,
        *,
        query: str = "",
        resource_type: str | None = None,
        category: str | None = None,
        limit: int = 10,
    ) -> tuple[CloudReferenceTopicRecord, ...]:
        tokens = [tok for tok in query.lower().replace("-", " ").split() if tok]
        matched: list[tuple[int, CloudReferenceTopicRecord]] = []
        for topic in self.cloud_reference_topics:
            if resource_type and topic.resource_type != resource_type:
                continue
            if category and topic.category.lower() != category.lower():
                continue
            blob = " ".join(
                (
                    topic.topic_id,
                    topic.resource_type,
                    topic.category,
                    topic.title_en,
                    topic.title_ko,
                    topic.summary_en,
                    topic.summary_ko,
                    " ".join(topic.query_terms),
                    json.dumps(topic.options, ensure_ascii=False),
                    json.dumps(topic.cni_models, ensure_ascii=False),
                    " ".join(topic.related_rules),
                    " ".join(topic.related_controls),
                    " ".join(topic.related_actions),
                    " ".join(topic.related_workflows),
                )
            ).lower()
            score = _match_score(blob, query.lower().strip(), tokens)
            if not tokens or score > 0:
                matched.append((score, topic))
        matched.sort(key=lambda item: (-item[0], item[1].topic_id))
        return tuple(item[1] for item in matched[:limit])

    def resolve_governance_chain(self, target_id: str) -> dict[str, Any]:
        needle = target_id.strip().lower()
        rules = [
            r
            for r in self.rules_and_controls
            if r.domain == "rule"
            and (
                needle in r.record_id.lower()
                or needle in str(r.metadata.get("remediates", "")).lower()
                or needle in str(r.metadata.get("resource_type", "")).lower()
                or any(needle in str(p).lower() for p in r.metadata.get("evaluates", ()))
            )
        ]
        rule_ids = {r.metadata.get("id", r.record_id.removeprefix("rule:")) for r in rules}
        control_domains = {
            "framework_control",
            "wara",
            "mcsb_compliance",
            "best_practice",
            "baseline",
        }
        controls = [
            r
            for r in self.rules_and_controls
            if r.domain in control_domains
            and (
                needle in r.record_id.lower()
                or needle in r.search_blob
                or any(str(rid) in r.search_blob for rid in rule_ids if rid)
            )
        ]
        workflows = [
            w
            for w in self.workflows
            if needle in w.workflow_id.lower()
            or needle in w.description.lower()
            or any(needle in act.lower() for act in w.action_type_refs)
            or any(needle in gate.lower() for gate in w.gate_refs)
            or any(
                str(r.metadata.get("remediates", "")).lower()
                in [a.lower() for a in w.action_type_refs]
                for r in rules
            )
        ]
        cloud_topics = [
            t
            for t in self.cloud_reference_topics
            if needle in t.topic_id.lower()
            or needle in t.resource_type.lower()
            or any(needle in r.lower() for r in t.related_rules)
            or any(needle in c.lower() for c in t.related_controls)
            or any(r in t.related_rules for r in rule_ids)
        ]
        actions = sorted(
            {
                *(str(r.metadata["remediates"]) for r in rules if r.metadata.get("remediates")),
                *(act for w in workflows for act in w.action_type_refs),
                *(act for t in cloud_topics for act in t.related_actions),
            }
        )
        remediation_templates = sorted(
            {
                str(r.metadata["remediation_template_ref"])
                for r in rules
                if r.metadata.get("remediation_template_ref")
            }
        )
        evaluated_properties = sorted(
            {
                *(str(prop) for r in rules for prop in r.metadata.get("evaluates", ())),
                *(t.evaluated_property for t in cloud_topics if t.evaluated_property),
            }
        )
        chain_payload = {
            "target_id": target_id,
            "matched_rules": [r.record_id for r in rules[:20]],
            "matched_controls": [c.record_id for c in controls[:25]],
            "matched_workflows": [w.workflow_id for w in workflows[:15]],
            "matched_cloud_reference_topics": [t.topic_id for t in cloud_topics[:10]],
            "linked_actions": actions,
            "remediation_templates": remediation_templates,
            "evaluated_properties": evaluated_properties,
        }
        return {
            **chain_payload,
            "chain_digest": _canonical_digest(chain_payload),
            "epistemic_status": "reviewed_catalog_lineage",
            "execution_authority": False,
        }


def _match_score(blob: str, phrase: str, tokens: Sequence[str]) -> int:
    if not tokens:
        return 1
    score = 0
    if phrase and phrase in blob:
        score += 10
    for token in tokens:
        if token in blob:
            score += 3
    return score


_CACHED_CORPUS: dict[Path, CatalogKnowledgeCorpus] = {}


def load_catalog_knowledge_corpus(repo_root: Path | None = None) -> CatalogKnowledgeCorpus:
    from .catalog_knowledge_sources import (
        load_cloud_reference_records,
        load_rules_and_controls_records,
    )

    root = (repo_root or _find_repo_root()).resolve()
    cached = _CACHED_CORPUS.get(root)
    if cached is not None:
        return cached
    workflows = _load_workflows(root)
    scenarios = _load_business_scenarios(root, workflows)
    rules_and_controls = load_rules_and_controls_records(root)
    cloud_topics = load_cloud_reference_records(root)
    corpus_digest = _canonical_digest(
        {
            "workflows": [w.content_digest for w in workflows],
            "scenarios": [s.content_digest for s in scenarios],
            "rules_and_controls": [r.content_digest for r in rules_and_controls],
            "cloud_topics": [t.content_digest for t in cloud_topics],
        }
    )
    corpus = CatalogKnowledgeCorpus(
        repo_root=root,
        workflows=workflows,
        business_scenarios=scenarios,
        rules_and_controls=rules_and_controls,
        cloud_reference_topics=cloud_topics,
        corpus_digest=corpus_digest,
    )
    _CACHED_CORPUS[root] = corpus
    return corpus


def _load_workflows(root: Path) -> tuple[WorkflowCatalogEntry, ...]:
    entries: list[WorkflowCatalogEntry] = []
    workflow_paths: list[tuple[str, Path]] = []
    catalog_wf_dir = root / "rule-catalog" / "workflows"
    if catalog_wf_dir.is_dir():
        for path in sorted(catalog_wf_dir.glob("*.yaml")):
            workflow_paths.append(("rule-catalog", path))
    ext_dir = root / "extensions"
    if ext_dir.is_dir():
        for path in sorted(ext_dir.glob("*/src/*/resources/workflows/*.yaml")):
            workflow_paths.append(("extension", path))
    for scope, path in workflow_paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "name" not in raw:
            continue
        steps_raw = raw.get("steps") or []
        gate_refs: list[str] = []
        action_refs: list[str] = []
        comp_refs: list[str] = []
        normalized_steps: list[dict[str, Any]] = []
        for step in steps_raw:
            if not isinstance(step, dict):
                continue
            gate_ref = step.get("gate_ref") or step.get("guard_rule_ref")
            if isinstance(gate_ref, str) and gate_ref:
                gate_refs.append(gate_ref)
            action_ref = step.get("action_type_ref")
            if isinstance(action_ref, str) and action_ref:
                action_refs.append(action_ref)
            comp_ref = step.get("compensated_by")
            if isinstance(comp_ref, str) and comp_ref:
                comp_refs.append(comp_ref)
            normalized_steps.append(
                {
                    "id": str(step.get("id", "")),
                    "kind": str(step.get("kind", "action" if action_ref else "step")),
                    "gate_ref": gate_ref,
                    "action_type_ref": action_ref,
                    "compensated_by": comp_ref,
                }
            )
        trigger = raw.get("trigger") or {}
        trigger_kind = str(trigger.get("kind", "signal"))
        trigger_target = str(
            trigger.get("signal_type") or trigger.get("event_type") or trigger.get("schedule") or ""
        )
        workflow_id = str(raw["name"])
        version = str(raw.get("version", "1.0.0"))
        description = str(raw.get("description", "")).strip()
        default_mode = str(raw.get("default_mode", "shadow"))
        gate_refs_tuple = tuple(gate_refs)
        action_refs_tuple = tuple(action_refs)
        comp_refs_tuple = tuple(comp_refs)
        steps_tuple = tuple(normalized_steps)
        anti_scope = str(raw.get("anti_scope", "")).strip()
        payload = {
            "workflow_id": workflow_id,
            "version": version,
            "source_scope": scope,
            "description": description,
            "trigger_kind": trigger_kind,
            "trigger_signal_or_event": trigger_target,
            "default_mode": default_mode,
            "gate_refs": gate_refs_tuple,
            "action_type_refs": action_refs_tuple,
            "compensated_by_refs": comp_refs_tuple,
            "steps": steps_tuple,
            "anti_scope": anti_scope,
        }
        entries.append(
            WorkflowCatalogEntry(
                workflow_id=workflow_id,
                version=version,
                source_scope=scope,
                description=description,
                trigger_kind=trigger_kind,
                trigger_signal_or_event=trigger_target,
                default_mode=default_mode,
                gate_refs=gate_refs_tuple,
                action_type_refs=action_refs_tuple,
                compensated_by_refs=comp_refs_tuple,
                steps=steps_tuple,
                anti_scope=anti_scope,
                content_digest=_canonical_digest(payload),
            )
        )
    return tuple(sorted(entries, key=lambda item: item.workflow_id))


def _load_business_scenarios(
    root: Path,
    workflows: Sequence[WorkflowCatalogEntry],
) -> tuple[BusinessScenarioEntry, ...]:
    scenarios: list[BusinessScenarioEntry] = []
    profile_path = (
        root
        / "extensions"
        / "aks-commerce"
        / "src"
        / "fdai_aks_commerce"
        / "resources"
        / "scenario-profile.json"
    )
    slo_dir = profile_path.parent / "slos"
    slo_by_service: dict[str, list[dict[str, Any]]] = {}
    if slo_dir.is_dir():
        for slo_path in sorted(slo_dir.glob("*.yaml")):
            raw_slo = yaml.safe_load(slo_path.read_text(encoding="utf-8"))
            if isinstance(raw_slo, dict):
                service_id = str((raw_slo.get("sli") or {}).get("labels", {}).get("service_id", ""))
                slo_by_service.setdefault(service_id, []).append(
                    {
                        "id": str(raw_slo.get("id", "")),
                        "description": str(raw_slo.get("description", "")),
                        "objective_ratio": raw_slo.get("objective_ratio"),
                        "window_days": raw_slo.get("window_days"),
                    }
                )
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        workloads_by_id = {
            str(w["id"]): {
                "id": str(w["id"]),
                "name": str(w["name"]),
                "workload_kind": str(w["workload_kind"]),
            }
            for w in profile.get("workloads", ())
        }
        links = profile.get("links", ())
        for service in profile.get("services", ()):
            svc_id = str(service["id"])
            implemented_ids = [
                str(link["to_id"])
                for link in links
                if link.get("from_id") == svc_id and link.get("link_type") == "implemented_by"
            ]
            dep_edges = [
                {
                    "from_id": str(link["from_id"]),
                    "link_type": str(link["link_type"]),
                    "to_id": str(link["to_id"]),
                }
                for link in links
                if link.get("from_id") in implemented_ids or link.get("from_id") == svc_id
            ]
            svc_workloads = tuple(
                workloads_by_id[wid] for wid in implemented_ids if wid in workloads_by_id
            )
            related_wfs = tuple(
                w.workflow_id
                for w in workflows
                if "commerce" in w.workflow_id
                or "blast-radius" in w.workflow_id
                or "scale-in" in w.workflow_id
            )
            decision_fns = (
                "decision.blast_radius",
                "decision.change_risk",
                "decision.cost_of_delay",
                "decision.slo_exhaustion_eta",
                "decision.recovery_feasibility",
            )
            scenario_id = f"aks-commerce:{svc_id}"
            profile_id = str(profile.get("profile_id", "aks-commerce"))
            service_name = str(service.get("name", svc_id))
            criticality = str(service.get("criticality", "high"))
            dep_edges_tuple = tuple(dep_edges)
            slo_specs_tuple = tuple(slo_by_service.get(svc_id, ()))
            payload = {
                "scenario_id": scenario_id,
                "profile_id": profile_id,
                "service_id": svc_id,
                "service_name": service_name,
                "criticality": criticality,
                "workloads": svc_workloads,
                "dependency_edges": dep_edges_tuple,
                "slo_specs": slo_specs_tuple,
                "workflows": related_wfs,
                "decision_functions": decision_fns,
            }
            scenarios.append(
                BusinessScenarioEntry(
                    scenario_id=scenario_id,
                    profile_id=profile_id,
                    service_id=svc_id,
                    service_name=service_name,
                    criticality=criticality,
                    workloads=svc_workloads,
                    dependency_edges=dep_edges_tuple,
                    slo_specs=slo_specs_tuple,
                    workflows=related_wfs,
                    decision_functions=decision_fns,
                    content_digest=_canonical_digest(payload),
                )
            )
    return tuple(sorted(scenarios, key=lambda item: item.scenario_id))
