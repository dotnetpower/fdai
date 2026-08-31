"""Repository-backed Best Practice and evidence composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from fdai.composition.readiness_evidence import (
    ArchitectureReviewChecklistEvidenceProvider,
)
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.probe import load_probe_catalog, probe_ids
from fdai.shared.contracts.models import BestPractice, RequirementKind


def load_runtime_best_practice_bindings(
    catalog_root: Path,
) -> tuple[
    tuple[BestPractice, ...],
    ArchitectureReviewChecklistEvidenceProvider,
]:
    """Load the pinned checklist and its typed, scope-aware evidence provider."""

    review_path = catalog_root.parent / "config" / "architecture-review.yaml"
    raw: Any = yaml.safe_load(review_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("config/architecture-review.yaml MUST contain a mapping")
    registries = _reference_registries(catalog_root, raw)
    controls = load_best_practice_catalog(
        catalog_root / "best-practices",
        known_refs=registries,
    )
    return controls, ArchitectureReviewChecklistEvidenceProvider(raw)


def _reference_registries(
    catalog_root: Path,
    manifest: Mapping[str, Any],
) -> dict[RequirementKind, set[str]]:
    review = _mapping(manifest.get("architecture_review"), "architecture_review")
    gate = _mapping(review.get("production_gate"), "production_gate")
    artifacts = _sequence(review.get("artifacts"), "artifacts")
    required = {
        str(item)
        for item in _sequence(
            gate.get("checklist_required_evidence"),
            "checklist_required_evidence",
        )
    }
    evidence_kinds = _mapping(gate.get("evidence_kinds"), "evidence_kinds")
    if set(evidence_kinds) != required:
        raise ValueError("evidence_kinds MUST classify checklist_required_evidence exactly once")
    artifact_ids = {str(_mapping(item, "artifact").get("id")) for item in artifacts}
    rules = {
        str(_mapping(yaml.safe_load(path.read_text(encoding="utf-8")), path.name)["id"])
        for path in sorted((catalog_root / "catalog").glob("*.yaml"))
    }
    return {
        RequirementKind.RULE: rules,
        RequirementKind.PROBE: probe_ids(load_probe_catalog(catalog_root / "probes")),
        RequirementKind.ARTIFACT: artifact_ids
        | {str(ref) for ref, kind in evidence_kinds.items() if kind == "artifact"},
        RequirementKind.METRIC: {
            str(ref) for ref, kind in evidence_kinds.items() if kind == "metric"
        },
        RequirementKind.DRILL: {
            str(ref) for ref, kind in evidence_kinds.items() if kind == "drill"
        },
        RequirementKind.APPROVAL: {
            str(item)
            for item in _sequence(
                gate.get("required_owner_slots"),
                "required_owner_slots",
            )
        },
    }


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be a mapping")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} MUST be a sequence")
    return value


__all__ = ["load_runtime_best_practice_bindings"]
