"""The historical scanner exception identifies a public Python symbol, never key material."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def test_signing_type_exception_is_exact_and_defaults_remain_enabled() -> None:
    root = Path(__file__).resolve().parents[3]
    config = tomllib.loads((root / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert config["extend"]["useDefault"] is True
    pattern = next(
        value for value in config["allowlist"]["regexes"] if "Ed25519PrivateKey" in value
    )
    assert pattern == "^Ed25519PrivateKey$"
    assert re.fullmatch(pattern, "Ed25519PrivateKey") is not None
    for candidate in (
        "prefix-Ed25519PrivateKey",
        "Ed25519PrivateKey-suffix",
        "synthetic-secret-value",
    ):
        assert re.fullmatch(pattern, candidate) is None
    assert not any("cloud_knowledge" in value for value in config["allowlist"]["paths"])
