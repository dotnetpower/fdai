"""Canonical code-security issues: one root cause, one fix site, one severity.

Occurrences from any lane, producer, path, or layer collapse into issues by deterministic keys:

- **code findings** merge when they share a weakness class and the same fix site (path and start
  line of the primary location, which SARIF producers place at the sink). Distinct source paths
  into that sink become separate instances. CWE ancestry alone never merges findings; a CWE that
  no class lists stays in an ``unclassified`` bucket keyed by producer and rule.
- **dependency findings** merge when they name the same package and share any advisory alias
  (CVE, GHSA, OSV). Each layer (lockfile, image, workload) becomes an instance.

All occurrences must target the same revision. Facts, verification results, exposure, and known
exploitation come from :class:`AnalysisContext`, never from scanner text.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from fdai.core.security.code_findings.models import (
    CodeSecurityIssue,
    FlowStep,
    Instance,
    InstanceFacts,
    Lane,
    Occurrence,
)
from fdai.core.security.code_findings.priority import PriorityInput, assign_priority
from fdai.core.security.code_findings.severity import (
    aggregate_issue_severity,
    assess_advisory,
    assess_facts,
)
from fdai.rule_catalog.code_security import (
    BAND_ORDER,
    CodeSecurityCatalog,
    Confidence,
    Exposure,
    Impact,
)

UNCLASSIFIED_PREFIX = "unclassified"
DEPENDENCY_CLASS = "vulnerable_dependency"
MISCONFIGURATION_CLASS = "insecure_configuration"
SECRET_CLASS = "hardcoded_secret"  # noqa: S105 - weakness class id, not a credential
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """Trusted inputs for one canonicalization pass over one revision.

    ``instance_facts`` is keyed by instance id and ``verifications`` by issue id; both come from
    deterministic verifiers or authorized people. ``known_exploited`` holds advisory ids from a
    pinned KEV snapshot.
    """

    revision: str
    exposure: Exposure = Exposure.UNKNOWN
    known_exploited: frozenset[str] = frozenset()
    instance_facts: Mapping[str, InstanceFacts] = field(default_factory=dict)
    verifications: Mapping[str, Confidence] = field(default_factory=dict)


def _digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def resolve_class(occurrence: Occurrence, catalog: CodeSecurityCatalog) -> str:
    """Return the weakness class id for a code occurrence.

    Exact CWE membership decides first. Without a listed CWE, producer tags for secrets and
    misconfiguration map to their classes; anything else stays unclassified.
    """
    classes = sorted(
        {
            class_id
            for cwe in occurrence.cwe_ids
            if (class_id := catalog.weakness_classes.class_for_cwe(cwe)) is not None
        }
    )
    if classes:
        return classes[0]
    tags = {tag.lower() for tag in occurrence.tags}
    if tags & {"secret", "secrets", "hardcoded-secret"}:
        return SECRET_CLASS
    if tags & {"misconfiguration", "misconfig"}:
        return MISCONFIGURATION_CLASS
    return f"{UNCLASSIFIED_PREFIX}:{occurrence.producer}:{occurrence.rule_id}"


def class_impact_range(class_id: str, catalog: CodeSecurityCatalog) -> tuple[Impact, ...]:
    entry = catalog.weakness_classes.classes.get(class_id)
    return entry.impact_range if entry is not None else tuple(Impact)


def _confidence(
    issue_id: str, occurrences: Sequence[Occurrence], ctx: AnalysisContext
) -> Confidence:
    verified = ctx.verifications.get(issue_id)
    if verified in (Confidence.VERIFIED, Confidence.PROVEN):
        return verified
    producers = {occ.producer for occ in occurrences}
    non_llm = any(occ.lane is not Lane.LLM_LENS for occ in occurrences)
    if len(producers) >= 2 and non_llm:
        return Confidence.CORROBORATED
    return Confidence.REPORTED if non_llm else Confidence.HYPOTHESIS


def _canonical_advisory(ids: Sequence[str]) -> str:
    return sorted(
        ids, key=lambda value: (not value.startswith("CVE-"), not value.startswith("GHSA"), value)
    )[0]


def _code_groups(
    occurrences: Sequence[Occurrence], catalog: CodeSecurityCatalog
) -> dict[tuple[str, str, int], list[Occurrence]]:
    groups: dict[tuple[str, str, int], list[Occurrence]] = defaultdict(list)
    for occ in occurrences:
        key = (resolve_class(occ, catalog), occ.location.path, occ.location.start_line or 0)
        groups[key].append(occ)
    return groups


def _find(parent: dict[str, str], node: str) -> str:
    """Union-find root lookup over advisory aliases."""
    while parent.setdefault(node, node) != node:
        node = parent[node]
    return node


_PYTHON_MANIFESTS = frozenset(
    {
        "requirements.txt",
        "pipfile",
        "pipfile.lock",
        "poetry.lock",
        "pyproject.toml",
        "uv.lock",
        "setup.py",
        "setup.cfg",
        "pdm.lock",
    }
)
_NPM_MANIFESTS = frozenset(
    {"package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"}
)
_PEP503_SEPARATORS = re.compile(r"[-_.]+")


def normalized_package(package: str, manifest: str) -> str:
    """Return the grouping key for a package name as its ecosystem defines identity.

    PyPI names compare after PEP 503 normalization and npm names case-insensitively, so producers
    that spell one package differently still report one root cause. Other ecosystems, such as Go
    module paths, are case-sensitive and keep the exact name.
    """
    name = PurePosixPath(manifest).name.lower()
    if name in _PYTHON_MANIFESTS or (name.startswith("requirements") and name.endswith(".txt")):
        return _PEP503_SEPARATORS.sub("-", package).lower()
    if name in _NPM_MANIFESTS:
        return package.lower()
    return package


def _dependency_groups(
    occurrences: Sequence[Occurrence],
) -> list[tuple[str, str, list[Occurrence]]]:
    by_package: dict[str, list[Occurrence]] = defaultdict(list)
    for occ in occurrences:
        key = (
            normalized_package(occ.package, occ.location.path) if occ.package else occ.location.path
        )
        by_package[key].append(occ)
    result: list[tuple[str, str, list[Occurrence]]] = []
    for package_key, members in sorted(by_package.items()):
        parent: dict[str, str] = {}
        for occ in members:
            first = occ.advisory_ids[0]
            for alias in occ.advisory_ids[1:]:
                parent[_find(parent, alias)] = _find(parent, first)
            _find(parent, first)
        components: dict[str, list[Occurrence]] = defaultdict(list)
        for occ in members:
            components[_find(parent, occ.advisory_ids[0])].append(occ)
        for component in components.values():
            aliases = sorted({alias for occ in component for alias in occ.advisory_ids})
            result.append((_canonical_advisory(aliases), package_key, component))
    return result


def _instances_for_code(
    issue_id: str,
    class_id: str,
    members: Sequence[Occurrence],
    catalog: CodeSecurityCatalog,
    ctx: AnalysisContext,
) -> tuple[Instance, ...]:
    by_source: dict[tuple[str, int], list[Occurrence]] = defaultdict(list)
    for occ in members:
        source = occ.code_flow[0] if occ.code_flow else None
        by_source[(source.path, source.line or 0) if source else ("", 0)].append(occ)
    instances: list[Instance] = []
    for (path, line), group in sorted(by_source.items()):
        instance_id = "inst-" + _digest(issue_id, path, line)[:12]
        facts = ctx.instance_facts.get(instance_id, InstanceFacts())
        instances.append(
            Instance(
                instance_id=instance_id,
                source=FlowStep(path=path, line=line or None) if path else None,
                occurrence_ids=tuple(sorted(occ.occurrence_id for occ in group)),
                facts=facts,
                severity=assess_facts(
                    facts, class_impact_range(class_id, catalog), catalog.severity_rubric
                ),
            )
        )
    return tuple(instances)


def _instances_for_dependency(
    issue_id: str, members: Sequence[Occurrence], catalog: CodeSecurityCatalog, ctx: AnalysisContext
) -> tuple[Instance, ...]:
    by_layer: dict[str, list[Occurrence]] = defaultdict(list)
    for occ in members:
        by_layer[occ.location.path].append(occ)
    instances: list[Instance] = []
    for layer, group in sorted(by_layer.items()):
        instance_id = "inst-" + _digest(issue_id, layer)[:12]
        facts = ctx.instance_facts.get(instance_id, InstanceFacts())
        scores = sorted({(occ.producer, occ.advisory_score) for occ in group if occ.advisory_score})
        severity = (
            assess_advisory(
                [(producer, float(score)) for producer, score in scores], catalog.severity_rubric
            )
            if scores
            else assess_facts(
                facts, class_impact_range(DEPENDENCY_CLASS, catalog), catalog.severity_rubric
            )
        )
        instances.append(
            Instance(
                instance_id=instance_id,
                source=FlowStep(path=layer, line=None),
                occurrence_ids=tuple(sorted(occ.occurrence_id for occ in group)),
                facts=facts,
                severity=severity,
            )
        )
    return tuple(instances)


def _issue(
    *,
    issue_id: str,
    class_id: str,
    title: str,
    members: Sequence[Occurrence],
    instances: tuple[Instance, ...],
    catalog: CodeSecurityCatalog,
    ctx: AnalysisContext,
    advisory_ids: tuple[str, ...] = (),
    package: str | None = None,
) -> CodeSecurityIssue:
    severity, governing_id = aggregate_issue_severity(instances)
    confidence = _confidence(issue_id, members, ctx)
    known_exploited = any(alias in ctx.known_exploited for alias in advisory_ids)
    priority = assign_priority(
        PriorityInput(severity.floor, severity.ceiling, confidence, ctx.exposure, known_exploited),
        catalog.priority_policy,
    )
    ordered = sorted(members, key=lambda occ: occ.occurrence_id)
    governing = next(item for item in instances if item.instance_id == governing_id)
    flow_source = next(
        (occ for occ in ordered if occ.occurrence_id in governing.occurrence_ids and occ.code_flow),
        None,
    )
    return CodeSecurityIssue(
        issue_id=issue_id,
        weakness_class=class_id,
        title=title,
        revision=ctx.revision,
        fix_site=ordered[0].location,
        severity=severity,
        governing_instance_id=governing_id,
        confidence=confidence,
        exposure=ctx.exposure,
        priority=priority,
        instances=instances,
        cwe_ids=tuple(sorted({cwe for occ in ordered for cwe in occ.cwe_ids})),
        producers=tuple(sorted({occ.producer for occ in ordered})),
        lanes=tuple(sorted({occ.lane for occ in ordered})),
        occurrence_ids=tuple(occ.occurrence_id for occ in ordered),
        source_severities=tuple(sorted({(occ.producer, occ.source_severity) for occ in ordered})),
        advisory_ids=advisory_ids,
        package=package,
        package_versions=tuple(
            sorted({occ.package_version for occ in ordered if occ.package_version})
        ),
        layers=tuple(sorted({occ.location.path for occ in ordered})) if advisory_ids else (),
        known_exploited=known_exploited,
        code_flow=flow_source.code_flow if flow_source else (),
        messages=tuple(dict.fromkeys(occ.message for occ in ordered if occ.message))[:5],
    )


def build_issues(
    occurrences: Sequence[Occurrence], catalog: CodeSecurityCatalog, ctx: AnalysisContext
) -> tuple[CodeSecurityIssue, ...]:
    """Collapse occurrences into canonical issues ordered by priority and severity."""
    if any(occ.revision != ctx.revision for occ in occurrences):
        raise ValueError("all occurrences must target the analysis revision")
    issues: list[CodeSecurityIssue] = []
    code = [occ for occ in occurrences if not occ.advisory_ids]
    for (class_id, path, line), members in sorted(_code_groups(code, catalog).items()):
        issue_id = "FDAI-SEC-" + _digest("code", class_id, path, line)[:12]
        entry = catalog.weakness_classes.classes.get(class_id)
        title = f"{entry.title} in {path}" if entry else f"{members[0].rule_id} in {path}"
        issues.append(
            _issue(
                issue_id=issue_id,
                class_id=class_id,
                title=title,
                members=members,
                instances=_instances_for_code(issue_id, class_id, members, catalog, ctx),
                catalog=catalog,
                ctx=ctx,
            )
        )
    for advisory, package_key, members in _dependency_groups(
        [occ for occ in occurrences if occ.advisory_ids]
    ):
        issue_id = "FDAI-SEC-" + _digest("dependency", advisory, package_key)[:12]
        aliases = tuple(sorted({alias for occ in members for alias in occ.advisory_ids}))
        issues.append(
            _issue(
                issue_id=issue_id,
                class_id=DEPENDENCY_CLASS,
                title=f"{advisory} in {package_key}",
                members=members,
                instances=_instances_for_dependency(issue_id, members, catalog, ctx),
                catalog=catalog,
                ctx=ctx,
                advisory_ids=aliases,
                package=members[0].package,
            )
        )
    return tuple(
        sorted(
            issues,
            key=lambda issue: (
                _PRIORITY_ORDER[issue.priority.priority.value],
                -BAND_ORDER[issue.severity.ceiling],
                -issue.severity.ceiling_points,
                issue.issue_id,
            ),
        )
    )


__all__ = [
    "DEPENDENCY_CLASS",
    "MISCONFIGURATION_CLASS",
    "SECRET_CLASS",
    "UNCLASSIFIED_PREFIX",
    "AnalysisContext",
    "build_issues",
    "class_impact_range",
    "normalized_package",
    "resolve_class",
]
