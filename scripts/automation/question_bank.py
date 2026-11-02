"""Build one reviewable question bank from FDAI's existing question surfaces."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, cast

import yaml
from fdai.rule_catalog.schema._zstd_compat import zstd_runtime as zstd
from jsonschema import Draft202012Validator
from scripts.automation.question_bank_sources import collect_questions

_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_MAX_QUESTION_BANK_BYTES = 16 * 1024 * 1024

_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_IPV4_PATTERN = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
_ESCAPED_HANGUL_PATTERN = re.compile(r"\\u(?:ac|ad|[b-d][0-9a-f])[0-9a-f]{2}", re.IGNORECASE)
_FORBIDDEN_PUNCTUATION = frozenset(
    {"\u2013", "\u2014", "\u2018", "\u2019", "\u201c", "\u201d", "\u2026", "\u00a0"}
)
_FORBIDDEN_SUBSTRINGS = ("/subscriptions/", "/resourcegroups/", ".azure.com")

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
    _validate_duplicate_references(questions)
    _reject_duplicate_wording(questions)
    _validate_wording_hygiene(questions)

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


def _validate_duplicate_references(questions: list[dict[str, Any]]) -> None:
    by_id = {_string(item["question_id"], "question_id"): item for item in questions}
    for question_id, item in by_id.items():
        if "duplicate_of" not in item:
            continue
        target_id = _string(item["duplicate_of"], "duplicate_of")
        if target_id == question_id:
            raise ValueError(f"question bank duplicate_of MUST NOT self-reference: {question_id}")
        target = by_id.get(target_id)
        if target is None:
            raise ValueError(
                f"question bank duplicate_of references unknown question id: "
                f"{question_id} -> {target_id}"
            )
        if "duplicate_of" in target:
            raise ValueError(
                f"question bank duplicate_of MUST reference a canonical non-duplicate id: "
                f"{question_id} -> {target_id}"
            )


def _validate_text_hygiene(text: str, *, question_id: str, locale: str) -> None:
    lowered = text.casefold()
    for token in _FORBIDDEN_SUBSTRINGS:
        if token in lowered:
            raise ValueError(
                f"question bank wording contains customer-specific token {token!r}: "
                f"{question_id} ({locale})"
            )
    if _UUID_PATTERN.search(text) is not None:
        raise ValueError(f"question bank wording contains a UUID literal: {question_id} ({locale})")
    if _IPV4_PATTERN.search(text) is not None:
        raise ValueError(
            f"question bank wording contains an IPv4 literal: {question_id} ({locale})"
        )
    if any(char in _FORBIDDEN_PUNCTUATION for char in text):
        raise ValueError(
            f"question bank wording contains non-ASCII smart punctuation: {question_id} ({locale})"
        )
    if _ESCAPED_HANGUL_PATTERN.search(text) is not None:
        raise ValueError(
            f"question bank wording contains escaped Hangul literals: {question_id} ({locale})"
        )


def _validate_wording_hygiene(questions: list[dict[str, Any]]) -> None:
    for item in questions:
        question_id = _string(item["question_id"], "question_id")
        safety = _mapping(item.get("safety", {"execution_authority": False}), "safety")
        if safety.get("execution_authority") is not False:
            raise ValueError(
                f"question bank item MUST keep execution_authority=False: {question_id}"
            )
        wording = _mapping(item["wording"], "wording")
        variations = _mapping(item.get("variations", {"en": [], "ko": []}), "variations")
        for locale in ("en", "ko"):
            text = _string(wording[locale], f"{question_id}.{locale}")
            _validate_text_hygiene(text, question_id=question_id, locale=locale)
            for variation in _array(
                variations.get(locale, []), f"{question_id}.variations.{locale}"
            ):
                var_map = _mapping(variation, f"{question_id}.variation")
                var_text = _string(var_map["text"], f"{question_id}.variation.text")
                _validate_text_hygiene(
                    var_text, question_id=question_id, locale=f"{locale}.variation"
                )


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
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} MUST be a non-empty string")
    return value


def _markdown_cell(value: object) -> str:
    return " ".join(_string(value, "Markdown cell").split()).replace("|", "\\|")


def compress_question_bank_bundle(
    payload: dict[str, Any],
    *,
    level: int = 19,
) -> bytes:
    """Serialize and Zstandard-compress a validated question-bank payload."""
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return bytes(zstd.compress(serialized, level=level))


def decompress_question_bank_bundle(
    data: bytes,
    *,
    max_output_size: int = _MAX_QUESTION_BANK_BYTES,
) -> dict[str, Any]:
    """Decompress and schema-validate a Zstandard-compressed question-bank bundle."""
    if not isinstance(data, (bytes, bytearray)) or bytes(data[:4]) != _ZSTD_MAGIC:
        raise ValueError("question-bank bundle MUST start with the Zstandard magic header")
    decompressor = zstd.ZstdDecompressor()
    output = decompressor.decompress(bytes(data), max_length=max_output_size + 1)
    if len(output) > max_output_size or not decompressor.eof or decompressor.unused_data:
        raise ValueError("question-bank bundle exceeds max_output_size or has trailing data")
    loaded = json.loads(output.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("question-bank bundle MUST decode to a JSON object")
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "eval/golden-dataset/question-bank/question-bank.schema.json"
    )
    _validator(schema_path).validate(loaded)
    return cast(dict[str, Any], loaded)


def compress_questions_with_dictionary(
    questions: list[dict[str, Any]],
    *,
    dict_size: int = 32 * 1024,
    level: int = 3,
) -> dict[str, Any]:
    """Train a shared Zstandard dictionary and compress each question row individually."""
    if len(questions) < 8:
        raise ValueError("dictionary compression requires at least 8 questions")
    samples = [
        json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        for item in questions
    ]
    zdict = zstd.train_dict(samples, dict_size=dict_size)
    dict_bytes = bytes(zdict.dict_content)
    compressed_rows = [zstd.compress(sample, level=level, zstd_dict=zdict) for sample in samples]
    raw_total = sum(len(sample) for sample in samples)
    comp_total = sum(len(row) for row in compressed_rows)
    return {
        "dict_id": int(zdict.dict_id),
        "dict_sha256": "sha256:" + hashlib.sha256(dict_bytes).hexdigest(),
        "dict_bytes": dict_bytes,
        "question_count": len(questions),
        "uncompressed_total_bytes": raw_total,
        "compressed_total_bytes": comp_total,
        "compression_ratio": raw_total / comp_total if comp_total > 0 else 1.0,
        "compressed_rows": tuple(compressed_rows),
    }


def decompress_questions_with_dictionary(
    bundle: dict[str, Any],
    *,
    max_row_bytes: int = 256 * 1024,
) -> list[dict[str, Any]]:
    """Decompress individual question rows using their shared Zstandard dictionary."""
    dict_bytes = bytes(bundle["dict_bytes"])
    expected_sha = str(bundle["dict_sha256"])
    if "sha256:" + hashlib.sha256(dict_bytes).hexdigest() != expected_sha:
        raise ValueError("question dictionary SHA-256 mismatch")
    zdict = zstd.ZstdDict(dict_bytes)
    if int(zdict.dict_id) != int(bundle["dict_id"]):
        raise ValueError("question dictionary ID mismatch")
    restored: list[dict[str, Any]] = []
    for raw_row in bundle["compressed_rows"]:
        decompressor = zstd.ZstdDecompressor(zstd_dict=zdict)
        decoded = decompressor.decompress(bytes(raw_row), max_length=max_row_bytes + 1)
        if len(decoded) > max_row_bytes or not decompressor.eof or decompressor.unused_data:
            raise ValueError("compressed question row exceeds max_row_bytes or is malformed")
        restored.append(_mapping(json.loads(decoded.decode("utf-8")), "question row"))
    if len(restored) != int(bundle["question_count"]):
        raise ValueError("question count mismatch in dictionary bundle")
    return restored


__all__ = [
    "build_question_bank",
    "compress_question_bank_bundle",
    "compress_questions_with_dictionary",
    "decompress_question_bank_bundle",
    "decompress_questions_with_dictionary",
    "render_review_catalog",
]
