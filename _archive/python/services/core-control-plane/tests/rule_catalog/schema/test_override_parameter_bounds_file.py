"""The shipped rule-catalog/override-parameter-bounds.yaml parses and is empty by default."""

from __future__ import annotations

from pathlib import Path

import yaml
from fdai.rule_catalog.schema.parameter_relaxation_policy import (
    parameter_relaxation_policies_from_mapping,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_POLICY_FILE = _REPO_ROOT / "rule-catalog" / "override-parameter-bounds.yaml"


def test_shipped_policy_file_exists() -> None:
    assert _POLICY_FILE.is_file()


def test_shipped_policy_file_parses_and_is_empty_by_default() -> None:
    with _POLICY_FILE.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    policies = parameter_relaxation_policies_from_mapping(raw)
    # The upstream distribution intentionally ships no relaxable rule - a
    # parameter-relaxation override is rejected everywhere until a reviewer
    # adds a policy entry.
    assert policies == {}
