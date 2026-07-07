"""Parser for aquasecurity/kube-bench CIS-Kubernetes benchmark rulesets.

kube-bench ships one YAML per component (master, node, controlplane,
etcd, policies, ...) for each ruleset version (cis-1.10, cis-1.11,
aks-1.7, eks-1.1, ...). Each YAML declares:

    controls:
      version: cis-1.10
      groups:
        - id: 1.1
          checks:
            - id: 1.1.1
              text: ...
              audit: ...
              remediation: ...
              scored: true|false

This parser walks the tree and emits one :class:`ParsedRule` per
check, shaped for the FDAI rule schema (resource_type =
``kubernetes-cluster.<component>``; source = ``kube_bench``;
check_logic.kind = ``expression`` with an ``audit`` reference back at
the shell command shipped by kube-bench).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import yaml

from .parser import ParsedRule, ParseError, ParseReport, ParserName

_SOURCE_ID: Final[str] = "kube_bench"

_COMPONENT_TO_RESOURCE: Final[Mapping[str, str]] = {
    "master": "kubernetes-cluster.control-plane",
    "controlplane": "kubernetes-cluster.control-plane",
    "etcd": "kubernetes-cluster.etcd",
    "node": "kubernetes-node-pool",
    "policies": "kubernetes-cluster.policies",
    "managedservices": "kubernetes-cluster.managed",
}

_illegal_id = re.compile(r"[^a-z0-9._-]+")


class KubeBenchParser:
    """Parser plugin id ``kube-bench``."""

    @property
    def name(self) -> ParserName:
        return ParserName.KUBE_BENCH

    def parse(self, snapshot_tree_root: Path) -> ParseReport:
        if not snapshot_tree_root.is_dir():
            raise ParseError(
                f"snapshot root does not exist or is not a directory: {snapshot_tree_root}"
            )
        rules: list[ParsedRule] = []
        for path in sorted(snapshot_tree_root.rglob("*.yaml")):
            if path.name == "config.yaml":
                # kube-bench config, not a ruleset.
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise ParseError(f"{path}: not valid YAML: {exc}") from exc
            if not isinstance(doc, Mapping):
                continue
            ruleset_version = _ruleset_version_from_tree(path.relative_to(snapshot_tree_root))
            component = _component_from_filename(path.name)
            resource_type = _COMPONENT_TO_RESOURCE.get(component, f"kubernetes-cluster.{component}")
            for check in _iter_checks(doc):
                raw = _to_rule_mapping(
                    check,
                    origin=path.relative_to(snapshot_tree_root),
                    ruleset_version=ruleset_version,
                    resource_type=resource_type,
                )
                if raw is None:
                    continue
                rules.append(ParsedRule(origin=str(path.relative_to(snapshot_tree_root)), raw=raw))
        return ParseReport(parser=ParserName.KUBE_BENCH, rules=tuple(rules))


def _iter_checks(doc: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    controls = doc.get("controls") or doc  # some rulesets skip the outer wrapper
    if not isinstance(controls, Mapping):
        return
    for group in controls.get("groups") or []:
        if not isinstance(group, Mapping):
            continue
        group_id = str(group.get("id") or "")
        group_text = str(group.get("text") or "")
        for check in group.get("checks") or []:
            if not isinstance(check, Mapping):
                continue
            enriched = dict(check)
            enriched.setdefault("__group_id", group_id)
            enriched.setdefault("__group_text", group_text)
            yield enriched


def _to_rule_mapping(
    check: Mapping[str, Any],
    *,
    origin: Path,
    ruleset_version: str,
    resource_type: str,
) -> Mapping[str, Any] | None:
    check_id = str(check.get("id") or "")
    text = str(check.get("text") or "")
    if not check_id or not text:
        return None
    scored = bool(check.get("scored", False))
    severity = "medium" if scored else "low"
    slug = _illegal_id.sub("-", text.lower()).strip("-.")[:80] or "check"
    fdai_id = f"kube-bench.{ruleset_version}.{check_id.replace('.', '-')}.{slug}"
    fdai_id = _illegal_id.sub("-", fdai_id.lower()).strip("-.")[:128]
    return {
        "schema_version": "1.0.0",
        "id": fdai_id,
        "version": "1.0.0",
        "source": _SOURCE_ID,
        "severity": severity,
        "category": "security",
        "resource_type": resource_type,
        "check_logic": {
            "kind": "expression",
            "reference": f"kube-bench://{ruleset_version}/{check_id}",
        },
        "remediation": {
            "template_ref": f"remediation/kube-bench/{ruleset_version}/{check_id}.md",
        },
        "remediates": "remediate.azure-policy-managed",
        "parameters": {
            "kube_bench_id": check_id,
            "kube_bench_ruleset": ruleset_version,
            "kube_bench_group_id": check.get("__group_id", ""),
            "kube_bench_scored": scored,
            "kube_bench_audit": str(check.get("audit") or "")[:1024],
        },
        "provenance": {
            "source_url": (
                f"https://github.com/aquasecurity/kube-bench/blob/main/cfg/{origin.as_posix()}"
            ),
            "source_version": ruleset_version,
            "resolved_ref": "0000000000000000000000000000000000000000",
            "content_hash": "sha256:" + ("0" * 64),
            "license": "Apache-2.0",
            "redistribution": "embeddable",
            "retrieved_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


def _ruleset_version_from_tree(relative_path: Path) -> str:
    parts = relative_path.parts
    if parts:
        return parts[0]
    return "unknown"


def _component_from_filename(filename: str) -> str:
    return filename.rsplit(".", 1)[0].lower()


__all__ = ["KubeBenchParser"]
