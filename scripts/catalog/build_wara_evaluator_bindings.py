#!/usr/bin/env python3
"""Build exact WARA evaluator overlays and a complete per-GUID semantic-review ledger.

Run after build_wara_assessment.py. This consumes explicitly reviewed semantics, never
infers a verdict from query syntax, a recommendation title, or automationAvailable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from fdai.core.rule_activation.generation import rule_digest
from fdai.delivery.wara_rule_evidence import _release_rules
from fdai.rule_catalog.schema.wara_assessment import (
    WaraAssessmentCatalog,
    WaraQueryBody,
    WaraQueryCatalog,
    canonical_digest,
)
from fdai.rule_catalog.schema.wara_evaluator_binding import (
    WaraEvaluatorBinding,
    WaraObservationRequirement,
)
from fdai.rule_catalog.schema.wara_rule_binding import (
    WaraRuleBindingCatalog,
    load_wara_rule_bindings,
)
from wara_evaluation_semantics import (
    AUTOMATED_IDENTITIES_DIGEST,
    BLOCKED,
    EXACT,
    REVIEWED_RULE_BINDINGS_DIGEST,
    RULE,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSESSMENT = ROOT / "rule-catalog/collected/wara-aprl/assessment"


def build(assessment: Path) -> tuple[dict[str, object], dict[str, object]]:
    crosswalk = json.loads((assessment / "crosswalk.json").read_text(encoding="utf-8"))
    queries = json.loads((assessment / "queries.json").read_text(encoding="utf-8"))
    bodies = {
        query.aprl_guid: query.decoded_body()
        for raw in queries["queries"]
        for query in (WaraQueryBody.model_validate(raw),)
    }
    identities = [
        {"aprl_guid": query["aprl_guid"], "body_digest": query["body_digest"]}
        for query in queries["queries"]
    ]
    if canonical_digest(identities) != AUTOMATED_IDENTITIES_DIGEST:
        raise ValueError(
            "WARA automated query identities changed; explicit semantic re-review required"
        )
    selectors = [entry["aprl_guid"][:8] for entry in identities]
    reviewed = (*EXACT, *RULE, *BLOCKED)
    if len(set(reviewed)) != len(reviewed) or set(reviewed) != set(selectors):
        raise ValueError("WARA semantic review MUST cover each pinned automated GUID exactly once")
    records = {record["aprl_guid"]: record for record in crosswalk["recommendations"]}
    if {r["aprl_guid"] for r in records.values() if r["automation_available"]} != {
        entry["aprl_guid"] for entry in identities
    }:
        raise ValueError("WARA automatic review set differs from the crosswalk")
    bindings = []
    reviews = []
    for query in queries["queries"]:
        guid = query["aprl_guid"]
        selector = guid[:8]
        record = records[guid]
        query_review = record["query_review"]
        requirements = []
        semantic_blockers = []
        if selector in EXACT:
            rationale, (regional, fields) = EXACT[selector]
            requirements = [
                WaraObservationRequirement(
                    path="type",
                    value_type="string",
                    allowed_values=(
                        record["provider_resource_type"],
                        record["provider_resource_type"].lower(),
                    ),
                )
            ]
            requirements.extend(WaraObservationRequirement.model_validate(item) for item in fields)
            if regional:
                # The review explicitly selected a regional query under the identity-set pin.
                body = bodies[guid]
                clauses = re.findall(r"\blocation\s+in~?\s*\(([^)]+)\)", body, flags=re.I)
                locations = tuple(
                    sorted(
                        set(
                            value
                            for clause in clauses
                            for value in re.findall(r"""["']([^"']+)["']""", clause)
                        )
                    )
                )
                if not locations:
                    raise ValueError(f"{guid}: reviewed regional eligibility has no exact literals")
                requirements.append(
                    WaraObservationRequirement(
                        path="location",
                        value_type="string",
                        allowed_values=locations,
                    )
                )
            decision = "exact_query"
        elif selector in RULE:
            rationale = RULE[selector]
            decision = "t0_rule"
        else:
            rationale = BLOCKED[selector]
            semantic_blockers = [rationale]
            decision = "blocked"
        admission_blockers = [
            reason
            for reason in query_review["blocked_reasons"]
            if reason != "missing_exact_evaluator"
        ]
        if record["applicability"]["disposition"] != "canonical":
            admission_blockers.append("resource_type_not_canonical")
        if query_review["declared_tables"] != ["resources"]:
            admission_blockers.append("provider_requires_resources_table")
        bindable = decision == "exact_query" and not admission_blockers
        if bindable:
            bindings.append(
                WaraEvaluatorBinding(
                    aprl_guid=guid,
                    query_digest=query["body_digest"],
                    evaluator_ref="azure-resource-graph.matching-rows-failed.v1",
                    provider="azure_resource_graph",
                    semantics="matching_rows_failed",
                    resource_id_column="id",
                    reviewer="fdai-maintainers",
                    review_state="reviewed-exact",
                    observation_requirements=tuple(requirements),
                ).model_dump(mode="json")
            )
        reviews.append(
            {
                "aprl_guid": guid,
                "query_digest": query["body_digest"],
                "decision": decision,
                "binding_status": "bound"
                if bindable
                else ("existing_t0_rule" if decision == "t0_rule" else "blocked"),
                "rationale": rationale,
                "resource_identity": "exact_scoped_resource_id" if bindable else "not_admitted",
                "empty_result_meaning": (
                    "satisfied_only_after_all_typed_observation_and_eligibility_guards"
                    if bindable
                    else "no_query_satisfaction_verdict"
                ),
                "observation_requirements": [r.model_dump(mode="json") for r in requirements],
                "blockers": sorted(set(admission_blockers + semantic_blockers)),
            }
        )
    overlay = {
        "schema_version": "1.0.0",
        "source_revision": crosswalk["source_revision"],
        "crosswalk_digest": crosswalk["crosswalk_digest"],
        "bindings": bindings,
    }
    overlay["overlay_digest"] = canonical_digest(overlay)
    ledger = {
        "schema_version": "1.0.0",
        "source_revision": crosswalk["source_revision"],
        "automated_identities_digest": AUTOMATED_IDENTITIES_DIGEST,
        "reviewed_rule_bindings_digest": REVIEWED_RULE_BINDINGS_DIGEST,
        "reviews": reviews,
    }
    ledger["review_digest"] = canonical_digest(ledger)
    return overlay, ledger


def build_rule_overlay(assessment: Path) -> dict[str, object]:
    """Re-pin unchanged reviewed Rule bindings; semantic or Rule revision drift fails closed."""

    path = assessment / "rule-bindings.json"
    original = WaraRuleBindingCatalog.model_validate_json(path.read_text(encoding="utf-8"))
    material = original.model_dump(mode="json")
    if canonical_digest(material["bindings"]) != REVIEWED_RULE_BINDINGS_DIGEST:
        raise ValueError("WARA reviewed Rule binding material changed; explicit re-review required")
    catalog = WaraAssessmentCatalog.model_validate_json(
        (assessment / "crosswalk.json").read_text(encoding="utf-8")
    )
    queries = WaraQueryCatalog.model_validate_json(
        (assessment / "queries.json").read_text(encoding="utf-8")
    )
    # Validate today's records/queries/Rules against the unchanged reviewed binding. Only
    # the comparison pin uses the old crosswalk identity; the output uses the verified new one.
    load_wara_rule_bindings(
        path,
        catalog=catalog.model_copy(update={"crosswalk_digest": original.crosswalk_digest}),
        queries=queries,
        rules=_release_rules(ROOT),
        rule_digest=rule_digest,
    )
    material["crosswalk_digest"] = catalog.crosswalk_digest
    material.pop("overlay_digest")
    material["overlay_digest"] = canonical_digest(material)
    WaraRuleBindingCatalog.model_validate(material)
    return material


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assessment-root", type=Path, default=DEFAULT_ASSESSMENT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    overlay, ledger = build(args.assessment_root)
    rule_overlay = build_rule_overlay(args.assessment_root)
    outputs = {
        "evaluator-bindings.json": overlay,
        "evaluation-semantics.json": ledger,
        "rule-bindings.json": rule_overlay,
    }
    for filename, material in outputs.items():
        path = args.assessment_root / filename
        rendered = json.dumps(material, indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                print(f"{path}: stale WARA reviewed evaluation output", file=sys.stderr)
                return 1
        else:
            path.write_text(rendered, encoding="utf-8")
    print(
        f"WARA exact query bindings: {len(overlay['bindings'])}; "
        f"Rule bindings: {len(rule_overlay['bindings'])}; semantic reviews: 143"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
