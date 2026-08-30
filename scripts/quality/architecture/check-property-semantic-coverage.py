#!/usr/bin/env python3
"""Measure reviewed Property semantic coverage and keep the documented value honest.

The reviewed-semantics registry (`rule-catalog/vocabulary/property-semantics.yaml`) covers only
part of the Property references that shipped rules evaluate. Every uncovered reference keeps its
legacy catalog projection and cannot claim `normalized_equivalence`. This gate measures that
coverage from repository data, rejects equivalence claims with no catalog evidence, rejects a
regression below the recorded floor, and rejects documentation that states a different number.

It also prints an evidence-ranked backlog so coverage grows for measured reasons instead of
arbitrary bulk authoring. The ranking uses three observable signals per uncovered reference:

1. how many distinct resource types expose the same leaf path (cross-provider equivalence risk),
2. how many shipped rules evaluate the reference (deterministic decision use), and
3. whether the leaf path carries a unit, magnitude, or enumeration marker (misreading risk).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import textwrap
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/core-control-plane/src"))
sys.path.insert(0, str(ROOT / "packages/service-contracts/src"))
sys.path.insert(0, str(ROOT / "extensions/cost-governance/src"))

import yaml  # noqa: E402
from fdai.core.capability_catalog import ExtensionManifest  # noqa: E402
from fdai.core.vertical_packages import VerticalPackageManager  # noqa: E402
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog  # noqa: E402
from fdai.rule_catalog.schema.property_semantic import (  # noqa: E402
    PropertySemanticRegistry,
)
from fdai.rule_catalog.schema.rego_semantics import property_path  # noqa: E402
from fdai.rule_catalog.schema.resource_type import (  # noqa: E402
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog  # noqa: E402
from fdai.rule_catalog.schema.signal_type import (  # noqa: E402
    load_signal_type_registry_from_mapping,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry  # noqa: E402

from fdai_cost_governance import (  # noqa: E402
    build_cost_governance_bundle,
    materialize_cost_governance_catalog,
)

BEGIN_MARKER = "<!-- property-semantic-coverage:begin -->"
END_MARKER = "<!-- property-semantic-coverage:end -->"
DOCUMENTS = (
    Path("docs/roadmap/architecture/operating-ontology.md"),
    Path("docs/roadmap/architecture/operating-ontology-ko.md"),
)
WRAP_WIDTH = 98
BACKLOG_PREVIEW = 12

# Reviewed references may only grow. Raise this floor in the same change that raises coverage.
REVIEWED_REFERENCE_FLOOR = 62
_PACKAGE_ARCHIVE = b"reviewed-fdai-cost-governance-coverage-wheel"
_PACKAGE_HOST_REFERENCES = {
    "action:remediate.remove-orphan-resource",
    "action:remediate.right-size",
    "action:remediate.set-retention-policy",
    "action:remediate.tag-add",
}

# Leaf-path markers that make a value easy to misread without reviewed semantics: a magnitude
# convention (percent versus ratio), a time or size unit, or a boolean versus enumeration shape.
UNIT_RISK_MARKERS = (
    "_bytes",
    "_count",
    "_days",
    "_enabled",
    "_hours",
    "_mode",
    "_percent",
    "_present",
    "_rate",
    "_ratio",
    "_required",
    "_seconds",
    "_tier",
    "_version",
)


@dataclass(frozen=True, slots=True)
class PropertyReference:
    """One Property reference that a shipped rule evaluates."""

    reference: str
    leaf_path: str
    decision_rule_count: int


class _TrustExactPackageArchive:
    def verify(self, manifest: ExtensionManifest, archive: bytes) -> bool:
        return manifest.archive_sha256 == hashlib.sha256(archive).hexdigest()


@dataclass(frozen=True, slots=True)
class RankedGap:
    """One uncovered reference with its deterministic priority signals."""

    reference: str
    provider_path_count: int
    decision_rule_count: int
    unit_risk: bool

    @property
    def score(self) -> int:
        return self.provider_path_count * 3 + self.decision_rule_count * 2 + int(self.unit_risk)


@dataclass(frozen=True, slots=True)
class Coverage:
    """Measured reviewed coverage over the rule-evaluated Property universe."""

    evaluated: tuple[PropertyReference, ...]
    reviewed_references: tuple[str, ...]
    semantic_count: int
    gaps: tuple[RankedGap, ...]

    @property
    def evaluated_count(self) -> int:
        return len(self.evaluated)

    @property
    def reviewed_count(self) -> int:
        return len(self.reviewed_references)

    @property
    def uncovered_count(self) -> int:
        return self.evaluated_count - self.reviewed_count

    @property
    def percent(self) -> str:
        if self.evaluated_count == 0:
            return "0.0"
        return f"{self.reviewed_count * 100 / self.evaluated_count:.1f}"


def _load(
    root: Path,
) -> tuple[
    tuple[PropertyReference, ...],
    PropertySemanticRegistry,
    frozenset[str],
]:
    catalog_root = root / "rule-catalog"
    schema_registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        catalog_root,
        schema_registry=schema_registry,
        probes_root=catalog_root / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    signal_types = load_signal_type_registry_from_mapping(
        yaml.safe_load((catalog_root / "vocabulary/signal-types.yaml").read_text(encoding="utf-8"))
    )
    base_rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=schema_registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
        policies_root=root / "policies",
    )
    bundle = build_cost_governance_bundle(
        archive_sha256=hashlib.sha256(_PACKAGE_ARCHIVE).hexdigest()
    )
    manager = VerticalPackageManager(
        host_version="0.1.3",
        ontology_release_digest=bundle.manifest.ontology_release_range,
        provider_bindings={"cost-estimator"},
        host_reference_ids=_PACKAGE_HOST_REFERENCES,
    ).install(
        bundle,
        archive=_PACKAGE_ARCHIVE,
        image_digest=f"sha256:{'f' * 64}",
        verifier=_TrustExactPackageArchive(),
    )
    package_catalog = materialize_cost_governance_catalog(
        manager.enable("cost-governance").runtime(),
        schema_registry=schema_registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
    )
    rules = (*base_rules, *package_catalog.rules)
    rule_ids = tuple(rule.id for rule in rules)
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("base and Cost Governance package catalogs duplicate rule ids")
    leaf_paths: dict[str, str] = {}
    usage: Counter[str] = Counter()
    for rule in rules:
        for reference in rule.evaluates:
            leaf_paths[reference] = property_path(rule.resource_type, reference)
            usage[reference] += 1
    evaluated = tuple(
        PropertyReference(
            reference=reference,
            leaf_path=leaf_paths[reference],
            decision_rule_count=usage[reference],
        )
        for reference in sorted(leaf_paths)
    )
    action_semantic_refs = frozenset(
        semantic_ref
        for action_type in ontology.action_types
        for semantic_ref in action_type.required_evidence_semantic_refs
    )
    return evaluated, ontology.property_semantics, action_semantic_refs


def measure(root: Path) -> tuple[Coverage, tuple[str, ...]]:
    """Measure coverage and return it with any evidence violations found."""

    evaluated, registry, action_semantic_refs = _load(root)
    evaluated_references = {item.reference for item in evaluated}
    declared = {
        provider_path.property_ref
        for semantic in registry.semantics
        for provider_path in semantic.equivalent_provider_paths
    }
    action_provider_paths = {
        provider_path.property_ref
        for semantic in registry.semantics
        if semantic.semantic_id in action_semantic_refs
        for provider_path in semantic.equivalent_provider_paths
    }
    violations = tuple(
        f"declared equivalent provider path has no shipped rule evidence: {reference}"
        for reference in sorted(declared - evaluated_references - action_provider_paths)
    )
    reviewed = tuple(
        item.reference for item in evaluated if registry.for_property(item.reference) is not None
    )
    leaf_usage: Counter[str] = Counter(item.leaf_path for item in evaluated)
    gaps = tuple(
        sorted(
            (
                RankedGap(
                    reference=item.reference,
                    provider_path_count=leaf_usage[item.leaf_path],
                    decision_rule_count=item.decision_rule_count,
                    unit_risk=any(marker in item.leaf_path for marker in UNIT_RISK_MARKERS),
                )
                for item in evaluated
                if item.reference not in set(reviewed)
            ),
            key=lambda gap: (-gap.score, gap.reference),
        )
    )
    coverage = Coverage(
        evaluated=evaluated,
        reviewed_references=reviewed,
        semantic_count=len(registry.semantics),
        gaps=gaps,
    )
    return coverage, violations


def _render_block(coverage: Coverage, document: Path) -> str:
    if document.name.endswith("-ko.md"):
        summary = (
            f"측정된 검토 커버리지: 룰이 평가하는 Property 참조 {coverage.evaluated_count}개 중 "
            f"**{coverage.reviewed_count}개**({coverage.percent}%)이며 검토된 의미는 "
            f"{coverage.semantic_count}개입니다. 이 수치는 손으로 관리하지 않고 커버리지 게이트가 "
            "계산합니다."
        )
        consequence = (
            "룰이 평가하는 모든 Property 참조가 검토된 의미와 범위가 제한된 정본 "
            "정규화를 가지며, 새 참조는 레지스트리나 floor를 갱신하지 않으면 gate를 "
            "통과하지 못합니다."
            if coverage.uncovered_count == 0
            else (
                f"나머지 {coverage.uncovered_count}개 참조는 이전 방식 변환 결과를 유지하므로 "
                "대부분의 Property는 `normalized_equivalence`를 주장할 수 없고 이 레지스트리로 "
                "값을 normalize할 수 없습니다."
            )
        )
    else:
        summary = (
            f"Measured reviewed coverage: **{coverage.reviewed_count} of "
            f"{coverage.evaluated_count}** rule-evaluated Property references "
            f"({coverage.percent}%) across {coverage.semantic_count} reviewed semantics, computed "
            "by the gate rather than by hand."
        )
        consequence = (
            "Every rule-evaluated Property reference has reviewed meaning and bounded canonical "
            "normalization; a new reference cannot pass the gate without updating the registry "
            "and floor."
            if coverage.uncovered_count == 0
            else (
                f"The other {coverage.uncovered_count} keep their legacy projection, so most "
                "Property instances cannot claim `normalized_equivalence`."
            )
        )
    paragraph = f"{summary} {consequence}"
    body = textwrap.fill(paragraph, width=WRAP_WIDTH, break_long_words=False)
    return f"{BEGIN_MARKER}\n{body}\n{END_MARKER}"


def _replace_block(text: str, block: str) -> str:
    start = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER) + len(END_MARKER)
    return text[:start] + block + text[end:]


def _check_documents(root: Path, coverage: Coverage, *, update: bool) -> tuple[str, ...]:
    failures: list[str] = []
    for relative in DOCUMENTS:
        document = root / relative
        text = document.read_text(encoding="utf-8")
        if BEGIN_MARKER not in text or END_MARKER not in text:
            failures.append(f"{relative}: missing the property-semantic-coverage block")
            continue
        block = _render_block(coverage, relative)
        if _replace_block(text, block) == text:
            continue
        if update:
            document.write_text(_replace_block(text, block), encoding="utf-8")
            continue
        failures.append(
            f"{relative}: documented Property semantic coverage is stale; "
            "rerun with --update to refresh the measured block"
        )
    return tuple(failures)


def _print_report(coverage: Coverage, *, show_all: bool) -> None:
    print(
        f"property-semantic-coverage: {coverage.reviewed_count}/{coverage.evaluated_count} "
        f"rule-evaluated Property references reviewed ({coverage.percent}%) "
        f"across {coverage.semantic_count} semantics"
    )
    gaps = coverage.gaps if show_all else coverage.gaps[:BACKLOG_PREVIEW]
    if not gaps:
        return
    print("priority backlog (paths x3, rules x2, unit risk x1):")
    for gap in gaps:
        print(
            f"  score={gap.score:>3}  paths={gap.provider_path_count}  "
            f"rules={gap.decision_rule_count}  unit_risk={'yes' if gap.unit_risk else 'no ':>3}  "
            f"{gap.reference}"
        )
    if not show_all and len(coverage.gaps) > len(gaps):
        print(f"  ... {len(coverage.gaps) - len(gaps)} more (use --report-all)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the measured coverage block in the tracked documents",
    )
    parser.add_argument(
        "--report-all",
        action="store_true",
        help="print every uncovered reference instead of the highest-priority preview",
    )
    args = parser.parse_args()

    coverage, violations = measure(ROOT)
    _print_report(coverage, show_all=args.report_all)

    failures = list(violations)
    if coverage.reviewed_count < REVIEWED_REFERENCE_FLOOR:
        failures.append(
            f"reviewed Property references regressed to {coverage.reviewed_count}; "
            f"the recorded floor is {REVIEWED_REFERENCE_FLOOR}"
        )
    failures.extend(_check_documents(ROOT, coverage, update=args.update))
    for failure in failures:
        print(f"property-semantic-coverage: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
