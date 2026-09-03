"""Adapt existing FDAI question surfaces into one materialized question shape."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import yaml

_CASE_HEADING = re.compile(r"^### Q(?P<number>[0-9]{3}) (?P<title>.+)$")
_PROMPT_LINE = re.compile(
    r"^- (?P<label>원문|변형 A|변형 B|Original|Variant A|Variant B): "
    r"`(?P<text>.+)`$"
)
_EXPECTED_MANUAL_CASES = 120
_MIN_CANDIDATES = 50
_DOMAIN_ORDER = (
    "state_incident_detection",
    "root_cause_analysis",
    "change_deployment_impact",
    "dependency_impact",
    "capacity_performance_forecast",
    "reliability_policy_automation",
)


def collect_questions(
    *,
    source: dict[str, Any],
    source_paths: dict[str, Path],
    source_refs: dict[str, str],
    source_path: Path,
    repo_root: Path,
    candidate_paths: tuple[Path, ...],
) -> list[dict[str, Any]]:
    """Collect Golden, manual, Console, and candidate questions without changing them."""

    return [
        *_golden_questions(source, source_paths, source_refs),
        *_manual_questions(
            source,
            source_paths["manual_prompts"],
            source_refs["manual_prompts"],
        ),
        *_console_questions(source, source_paths, source_refs),
        *_candidate_questions(source, source_path, repo_root),
        *_external_candidate_questions(source, candidate_paths, repo_root),
    ]


def _golden_questions(
    source: dict[str, Any],
    paths: dict[str, Path],
    refs: dict[str, str],
) -> list[dict[str, Any]]:
    question_source = _yaml_object(paths["golden_questions"])
    expectations_payload = _json_object(paths["golden_expectations"])
    coverage_payload = _json_object(paths["golden_coverage"])
    localized = {
        "en": _localized_variations(_json_object(paths["golden_english"])),
        "ko": _localized_variations(_json_object(paths["golden_korean"])),
    }
    expectations = {
        _string(item["semantic_pair_id"], "semantic_pair_id"): item
        for item in _object_array(expectations_payload["cases"], "expectation cases")
    }
    coverage = {
        _string(item["expectation_id"], "expectation_id"): item
        for item in _object_array(coverage_payload["expectations"], "coverage expectations")
    }
    category_domains = _mapping(source["golden_category_domains"], "golden_category_domains")

    result: list[dict[str, Any]] = []
    for raw in _object_array(question_source["question_sets"], "question_sets"):
        expectation_id = _string(raw["expectation_id"], "expectation_id")
        expectation = expectations[expectation_id]
        coverage_item = coverage[expectation_id]
        category = _string(expectation["category"], "category")
        request = _mapping(raw["request"], "request")
        runtime_context = _string(coverage_item["runtime_context"], "runtime_context")
        result.append(
            {
                "question_id": f"golden.{expectation_id}",
                "source_kind": "golden",
                "domain": _string(category_domains[category], f"domain for {category}"),
                "intent": expectation_id,
                "title": expectation_id.replace("-", " ").title(),
                "wording": {
                    "en": _string(request["en"], "English request"),
                    "ko": _string(request["ko"], "Korean request"),
                },
                "variations": {
                    locale: localized[locale][expectation_id] for locale in ("en", "ko")
                },
                "readiness": {
                    "content_review": "reviewed",
                    "semantic_contract": "covered",
                    "runtime_binding": (
                        "clarify" if runtime_context == "explicit_target_required" else "bound"
                    ),
                    "evidence_source": "contract_only",
                    "validation": "contract_passed",
                },
                "safety": {
                    "action_posture": coverage_item["action_posture"],
                    "execution_authority": False,
                },
                "surfaces": ["golden"],
                "source_refs": [
                    refs["golden_questions"],
                    refs["golden_expectations"],
                    refs["golden_coverage"],
                    refs["golden_english"],
                    refs["golden_korean"],
                ],
                "legacy_ids": [expectation_id],
                "expected_posture": coverage_item["expected_posture"],
                "temporal_scope": _mapping(expectation["expected_semantics"], "expected_semantics")[
                    "temporal_scope"
                ],
                "required_context": {
                    "explicit_target_required": "explicit_target",
                    "incident_binding": "incident_binding",
                    "none": "none",
                    "server_scope": "server_scope",
                }[runtime_context],
            }
        )
    return result


def _localized_variations(payload: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in _object_array(payload["questions"], "localized questions"):
        expectation_id = _string(item["expectation_id"], "expectation_id")
        grouped.setdefault(expectation_id, []).append(
            {
                "kind": _string(item["variation_kind"], "variation_kind"),
                "text": _string(item["question"], "question"),
            }
        )
    return grouped


def _manual_questions(
    source: dict[str, Any],
    path: Path,
    source_ref: str,
) -> list[dict[str, Any]]:
    cases: dict[int, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = _CASE_HEADING.fullmatch(line)
        if heading:
            number = int(heading.group("number"))
            current = {"title": heading.group("title"), "prompts": []}
            cases[number] = current
            continue
        prompt = _PROMPT_LINE.fullmatch(line)
        if prompt and current is not None:
            current["prompts"].append((prompt.group("label"), prompt.group("text")))

    if sorted(cases) != list(range(1, _EXPECTED_MANUAL_CASES + 1)):
        raise ValueError("manual question pack MUST contain Q001 through Q120")

    result: list[dict[str, Any]] = []
    for korean_number in range(1, _EXPECTED_MANUAL_CASES + 1, 2):
        english_number = korean_number + 1
        korean = cases[korean_number]
        english = cases[english_number]
        _validate_manual_prompts(korean, ("원문", "변형 A", "변형 B"))
        _validate_manual_prompts(english, ("Original", "Variant A", "Variant B"))
        question_id = f"manual.q{korean_number:03d}-q{english_number:03d}"
        result.append(
            {
                "question_id": question_id,
                "source_kind": "manual",
                "domain": _manual_domain(source, korean_number),
                "intent": question_id,
                "title": f"{korean['title']} / {english['title']}",
                "wording": {
                    "en": english["prompts"][0][1],
                    "ko": korean["prompts"][0][1],
                },
                "variations": {
                    "en": _manual_variations(english["prompts"]),
                    "ko": _manual_variations(korean["prompts"]),
                },
                "readiness": {
                    "content_review": "source_controlled",
                    "semantic_contract": "partial",
                    "runtime_binding": "mixed",
                    "evidence_source": "unassessed",
                    "validation": "not_run",
                },
                "safety": {
                    "action_posture": "read_only",
                    "execution_authority": False,
                },
                "surfaces": ["manual"],
                "source_refs": [source_ref],
                "legacy_ids": [f"Q{korean_number:03d}", f"Q{english_number:03d}"],
            }
        )
    return result


def _manual_variations(prompts: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"kind": kind, "text": text}
        for kind, (_, text) in zip(
            ("direct", "variant_a", "variant_b"),
            prompts,
            strict=True,
        )
    ]


def _validate_manual_prompts(case: dict[str, Any], expected_labels: tuple[str, str, str]) -> None:
    labels = tuple(label for label, _ in case["prompts"])
    if labels != expected_labels:
        raise ValueError(f"manual case {case['title']} has invalid prompt labels: {labels}")


def _manual_domain(source: dict[str, Any], question_number: int) -> str:
    matches = [
        _string(item["domain"], "manual domain")
        for item in _object_array(source["manual_domain_ranges"], "manual_domain_ranges")
        if int(item["first"]) <= question_number <= int(item["last"])
    ]
    if len(matches) != 1:
        raise ValueError(f"manual question Q{question_number:03d} MUST map to one domain")
    return matches[0]


def _console_questions(
    source: dict[str, Any],
    paths: dict[str, Path],
    refs: dict[str, str],
) -> list[dict[str, Any]]:
    english = _mapping(_json_object(paths["console_english"])["deck"], "English deck")
    korean = _mapping(_json_object(paths["console_korean"])["deck"], "Korean deck")
    result: list[dict[str, Any]] = []
    for item in _object_array(source["console_questions"], "console_questions"):
        question_id = _string(item["id"], "console id")
        catalog = _string(item["catalog"], "console catalog")
        key = _string(item["key"], "console key")
        english_catalog = _mapping(english[catalog], f"English {catalog}")
        korean_catalog = _mapping(korean[catalog], f"Korean {catalog}")
        result.append(
            {
                "question_id": f"console.{question_id}",
                "source_kind": "console",
                "domain": item["domain"],
                "intent": item["intent"],
                "title": key.replace("_", " ").title(),
                "wording": {
                    "en": _string(english_catalog[key], f"English {catalog} {key}"),
                    "ko": _string(korean_catalog[key], f"Korean {catalog} {key}"),
                },
                "variations": {"en": [], "ko": []},
                "readiness": {
                    "content_review": "reviewed",
                    "semantic_contract": "covered",
                    "runtime_binding": "bound",
                    "evidence_source": "retained",
                    "validation": "contract_passed",
                },
                "safety": {
                    "action_posture": "read_only",
                    "execution_authority": False,
                },
                "surfaces": ["console"],
                "source_refs": [refs["console_english"], refs["console_korean"]],
                "legacy_ids": [f"deck.{catalog}.{key}"],
            }
        )
    return result


def _candidate_questions(
    source: dict[str, Any],
    source_path: Path,
    repo_root: Path,
) -> list[dict[str, Any]]:
    defaults = _mapping(source["candidate_defaults"], "candidate_defaults")
    groups = _object_array(source["candidate_groups"], "candidate_groups")
    domains = [_string(group["domain"], "candidate domain") for group in groups]
    if tuple(sorted(domains)) != tuple(sorted(_DOMAIN_ORDER)):
        raise ValueError("candidate groups MUST define each operator domain exactly once")

    result: list[dict[str, Any]] = []
    for group in groups:
        domain = _string(group["domain"], "candidate domain")
        for item in _object_array(group["questions"], "candidate questions"):
            question_id = _string(item["id"], "candidate id")
            wording = _mapping(item["wording"], "candidate wording")
            result.append(
                {
                    "question_id": question_id,
                    "source_kind": "candidate",
                    "domain": domain,
                    "intent": item["intent"],
                    "title": question_id.split(".", 1)[-1].replace("-", " ").title(),
                    "wording": {"en": wording["en"], "ko": wording["ko"]},
                    "variations": {"en": [], "ko": []},
                    "readiness": deepcopy(item.get("readiness", defaults["readiness"])),
                    "safety": deepcopy(item.get("safety", defaults["safety"])),
                    "surfaces": deepcopy(item.get("surfaces", defaults["surfaces"])),
                    "source_refs": [source_path.relative_to(repo_root).as_posix()],
                    "legacy_ids": [],
                    "temporal_scope": item["temporal_scope"],
                    "result_shape": item["result_shape"],
                    "required_context": item["required_context"],
                    "target_kinds": item["target_kinds"],
                }
            )
    if len(result) < _MIN_CANDIDATES:
        raise ValueError(
            f"operator candidate bank MUST contain at least {_MIN_CANDIDATES} questions"
        )
    return result


def _external_candidate_questions(
    source: dict[str, Any],
    paths: tuple[Path, ...],
    repo_root: Path,
) -> list[dict[str, Any]]:
    defaults = _mapping(source["candidate_defaults"], "candidate_defaults")
    result: list[dict[str, Any]] = []
    for path in paths:
        payload = _yaml_object(path)
        source_id = _string(payload["source_id"], "candidate source id")
        source_ref = path.relative_to(repo_root).as_posix()
        for item in _object_array(payload["questions"], f"{source_id} questions"):
            question_id = _string(item["id"], "candidate id")
            wording = _mapping(item["wording"], "candidate wording")
            result.append(
                {
                    "question_id": question_id,
                    "source_kind": "candidate",
                    "domain": item["domain"],
                    "intent": item["intent"],
                    "title": question_id.split(".", 1)[-1].replace("-", " ").title(),
                    "wording": {"en": wording["en"], "ko": wording["ko"]},
                    "variations": {"en": [], "ko": []},
                    "readiness": deepcopy(defaults["readiness"]),
                    "safety": deepcopy(item.get("safety", defaults["safety"])),
                    "surfaces": deepcopy(defaults["surfaces"]),
                    "source_refs": [source_ref],
                    "legacy_ids": [],
                    "temporal_scope": item["temporal_scope"],
                    "result_shape": item["result_shape"],
                    "required_context": item["required_context"],
                    "target_kinds": item["target_kinds"],
                    "category": item["category"],
                    **({"duplicate_of": item["duplicate_of"]} if "duplicate_of" in item else {}),
                }
            )
    return result


def _yaml_object(path: Path) -> dict[str, Any]:
    return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), path.as_posix())


def _json_object(path: Path) -> dict[str, Any]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), path.as_posix())


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} MUST be an object")
    return cast(dict[str, Any], value)


def _object_array(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} MUST be an array of objects")
    return cast(list[dict[str, Any]], value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} MUST be a non-empty string")
    return value


__all__ = ["collect_questions"]
