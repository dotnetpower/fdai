"""Keep a proven historical public-prose exception exact and source scanning enabled."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OWNER = "docs/roadmap/deployment/hub-managed-lifecycle-self-upgrade.md"
PUBLISHED_HEAD = "a61f9e6d059a92e96e4aaa2ada1a1ea63726fefc"


def test_historical_public_prose_exception_is_exact_and_not_a_path_exemption() -> None:
    expected = ":".join((PUBLISHED_HEAD, OWNER, "generic-api-key", "83"))
    entries = {
        line.strip()
        for line in (ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert expected in entries
    assert {entry for entry in entries if f":{OWNER}:" in entry} == {expected}
    assert not any(character in expected for character in ("*", "?", "["))
    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert config["extend"]["useDefault"] is True
    assert not any(re.search(pattern, OWNER) for pattern in config["allowlist"]["paths"])
    assert "/".join(("enrollment", "key", "scope")) not in (ROOT / OWNER).read_text(
        encoding="utf-8"
    )
