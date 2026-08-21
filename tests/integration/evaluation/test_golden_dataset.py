"""Contract tests for the bilingual cloud-operations golden dataset."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator
from scripts.automation.build_golden_dataset import VARIATION_KINDS, build_payloads

_ROOT = Path(__file__).resolve().parents[3]
_DATASET_ROOT = _ROOT / "eval" / "golden-dataset"
_OBJECT_ROOT = _ROOT / "rule-catalog" / "vocabulary" / "object-types"
_LINK_ROOT = _ROOT / "rule-catalog" / "vocabulary" / "link-types"
_RUNTIME_ROOT = _ROOT / "services" / "core-control-plane" / "src"


def _json(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((_DATASET_ROOT / name).read_text(encoding="utf-8")),
    )


def _schema(name: str) -> Draft202012Validator:
    schema = _json(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _link_declarations() -> dict[str, dict[str, Any]]:
    declarations: dict[str, dict[str, Any]] = {}
    for path in sorted(_LINK_ROOT.glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(value, dict), path
        declarations[str(value["name"])] = value
    return declarations


def _iter_keyed_arrays(value: object) -> Iterable[tuple[str, list[object]]]:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, list):
                yield key, item
            yield from _iter_keyed_arrays(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_keyed_arrays(item)


def test_golden_dataset_satisfies_strict_schemas_and_bilingual_parity() -> None:
    expectations = _json("expectations.json")
    coverage = _json("coverage.json")
    english = _json("questions.en.json")
    korean = _json("questions.ko.json")

    _schema("expectations.schema.json").validate(expectations)
    _schema("coverage.schema.json").validate(coverage)
    question_schema = _schema("questions.schema.json")
    question_schema.validate(english)
    question_schema.validate(korean)

    assert english["locale"] == "en"
    assert korean["locale"] == "ko"
    assert expectations["dataset_version"] == coverage["dataset_version"] == "2.0.0"
    assert expectations["dataset_version"] == english["dataset_version"]
    assert expectations["dataset_version"] == korean["dataset_version"]
    assert english["source_digest"] == korean["source_digest"]

    expected_ids = [case["semantic_pair_id"] for case in expectations["cases"]]
    coverage_ids = [case["expectation_id"] for case in coverage["expectations"]]
    english_identities = [
        (case["case_id"], case["expectation_id"], case["variation_kind"])
        for case in english["questions"]
    ]
    korean_identities = [
        (case["case_id"], case["expectation_id"], case["variation_kind"])
        for case in korean["questions"]
    ]
    assert len(expected_ids) == 35
    assert expected_ids == sorted(set(expected_ids))
    assert coverage_ids == expected_ids
    assert len(english_identities) == len(korean_identities) == 280
    assert english_identities == korean_identities
    assert english_identities == sorted(set(english_identities))
    assert {identity[1] for identity in english_identities} == set(expected_ids)
    assert all(case["question"] == case["question"].strip() for case in english["questions"])
    assert all(case["question"] == case["question"].strip() for case in korean["questions"])
    keyed_arrays = tuple(_iter_keyed_arrays(expectations))
    assert all(
        all(not str(item).startswith("query.") for item in items)
        for key, items in keyed_arrays
        if key == "required_capabilities"
    )
    assert all(
        all(str(item).startswith("query.") for item in items)
        for key, items in keyed_arrays
        if key == "required_function_types"
    )


def test_golden_generated_artifacts_match_reviewed_source() -> None:
    expected_english, expected_korean = build_payloads(
        source_path=_DATASET_ROOT / "questions.source.yaml",
        coverage_path=_DATASET_ROOT / "coverage.json",
    )

    assert _json("questions.en.json") == expected_english
    assert _json("questions.ko.json") == expected_korean


def test_golden_coverage_spans_all_reviewed_assurance_axes() -> None:
    coverage = _json("coverage.json")
    expectations = {case["semantic_pair_id"]: case for case in _json("expectations.json")["cases"]}
    rows = coverage["expectations"]

    assert Counter(row["perspective"] for row in rows) == {
        "action": 5,
        "business": 5,
        "causal": 5,
        "operation": 5,
        "policy": 5,
        "resource": 5,
        "service": 5,
    }
    assert {row["evidence_posture"] for row in rows} == {
        "conflicting",
        "fresh",
        "incomplete",
        "stale",
        "unavailable",
    }
    assert {row["case_class"] for row in rows} == {
        "access_filtered",
        "boundary",
        "positive",
        "zero_match",
    }
    assert {row["anchor_kind"] for row in rows} == {
        "none",
        "selected_incident",
        "selected_object",
        "server_scope",
    }
    assert {row["expected_posture"] for row in rows} == {
        "action_draft",
        "answer",
        "clarify",
        "hold",
        "unsupported",
    }

    dispositions = {
        "action_draft": "action_draft",
        "answer": "answered",
        "clarify": "clarification",
        "hold": "held",
        "unsupported": "unsupported",
    }
    for row in rows:
        expectation = expectations[row["expectation_id"]]
        assert (
            dispositions[row["expected_posture"]]
            in expectation["expected_semantics"]["allowed_dispositions"]
        )
        assert (row["action_posture"] == "draft_only") == (row["perspective"] == "action")
        if row["perspective"] == "action":
            assert expectation["expected_semantics"]["operation"] == "action_draft"
    assert Counter(row["rule_state"] for row in rows)["active"] == 1
    assert Counter(row["rule_state"] for row in rows)["collected"] == 1


def test_golden_runtime_context_matches_supported_bindings() -> None:
    coverage = _json("coverage.json")
    expectations = {case["semantic_pair_id"]: case for case in _json("expectations.json")["cases"]}
    english = _json("questions.en.json")
    korean = _json("questions.ko.json")
    rows = {row["expectation_id"]: row for row in coverage["expectations"]}
    context_by_anchor = {
        "none": "none",
        "selected_incident": "incident_binding",
        "selected_object": "explicit_target_required",
        "server_scope": "server_scope",
    }

    assert {row["runtime_context"] for row in rows.values()} == {
        "explicit_target_required",
        "incident_binding",
        "none",
        "server_scope",
    }
    for row in rows.values():
        assert row["runtime_context"] == context_by_anchor[row["anchor_kind"]]
        if row["runtime_context"] == "explicit_target_required":
            assert row["expected_posture"] == "clarify"
            assert (
                "clarification"
                in expectations[row["expectation_id"]]["expected_semantics"]["allowed_dispositions"]
            )

    for payload in (english, korean):
        for case in payload["questions"]:
            assert case["runtime_context"] == rows[case["expectation_id"]]["runtime_context"]
    assert all(
        not re.search(r"\bselected\b", case["question"], flags=re.IGNORECASE)
        for case in english["questions"]
    )
    assert all("선택한" not in case["question"] for case in korean["questions"])


def test_golden_questions_cover_sanitized_resource_scenarios() -> None:
    source = yaml.safe_load((_DATASET_ROOT / "questions.source.yaml").read_text(encoding="utf-8"))
    bilingual_product_terms = {
        "aks",
        "application gateway",
        "appgw",
        "pod",
    }
    corpus_terms = bilingual_product_terms | {
        "container apps",
        "event hubs",
        "key vault",
        "network security group",
        "postgresql",
        "private endpoint",
        "storage",
        "virtual machine",
    }
    requests_by_locale = {
        locale: "\n".join(
            str(question_set["request"][locale]) for question_set in source["question_sets"]
        ).casefold()
        for locale in ("en", "ko")
    }
    combined_requests = "\n".join(requests_by_locale.values())
    assert all(term in combined_requests for term in corpus_terms)
    for requests in requests_by_locale.values():
        assert all(term in requests for term in bilingual_product_terms)
        assert (
            re.search(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                requests,
            )
            is None
        )
        assert "/subscriptions/" not in requests
        assert "/resourcegroups/" not in requests
        assert ".azure.com" not in requests
    for question_set in source["question_sets"]:
        for request in question_set["request"].values():
            if "appgw" in request.casefold():
                assert "application gateway" in request.casefold()


def test_golden_wording_is_varied_within_each_locale_and_expectation() -> None:
    for filename in ("questions.en.json", "questions.ko.json"):
        payload = _json(filename)
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for case in payload["questions"]:
            grouped[case["expectation_id"]].append(case)

        all_questions = [case["question"].casefold() for case in payload["questions"]]
        assert len(all_questions) == len(set(all_questions)) == 280
        assert Counter(case["variation_kind"] for case in payload["questions"]) == {
            variation_kind: 35 for variation_kind in VARIATION_KINDS
        }
        for cases in grouped.values():
            assert {case["variation_kind"] for case in cases} == set(VARIATION_KINDS)
            opening_signatures = {
                tuple(re.findall(r"[0-9a-z가-힣]+", case["question"].casefold())[:3])
                for case in cases
            }
            assert len(opening_signatures) >= 6


def test_golden_expectations_are_canonical_and_read_only() -> None:
    expectations = _json("expectations.json")

    for key, values in _iter_keyed_arrays(expectations):
        if key.startswith("required_") or key == "forbidden_claims":
            assert all(isinstance(value, str) for value in values), key
            string_values = cast(list[str], values)
            assert string_values == sorted(set(string_values)), key
    for case in expectations["cases"]:
        retrieval = case["semantic_retrieval"]
        answer = case["answer_oracle"]
        assert retrieval["require_exact_release"] is True
        assert retrieval["require_principal_scope"] is True
        assert retrieval["allow_legacy_route"] is False
        assert answer["evidence_required"] is True
        assert answer["execution_authority"] is False
        assert "execution.completed" in answer["forbidden_claims"]


def test_golden_ontology_paths_match_shipped_catalog_direction() -> None:
    expectations = _json("expectations.json")
    object_types = {path.stem for path in _OBJECT_ROOT.glob("*.yaml")}
    link_types = _link_declarations()

    for case in expectations["cases"]:
        retrieval = case["semantic_retrieval"]
        ontology = case["expected_ontology"]
        referenced_objects = set(retrieval["required_object_types"])
        referenced_links = set(retrieval["required_link_types"])
        assert referenced_objects <= object_types, case["semantic_pair_id"]
        assert referenced_links <= link_types.keys(), case["semantic_pair_id"]
        assert ontology["anchor_type"] in referenced_objects
        assert set(ontology["target_types"]) <= referenced_objects

        path_depths: list[int] = []
        for path in ontology["paths"]:
            steps = path["steps"]
            path_depths.append(len(steps))
            assert steps[0]["from_type"] == ontology["anchor_type"]
            for index, step in enumerate(steps):
                declaration = link_types[step["link_type"]]
                if step["direction"] == "outgoing":
                    assert step["from_type"] == declaration["from_type"]
                    assert step["to_type"] == declaration["to_type"]
                else:
                    assert step["from_type"] == declaration["to_type"]
                    assert step["to_type"] == declaration["from_type"]
                if index:
                    assert steps[index - 1]["to_type"] == step["from_type"]
            assert steps[-1]["to_type"] in ontology["target_types"]

        if path_depths:
            assert min(path_depths) == ontology["min_traversal_depth"]
            assert max(path_depths) == ontology["max_traversal_depth"]
        else:
            assert ontology["min_traversal_depth"] == 0
            assert ontology["max_traversal_depth"] == 0


def test_golden_function_types_exist_in_active_runtime() -> None:
    expectations = _json("expectations.json")
    runtime_source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(_RUNTIME_ROOT.rglob("*.py"))
    )

    function_types = {
        function_name
        for case in expectations["cases"]
        for function_name in case["semantic_retrieval"]["required_function_types"]
    }
    assert function_types
    assert all(function_name.startswith("query.") for function_name in function_types)
    for function_name in function_types:
        assert function_name in runtime_source, function_name
