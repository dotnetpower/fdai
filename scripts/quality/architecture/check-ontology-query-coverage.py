#!/usr/bin/env python3
"""Enforce shipped ontology structural coverage and terminal question cohorts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/core-control-plane/src"))
sys.path.insert(0, str(ROOT / "packages/service-contracts/src"))

from fdai.core.conversation.coverage_gate import (  # noqa: E402
    QuestionDispositionRecord,
    evaluate_ontology_query_coverage,
    require_ontology_query_coverage,
)
from fdai.core.conversation.semantic_manifest import CatalogQueryManifestProvider  # noqa: E402
from fdai.core.conversation.session import Principal, Role  # noqa: E402
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog  # noqa: E402
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry  # noqa: E402
from fdai.shared.ontology.release import build_ontology_release  # noqa: E402
from fdai_service_contracts.ontology_query import StructuralCoverageReceipt  # noqa: E402


def _questions() -> tuple[QuestionDispositionRecord, ...]:
    payload = json.loads(
        (ROOT / "config/ontology-query-competency.json").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0.0":
        raise ValueError("ontology query competency schema_version is invalid")
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        raise ValueError("ontology query competency questions MUST be an array")
    return tuple(QuestionDispositionRecord(**item) for item in raw_questions)


def _structural_receipts() -> tuple[StructuralCoverageReceipt, ...]:
    catalog_root = ROOT / "rule-catalog"
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=catalog_root / "probes",
    )
    release = build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
    )
    provider = CatalogQueryManifestProvider(
        release=release,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interfaces=catalog.interface_types,
    )
    return tuple(
        provider.manifest_for(
            principal=Principal(id=f"coverage-{role.value}", role=role),
            purpose="operations-review",
        ).coverage_receipt
        for role in (Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)
    )


def _require_exact_only_default() -> None:
    source = (
        ROOT / "services/core-control-plane/src/fdai/core/conversation/coordinator.py"
    ).read_text(encoding="utf-8")
    expected_declaration = 'ordinary_language_mode: Literal["exact_only", "legacy"] = "exact_only"'
    if expected_declaration not in source:
        raise ValueError("ordinary-language coordinator default is not exact-only")
    if "def _match_exact_command" not in source:
        raise ValueError("explicit exact-command surface is unavailable")


def main() -> int:
    try:
        _require_exact_only_default()
        receipt = evaluate_ontology_query_coverage(
            structural_receipts=_structural_receipts(),
            questions=_questions(),
        )
        require_ontology_query_coverage(receipt)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"ontology-query-coverage: ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "ontology-query-coverage: OK "
        f"(questions={receipt.accepted_question_count}, "
        f"principal_manifests={len(receipt.principal_receipt_digests)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
