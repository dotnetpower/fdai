"""Shared builders for code-security finding tests (synthetic, customer-agnostic data)."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from fdai.rule_catalog.code_security import CodeSecurityCatalog, load_code_security_catalog

REPO_ROOT = Path(__file__).resolve().parents[6]
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "code-security"
REVISION = "a" * 40


@cache
def catalog() -> CodeSecurityCatalog:
    return load_code_security_catalog(CATALOG_ROOT)


def result(
    rule_id: str,
    path: str,
    line: int,
    *,
    cwe: int | None = None,
    message: str = "finding",
    flow: list[tuple[str, int]] | None = None,
    properties: dict[str, Any] | None = None,
    level: str = "error",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "ruleId": rule_id,
        "level": level,
        "message": {"text": message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": path},
                    "region": {"startLine": line},
                }
            }
        ],
    }
    if cwe is not None:
        item["properties"] = {"tags": [f"external/cwe/cwe-{cwe:03d}"]}
    if properties:
        item.setdefault("properties", {}).update(properties)
    if flow:
        item["codeFlows"] = [
            {
                "threadFlows": [
                    {
                        "locations": [
                            {
                                "location": {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": step_path},
                                        "region": {"startLine": step_line},
                                    }
                                }
                            }
                            for step_path, step_line in flow
                        ]
                    }
                ]
            }
        ]
    return item


def sarif(
    producer: str, results: list[dict[str, Any]], rules: list[dict[str, Any]] | None = None
) -> bytes:
    document = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": producer, "version": "1.0.0", "rules": rules or []}},
                "results": results,
            }
        ],
    }
    return json.dumps(document).encode()
