#!/usr/bin/env python3
"""Render deterministic bilingual wording variants for the golden dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

VARIATION_KINDS = (
    "audit_oriented",
    "concise",
    "contrastive",
    "direct",
    "evidence_first",
    "investigative",
    "operator_colloquial",
    "uncertainty_aware",
)

_PERSPECTIVE_LABELS_KO = {
    "action": "작업",
    "business": "비즈니스",
    "causal": "인과",
    "operation": "운영",
    "policy": "정책",
    "resource": "리소스",
    "service": "서비스",
}


def build_payloads(
    *,
    source_path: Path,
    coverage_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build English and Korean payloads from one reviewed source."""

    source_bytes = source_path.read_bytes()
    source = yaml.safe_load(source_bytes)
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict) or source.get("schema_version") != "1.0.0":
        raise ValueError("golden question source schema_version MUST be 1.0.0")
    dataset_version = source.get("dataset_version")
    if not isinstance(dataset_version, str):
        raise ValueError("golden question source dataset_version MUST be a string")
    entries = source.get("question_sets")
    if not isinstance(entries, list) or not entries:
        raise ValueError("golden question source MUST contain question_sets")

    coverage_entries = coverage.get("expectations")
    if not isinstance(coverage_entries, list):
        raise ValueError("golden coverage MUST contain expectations")
    coverage_by_id = {
        entry["expectation_id"]: entry
        for entry in coverage_entries
        if isinstance(entry, dict)
    }

    source_digest = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    questions: dict[str, list[dict[str, str]]] = {"en": [], "ko": []}
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("golden question set MUST be an object")
        expectation_id = entry.get("expectation_id")
        if not isinstance(expectation_id, str) or expectation_id in seen:
            raise ValueError("golden question expectation ids MUST be unique strings")
        if expectation_id not in coverage_by_id:
            raise ValueError(f"golden question expectation lacks coverage: {expectation_id}")
        seen.add(expectation_id)
        request = entry.get("request")
        if not isinstance(request, dict):
            raise ValueError(f"golden question request is invalid: {expectation_id}")
        for locale in ("en", "ko"):
            request_text = request.get(locale)
            if not isinstance(request_text, str) or not request_text.strip():
                raise ValueError(
                    f"golden question request is missing {locale}: {expectation_id}"
                )
            rendered = _render_variations(
                locale=locale,
                request=request_text.strip(),
                perspective=coverage_by_id[expectation_id]["perspective"],
            )
            questions[locale].extend(
                {
                    "case_id": f"{expectation_id}.{variation_kind}",
                    "expectation_id": expectation_id,
                    "runtime_context": coverage_by_id[expectation_id][
                        "runtime_context"
                    ],
                    "variation_kind": variation_kind,
                    "question": rendered[variation_kind],
                }
                for variation_kind in VARIATION_KINDS
            )

    expected_ids = set(coverage_by_id)
    if seen != expected_ids:
        missing = ", ".join(sorted(expected_ids - seen))
        extra = ", ".join(sorted(seen - expected_ids))
        raise ValueError(f"golden question coverage mismatch (missing={missing}; extra={extra})")

    def payload(locale: str) -> dict[str, Any]:
        return {
            "schema_version": "2.0.0",
            "dataset_version": dataset_version,
            "source_digest": source_digest,
            "locale": locale,
            "questions": sorted(questions[locale], key=lambda item: item["case_id"]),
        }

    return payload("en"), payload("ko")


def _render_variations(*, locale: str, request: str, perspective: str) -> dict[str, str]:
    request = request.rstrip(" .?")
    if locale == "en":
        direct = request[0].upper() + request[1:]
        return {
            "audit_oriented": f"For an audit-ready view, {request}.",
            "concise": f"Quick check: {request}.",
            "contrastive": (
                f"{direct}. Contrast observed facts with unsupported assumptions."
            ),
            "direct": f"{direct}.",
            "evidence_first": f"Using only verified evidence, {request}.",
            "investigative": (
                f"Investigate this from the {perspective} perspective: {request}."
            ),
            "operator_colloquial": f"Could you {request}?",
            "uncertainty_aware": (
                f"{direct}. Separate what is verified from what remains unknown."
            ),
        }
    if locale != "ko":
        raise ValueError(f"unsupported golden question locale: {locale}")
    perspective_label = _PERSPECTIVE_LABELS_KO[perspective]
    return {
        "audit_oriented": f"감사에 남길 수 있도록 답해 주세요. {request}.",
        "concise": f"빠르게 확인하고 싶어요. {request}.",
        "contrastive": f"{request}. 관측 사실과 근거 없는 추정을 구분해 주세요.",
        "direct": f"{request}.",
        "evidence_first": f"검증된 근거만 사용해 주세요. {request}.",
        "investigative": f"{perspective_label} 관점에서 조사해 주세요. {request}.",
        "operator_colloquial": f"지금 운영자가 확인해야 해요. {request}.",
        "uncertainty_aware": (
            f"{request}. 확인된 사실과 알 수 없는 부분을 나눠 주세요."
        ),
    }


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("eval/golden-dataset"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    english, korean = build_payloads(
        source_path=root / "questions.source.yaml",
        coverage_path=root / "coverage.json",
    )
    _write_payload(root / "questions.en.json", english)
    _write_payload(root / "questions.ko.json", korean)
    print(
        "golden-dataset: rendered "
        f"{len(english['questions'])} English and {len(korean['questions'])} Korean questions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())