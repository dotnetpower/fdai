"""Shared builders for code-security finding tests (synthetic, customer-agnostic data)."""

from __future__ import annotations

import json
import os
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


def write_signing_key(path: Path) -> Path:
    """Write a fresh owner-only Ed25519 PEM private key for signing tests."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    pem = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)
    return path
