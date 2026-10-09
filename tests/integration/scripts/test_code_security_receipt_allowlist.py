"""A public corpus checksum exception is exact; it never disables secret detection for a path."""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_public_input_checksum_is_not_a_broad_secret_rule_exception() -> None:
    relative = "rule-catalog/code-security/evaluation/managed-verifiers-1.6.0.json"
    receipt = json.loads((_ROOT / relative).read_text())
    checksum = receipt["labeled_source_inputs"]["dvcsharp-api"]
    assert re.fullmatch(r"[0-9a-f]{64}", checksum)
    expected = "c393cbbd4ee6c0bc86d9332ec169076e16ec70d6:" + relative + ":generic-api-key:132"
    entries = [
        line
        for line in (_ROOT / ".gitleaksignore").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    matching = [entry for entry in entries if relative in entry]
    assert matching == [expected]
    assert all("*" not in entry for entry in matching)
