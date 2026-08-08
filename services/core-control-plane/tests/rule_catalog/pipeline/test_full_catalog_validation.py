"""Full-catalog schema validation.

The existing ``test_collect.py`` samples a handful of imported YAML
files to prove the parser and writer produced schema-valid rules.
That sample is not enough for the collected trees we now ship
(thousands of files under ``rule-catalog/collected/**``) - one
regression in the collector CLI could land thousands of rules that
each individually pass the sample but violate the schema on some
edge-case field.

This test walks EVERY YAML under ``rule-catalog/collected/`` and
``rule-catalog/catalog/`` and validates it against the shipped rule
schema. It is intentionally opinionated:

* Runs schema validation from a single compiled validator (cheap
  even on 8000+ files - measured ~2 s locally).
* Fails on the first violation with the file path and the JSON
  Pointer to the offending field so a maintainer can jump straight
  to the bad file.
* Also asserts every rule id is globally unique across the catalog
  and collected trees (a duplicate id silently overwrites the
  previous entry in every downstream loader we ship).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[5]
CATALOG_DIRS = [
    REPO_ROOT / "rule-catalog" / "catalog",
    REPO_ROOT / "rule-catalog" / "collected",
]
SCHEMA_PATH = (
    REPO_ROOT
    / "services"
    / "core-control-plane"
    / "src"
    / "fdai"
    / "shared"
    / "contracts"
    / "rule"
    / "schema.json"
)


def _load_yaml(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    if hasattr(yaml, "CSafeLoader"):
        return yaml.load(text, Loader=yaml.CSafeLoader)
    return yaml.safe_load(text)


def _iter_rule_files() -> list[Path]:
    files: list[Path] = []
    for root in CATALOG_DIRS:
        if not root.is_dir():
            continue
        files.extend(sorted(root.rglob("*.yaml")))
    return files


@pytest.fixture(scope="module")
def loaded_rules() -> tuple[tuple[Path, object], ...]:
    return tuple((path, _load_yaml(path)) for path in _iter_rule_files())


def test_shipped_rule_catalog_contract(
    loaded_rules: tuple[tuple[Path, object], ...],
) -> None:
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert loaded_rules, "expected at least one rule YAML to exist"
    failures: list[str] = []
    checked = 0
    for path, data in loaded_rules:
        if data is None:
            continue
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            where = ".".join(str(p) for p in first.absolute_path) or "<root>"
            failures.append(f"{path.relative_to(REPO_ROOT)}: {where}: {first.message}")
            if len(failures) >= 5:
                break
        checked += 1
    assert not failures, "rule schema violations:\n" + "\n".join(failures)
    # Sanity: we expect thousands of imports now, not just the hand-authored 55.
    assert checked >= 1000, f"only {checked} rule files were validated"
    id_counter: Counter[str] = Counter()
    for _path, data in loaded_rules:
        if isinstance(data, dict) and "id" in data:
            id_counter[str(data["id"])] += 1
    duplicates = {k: v for k, v in id_counter.items() if v > 1}
    assert not duplicates, f"duplicate rule ids across catalog: {duplicates}"
