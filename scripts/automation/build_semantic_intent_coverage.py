#!/usr/bin/env python3
"""Build the FDAI conversation quality assurance scorecard."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fdai.agents._framework.pantheon import PANTHEON_SPECS
from scripts.automation.conversation_quality_metrics import (
    HARD_ZERO_METRICS,
    METRIC_GROUPS,
    MODEL_CHANGE_POLICY,
    OPERATING_DOMAINS,
    QUALITY_COVERAGE_LIMITATIONS,
    SCORECARD,
    SCORING_POLICY,
)
from scripts.automation.conversation_quality_sources import (
    digest,
    enum_values,
    has_answer_oracle,
    json_object,
    paths_digest,
    presentation_registry_kinds,
    query_function_names,
    ratio,
    required_question_bank_domains,
    sha256,
    string_set_assignment,
    typescript_string_union,
    yaml_object,
)
from scripts.automation.presentation_quality_metrics import (
    PRESENTATION_EVALUATION_AXES,
)

_ratio = ratio


def build_inventory(root: Path) -> dict[str, Any]:
    """Build a source-derived topic inventory and current evaluation coverage."""
    golden = json_object(root / "eval/golden-dataset/expectations.json")
    question_bank = json_object(root / "eval/golden-dataset/question-bank/question-bank.json")
    question_bank_source = yaml_object(
        root / "eval/golden-dataset/question-bank/question-bank.source.yaml"
    )
    intent_cases = yaml_object(root / "eval/golden-dataset/azure-incident-intent-golden.yaml")
    adequacy_path = (
        root / "services/core-control-plane/src/fdai/core/conversation/question_adequacy.py"
    )
    criteria_path = (
        root / "services/core-control-plane/src/fdai/core/conversation_assurance/models.py"
    )
    adaptive_answer_path = (
        root / "packages/service-contracts/src/fdai_service_contracts/adaptive_answer.py"
    )
    presentation_planner_path = (
        root
        / "services/operator-service/src/fdai_operator_service/families/conversation"
        / "presentation_planner.py"
    )
    presentation_backend_types_path = root / "console/src/deck/backend-types.ts"
    presentation_module_types_path = root / "console/src/deck/presentation-modules/types.ts"
    presentation_registry_path = root / "console/src/deck/presentation-modules/registry.tsx"
    function_root = root / "services/core-control-plane/src/fdai/core/ontology_platform"
    function_source_paths = sorted(function_root.glob("*.py"))
    function_names = query_function_names(function_source_paths)
    golden_functions = Counter(
        function_name
        for case in golden["cases"]
        for function_name in case["semantic_retrieval"]["required_function_types"]
    )
    intent_functions = Counter(
        intent
        for case in intent_cases["cases"]
        for intent in (
            case["expected"]["primary_intent"],
            *case["expected"].get("secondary_intents", []),
        )
        if intent.startswith("query.")
    )
    unknown_function_refs = (set(golden_functions) | set(intent_functions)) - set(function_names)
    if unknown_function_refs:
        raise ValueError(
            "semantic intent sources reference undeclared query functions: "
            f"{sorted(unknown_function_refs)}"
        )
    question_domain_rows = []
    for spec in PANTHEON_SPECS:
        for domain in spec.question_domains:
            question_domain_rows.append(
                {
                    "topic_id": domain,
                    "agent": spec.name,
                    "semantic_contract_case_count": 0,
                    "coverage_state": "unmapped",
                }
            )
    bank_questions = question_bank["questions"]
    bank_domains = Counter(item["domain"] for item in bank_questions)
    bank_categories = Counter(item.get("category") or "uncategorized" for item in bank_questions)
    golden_categories = Counter(item["category"] for item in golden["cases"])
    required_bank_domains = required_question_bank_domains(question_bank_source)
    required_golden_categories = set(question_bank_source["golden_category_domains"])
    answer_oracle_count = sum(has_answer_oracle(case) for case in golden["cases"])
    presentation_kinds = enum_values(presentation_planner_path, "PresentationKind")
    presentation_registry = presentation_registry_kinds(presentation_registry_path)
    if set(presentation_kinds) != presentation_registry:
        raise ValueError("Operator presentation kinds and Console registrations MUST match exactly")
    presentation_oracle_count = sum(
        bool(item.get("presentation_oracle")) for item in bank_questions
    )
    function_rows = [
        {
            "topic_id": name,
            "golden_expectation_count": golden_functions[name],
            "intent_contract_case_count": intent_functions[name],
            "coverage_state": (
                "reviewed_golden"
                if golden_functions[name]
                else ("intent_contract_only" if intent_functions[name] else "missing_case")
            ),
        }
        for name in function_names
    ]
    readiness = Counter(
        (
            item["readiness"]["content_review"],
            item["readiness"]["semantic_contract"],
            item["readiness"]["runtime_binding"],
            item["readiness"]["evidence_source"],
            item["readiness"]["validation"],
        )
        for item in bank_questions
    )
    inventory = {
        "operating_domains": _operating_domain_rows(bank_questions, OPERATING_DOMAINS),
        "question_bank_domains": [
            _question_topic_row(name, bank_domains[name], bank_questions, "domain")
            for name in sorted(required_bank_domains | set(bank_domains))
        ],
        "question_bank_categories": [
            _question_topic_row(name, count, bank_questions, "category")
            for name, count in sorted(bank_categories.items())
        ],
        "golden_categories": [
            {"topic_id": name, "expectation_count": golden_categories[name]}
            for name in sorted(required_golden_categories | set(golden_categories))
        ],
        "pantheon_question_domains": sorted(
            question_domain_rows,
            key=lambda item: (item["agent"], item["topic_id"]),
        ),
        "ontology_query_functions": function_rows,
    }
    reviewed_bank_count = sum(count for keys, count in readiness.items() if keys[0] == "reviewed")
    validated_bank_count = sum(
        count for keys, count in readiness.items() if keys[-1] == "contract_passed"
    )
    pantheon_covered = sum(item["coverage_state"] == "covered" for item in question_domain_rows)
    function_any_covered = sum(item["coverage_state"] != "missing_case" for item in function_rows)
    body = {
        "schema_version": "1.1.0",
        "artifact_kind": "conversation_quality_assurance_scorecard",
        "scorecard": {
            **SCORECARD,
            "metric_count": sum(len(metrics) for metrics in METRIC_GROUPS.values()),
        },
        "model_change_policy": MODEL_CHANGE_POLICY,
        "source_digests": {
            path.relative_to(root).as_posix(): sha256(path)
            for path in (
                root / "eval/golden-dataset/expectations.json",
                root / "eval/golden-dataset/question-bank/question-bank.json",
                root / "eval/golden-dataset/question-bank/question-bank.source.yaml",
                root / "eval/golden-dataset/azure-incident-intent-golden.yaml",
                root / "services/core-control-plane/src/fdai/agents/_framework/pantheon.py",
                adaptive_answer_path,
                adequacy_path,
                criteria_path,
                presentation_planner_path,
                (
                    root
                    / "services/operator-service/src/fdai_operator_service/families/conversation"
                    / "presentation_artifact_v3.py"
                ),
                root / "console/src/deck/presentation-artifact.ts",
                root / "console/src/deck/presentation-modules/charts.tsx",
                presentation_backend_types_path,
                presentation_module_types_path,
                presentation_registry_path,
                root / "scripts/automation/conversation_quality_metrics.py",
                root / "scripts/automation/conversation_quality_sources.py",
                root / "scripts/automation/presentation_quality_metrics.py",
                root / "scripts/automation/semantic_intent_metrics.py",
            )
        }
        | {
            "services/core-control-plane/src/fdai/core/ontology_platform/*.py": (
                paths_digest(root, function_source_paths)
            )
        },
        "topic_inventory": inventory,
        "evaluation_axes": _evaluation_axes(
            bank_questions,
            intent_cases["cases"],
            adequacy_path=adequacy_path,
            criteria_path=criteria_path,
            presentation_planner_path=presentation_planner_path,
            presentation_backend_types_path=presentation_backend_types_path,
            presentation_module_types_path=presentation_module_types_path,
        ),
        "scoring_policy": SCORING_POLICY,
        "metric_contract": {group: list(metrics) for group, metrics in METRIC_GROUPS.items()},
        "coverage_metrics": {
            "golden_category_coverage": _ratio(
                len(required_golden_categories & set(golden_categories)),
                len(required_golden_categories),
            ),
            "question_bank_domain_inventory_coverage": _ratio(
                len(required_bank_domains & set(bank_domains)),
                len(required_bank_domains),
            ),
            "question_bank_reviewed_rate": _ratio(reviewed_bank_count, len(bank_questions)),
            "question_bank_contract_validation_rate": _ratio(
                validated_bank_count, len(bank_questions)
            ),
            "pantheon_domain_semantic_contract_coverage": _ratio(
                pantheon_covered, len(question_domain_rows)
            ),
            "ontology_query_function_golden_coverage": _ratio(
                sum(bool(golden_functions[name]) for name in function_names),
                len(function_names),
            ),
            "ontology_query_function_any_contract_coverage": _ratio(
                function_any_covered, len(function_names)
            ),
            "golden_answer_oracle_coverage": _ratio(answer_oracle_count, len(golden["cases"])),
            "presentation_block_registry_coverage": _ratio(
                len(set(presentation_kinds) & presentation_registry),
                len(presentation_kinds),
            ),
            "question_presentation_oracle_coverage": _ratio(
                presentation_oracle_count, len(bank_questions)
            ),
            "paired_model_case_coverage": _ratio(0, len(bank_questions)),
        },
        "hard_zero_metrics": list(HARD_ZERO_METRICS),
        "coverage_limitations": list(QUALITY_COVERAGE_LIMITATIONS),
    }
    body["inventory_digest"] = digest(body)
    return body


def _question_topic_row(
    name: str,
    count: int,
    questions: list[dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    matching = [item for item in questions if (item.get(field) or "uncategorized") == name]
    reviewed = sum(item["readiness"]["content_review"] == "reviewed" for item in matching)
    contract_validated = sum(
        item["readiness"]["validation"] == "contract_passed" for item in matching
    )
    return {
        "topic_id": name,
        "question_count": count,
        "reviewed": _ratio(reviewed, count),
        "contract_validated": _ratio(contract_validated, count),
    }


def _operating_domain_rows(
    questions: list[dict[str, Any]],
    operating_domains: dict[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    rows = []
    for domain, bank_domain_ids in operating_domains.items():
        matching = [item for item in questions if item["domain"] in bank_domain_ids]
        reviewed = sum(item["readiness"]["content_review"] == "reviewed" for item in matching)
        validated = sum(item["readiness"]["validation"] == "contract_passed" for item in matching)
        rows.append(
            {
                "topic_id": domain,
                "mapping_kind": "reviewed_evaluation_crosswalk",
                "question_bank_domains": list(bank_domain_ids),
                "question_count": len(matching),
                "reviewed": _ratio(reviewed, len(matching)),
                "contract_validated": _ratio(validated, len(matching)),
            }
        )
    return rows


def _evaluation_axes(
    questions: list[dict[str, Any]],
    intent_cases: list[dict[str, Any]],
    *,
    adequacy_path: Path,
    criteria_path: Path,
    presentation_planner_path: Path,
    presentation_backend_types_path: Path,
    presentation_module_types_path: Path,
) -> dict[str, list[str]]:
    return {
        "action_postures": sorted(
            {item["safety"]["action_posture"] for item in questions}
            | {item["expected"]["action_posture"] for item in intent_cases}
        ),
        "discourse_modes": sorted({item["expected"]["discourse_mode"] for item in intent_cases}),
        "evidence_postures": [
            "conflicting",
            "fresh",
            "incomplete",
            "stale",
            "unavailable",
        ],
        "locales": ["en", "ko", "mixed"],
        "result_shapes": sorted({item.get("result_shape") or "unspecified" for item in questions}),
        "target_kinds": sorted(
            {target for item in questions for target in item.get("target_kinds", [])}
            | {target["kind"] for item in intent_cases for target in item["expected"]["targets"]}
        ),
        "temporal_scopes": sorted(
            {item.get("temporal_scope") or "unspecified" for item in questions}
        ),
        "terminal_postures": [
            "action_draft",
            "answered",
            "clarification",
            "held",
            "unsupported",
        ],
        "answer_adequacy_gates": string_set_assignment(adequacy_path, "_REQUIRED_GATES"),
        "answer_review_criteria": enum_values(criteria_path, "AssuranceCriterion"),
        "presentation_intents": enum_values(presentation_planner_path, "PresentationIntent"),
        "presentation_kinds": enum_values(presentation_planner_path, "PresentationKind"),
        "presentation_semantic_shapes": enum_values(presentation_planner_path, "SemanticShape"),
        "visualization_kinds": enum_values(presentation_planner_path, "VisualizationKind"),
        "presentation_layouts": typescript_string_union(
            presentation_backend_types_path, "PresentationLayout"
        ),
        "responsive_policies": typescript_string_union(
            presentation_module_types_path, "PresentationResponsivePolicy"
        ),
        "accessibility_fallbacks": typescript_string_union(
            presentation_module_types_path, "PresentationAccessibilityFallback"
        ),
        **PRESENTATION_EVALUATION_AXES,
    }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("eval/golden-dataset/semantic-intent-coverage.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    payload = build_inventory(root)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != content:
            print(
                "semantic-intent-coverage: stale generated artifact; regenerate with "
                "python scripts/automation/build_semantic_intent_coverage.py",
                file=sys.stderr,
            )
            return 1
        print("semantic-intent-coverage: OK (generated inventory matches authoritative sources)")
        return 0
    _write_text(output, content)
    metrics = payload["coverage_metrics"]
    print(
        "conversation-quality-assurance: "
        + ", ".join(
            f"{name}={value['covered']}/{value['total']}" for name, value in metrics.items()
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
