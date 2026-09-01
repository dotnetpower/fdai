"""Build one reviewable question bank from FDAI's existing question surfaces."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator
from scripts.automation.question_bank_sources import collect_questions

_DOMAIN_ORDER = (
    "state_incident_detection",
    "root_cause_analysis",
    "change_deployment_impact",
    "dependency_impact",
    "capacity_performance_forecast",
    "reliability_policy_automation",
    "cost_finops",
)
_DOMAIN_LABELS = {
    "state_incident_detection": ("State and incident detection", "상태 및 장애 감지"),
    "root_cause_analysis": ("Root-cause analysis", "원인 분석"),
    "change_deployment_impact": ("Change and deployment impact", "변경 및 배포 영향"),
    "dependency_impact": ("Dependency and impact", "의존성 및 영향도"),
    "capacity_performance_forecast": (
        "Capacity, performance, and forecast",
        "용량, 성능 및 예측",
    ),
    "reliability_policy_automation": (
        "Reliability, policy, and automation",
        "안정성, 정책 및 자동화",
    ),
    "cost_finops": ("Cost and FinOps", "비용 및 FinOps"),
}


def build_question_bank(*, repo_root: Path, source_path: Path) -> dict[str, Any]:
    """Build and validate the materialized question bank without writing files."""

    repo_root = repo_root.resolve()
    source_path = source_path.resolve()
    source = _yaml_object(source_path)
    source_schema_path = source_path.with_name("question-bank.source.schema.json")
    _validator(source_schema_path).validate(source)

    source_paths = {
        name: _repository_path(repo_root, value)
        for name, value in _mapping(source["sources"], "sources").items()
    }
    source_refs = {
        name: cast(str, _mapping(source["sources"], "sources")[name]) for name in source_paths
    }
    candidate_paths = tuple(
        _repository_path(repo_root, value)
        for value in _array(source["candidate_sources"], "candidate_sources")
    )
    expansion_validator = _validator(source_path.with_name("question-expansion.source.schema.json"))
    for path in candidate_paths:
        expansion_validator.validate(_yaml_object(path))

    questions = collect_questions(
        source=source,
        source_paths=source_paths,
        source_refs=source_refs,
        source_path=source_path,
        repo_root=repo_root,
        candidate_paths=candidate_paths,
    )
    questions.sort(key=lambda item: cast(str, item["question_id"]))
    identities = [cast(str, item["question_id"]) for item in questions]
    if len(identities) != len(set(identities)):
        duplicates = sorted(
            identity for identity, count in Counter(identities).items() if count > 1
        )
        raise ValueError(f"question bank ids MUST be unique: {duplicates}")
    _reject_duplicate_wording(questions)

    source_files = _source_files(
        repo_root,
        (source_path, *source_paths.values(), *candidate_paths),
    )
    digest_input = json.dumps(
        source_files,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    source_counts = Counter(cast(str, item["source_kind"]) for item in questions)
    domain_counts = Counter(cast(str, item["domain"]) for item in questions)
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "catalog_version": _string(source["catalog_version"], "catalog_version"),
        "source_digest": "sha256:" + hashlib.sha256(digest_input).hexdigest(),
        "source_files": source_files,
        "summary": {
            "question_count": len(questions),
            "source_counts": dict(sorted(source_counts.items())),
            "domain_counts": dict(sorted(domain_counts.items())),
        },
        "questions": questions,
    }
    _validator(source_path.with_name("question-bank.schema.json")).validate(payload)
    return payload


def render_review_catalog(payload: dict[str, Any]) -> str:
    """Render a generated bilingual review view from a validated question bank."""

    summary = _mapping(payload["summary"], "summary")
    source_counts = _mapping(summary["source_counts"], "source_counts")
    domain_counts = _mapping(summary["domain_counts"], "domain_counts")
    questions = _array(payload["questions"], "questions")
    lines = [
        "# FDAI Question Bank Review Catalog",
        "",
        "This generated catalog brings FDAI's Golden questions, manual browser prompts, "
        "Console starters, and operator candidates into one review view. Edit the referenced "
        "source files and regenerate this catalog instead of editing this file.",
        "",
        "> The catalog is a read-only inventory. A listed question does not prove that its "
        "semantic contract, runtime binding, evidence source, or live validation is available.",
        "",
        "## Catalog summary",
        "",
        f"- Catalog version: `{payload['catalog_version']}`",
        f"- Source digest: `{payload['source_digest']}`",
        f"- Logical questions: {summary['question_count']}",
        "- Source counts: "
        + ", ".join(f"`{key}` {value}" for key, value in sorted(source_counts.items())),
        "",
        "| Operator domain | Count |",
        "|-----------------|------:|",
    ]
    for domain in _DOMAIN_ORDER:
        english, korean = _DOMAIN_LABELS[domain]
        lines.append(f"| {english} / {korean} | {domain_counts.get(domain, 0)} |")

    lines.extend(
        [
            "",
            "## Readiness axes",
            "",
            "| Axis | Meaning |",
            "|------|---------|",
            "| Content review | Whether wording is a candidate, source-controlled, "
            "or formally reviewed. |",
            "| Semantic contract | Whether a typed intent and answer oracle are "
            "unassessed, partial, or covered. |",
            "| Runtime binding | Whether context and providers are unassessed, "
            "unavailable, clarification-bound, bound, or mixed. |",
            "| Evidence source | Whether evidence is unassessed, contract-only, "
            "retained, or live. |",
            "| Validation | Whether no run, contract validation, or live validation "
            "has completed. |",
            "",
        ]
    )

    for domain in _DOMAIN_ORDER:
        english, korean = _DOMAIN_LABELS[domain]
        lines.extend(
            [
                f"## {english} / {korean}",
                "",
                "| ID | Source | Category | Korean question | English question | Context | "
                "Duplicate of | Readiness | Surface |",
                "|----|--------|----------|-----------------|------------------|---------|"
                "--------------|-----------|---------|",
            ]
        )
        for raw in questions:
            item = _mapping(raw, "question")
            if item["domain"] != domain:
                continue
            wording = _mapping(item["wording"], "wording")
            readiness = _mapping(item["readiness"], "readiness")
            readiness_text = (
                f"{readiness['content_review']} / {readiness['semantic_contract']} / "
                f"{readiness['runtime_binding']} / {readiness['evidence_source']} / "
                f"{readiness['validation']}"
            )
            context = item.get("required_context", "source-defined")
            lines.append(
                "| "
                + " | ".join(
                    (
                        f"`{item['question_id']}`",
                        f"`{item['source_kind']}`",
                        f"`{item.get('category', 'source-defined')}`",
                        _markdown_cell(wording["ko"]),
                        _markdown_cell(wording["en"]),
                        f"`{context}`",
                        (f"`{item['duplicate_of']}`" if "duplicate_of" in item else "-"),
                        f"`{readiness_text}`",
                        ", ".join(f"`{value}`" for value in item["surfaces"]),
                    )
                )
                + " |"
            )
        lines.append("")

    lines.extend(
        [
            "## Source custody",
            "",
            "| Source file | SHA-256 |",
            "|-------------|---------|",
        ]
    )
    for raw in _array(payload["source_files"], "source_files"):
        item = _mapping(raw, "source file")
        lines.append(f"| `{item['path']}` | `{item['digest']}` |")
    lines.append("")
    return "\n".join(lines)


def _source_files(repo_root: Path, paths: tuple[Path, ...]) -> list[dict[str, str]]:
    unique = sorted(set(paths))
    return [
        {
            "path": path.relative_to(repo_root).as_posix(),
            "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in unique
    ]


def _reject_duplicate_wording(questions: list[dict[str, Any]]) -> None:
    for locale in ("en", "ko"):
        identities_by_text: dict[str, list[str]] = {}
        for item in questions:
            wording = _mapping(item["wording"], "wording")
            normalized = " ".join(_string(wording[locale], "question wording").split()).casefold()
            identities_by_text.setdefault(normalized, []).append(
                _string(item["question_id"], "question_id")
            )
        duplicates = {
            text: identities
            for text, identities in identities_by_text.items()
            if len(identities) > 1
        }
        by_id = {_string(item["question_id"], "question_id"): item for item in questions}
        for identities in duplicates.values():
            canonical = [
                identity for identity in identities if "duplicate_of" not in by_id[identity]
            ]
            if len(canonical) != 1 or any(
                by_id[identity].get("duplicate_of") != canonical[0]
                for identity in identities
                if identity != canonical[0]
            ):
                raise ValueError(
                    f"question bank {locale} duplicate wording requires one canonical id: "
                    f"{sorted(identities)}"
                )


def _repository_path(repo_root: Path, value: object) -> Path:
    relative = Path(_string(value, "repository path"))
    path = (repo_root / relative).resolve()
    if not path.is_relative_to(repo_root):
        raise ValueError(f"question-bank source escapes repository root: {relative}")
    if not path.is_file():
        raise ValueError(f"question-bank source is missing: {relative}")
    return path


def _validator(path: Path) -> Draft202012Validator:
    schema = _json_object(path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _yaml_object(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _mapping(value, path.as_posix())


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(value, path.as_posix())


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} MUST be an object")
    return cast(dict[str, Any], value)


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} MUST be an array")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} MUST be a non-empty string")
    return value


def _markdown_cell(value: object) -> str:
    return _string(value, "Markdown cell").replace("|", "\\|").replace("\n", " ")


__all__ = ["build_question_bank", "render_review_catalog"]
