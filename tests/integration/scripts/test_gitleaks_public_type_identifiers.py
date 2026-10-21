"""Exact public Python type labels are not credential material or path exemptions."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("label", ["Ed25519PrivateKey", "X25519PrivateKey"])
def test_public_key_types_have_exact_value_exceptions_only(label: str) -> None:
    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert config["extend"]["useDefault"] is True
    exceptions = [
        re.compile(pattern) for pattern in config["allowlist"]["regexes"] if label in pattern
    ]
    assert len(exceptions) == 1
    exception = exceptions[0]
    assert exception.pattern == f"^{label}$"
    assert exception.search(label) is not None
    for value in (f"prefix{label}", f"{label}suffix", f"{label}=not-a-type", "opaque-value"):
        assert exception.search(value) is None
    assert not any(
        re.search(pattern, path)
        for pattern in config["allowlist"]["paths"]
        for path in (
            "packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_package.py",
            "packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_sealing.py",
        )
    )
