"""The Rule revision lock blocks in-place changes to shipped Rules."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-rule-revision-lock.py"
    spec = importlib.util.spec_from_file_location("check_rule_revision_lock", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_rule(tmp_path: Path, rule_id: str) -> tuple[Path, Path]:
    source = REPO_ROOT / "rule-catalog/catalog" / f"{rule_id}.yaml"
    target = tmp_path / "rule-catalog/catalog" / source.name
    target.parent.mkdir(parents=True)
    shutil.copy(source, target)
    reference = next(
        line.split(":", 1)[1].strip()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("reference:")
    )
    policy = tmp_path / reference
    policy.parent.mkdir(parents=True)
    shutil.copy(REPO_ROOT / reference, policy)
    return target, policy


def test_shipped_catalog_matches_the_lock() -> None:
    module = _load_module()
    locked = module.json.loads(module.LOCK.read_text(encoding="utf-8"))["rules"]

    assert module.violations(locked, module.current_entries()) == []


def test_definition_policy_version_and_removal_changes_are_rejected(tmp_path: Path) -> None:
    module = _load_module()
    rule_id = "network.nsg.no-inbound-any-ssh"
    definition, policy = _copy_rule(tmp_path, rule_id)
    locked = module.current_entries(tmp_path)

    policy.write_text(policy.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    assert module.violations(locked, module.current_entries(tmp_path)) == [
        f"{rule_id}: policy_digest changed from the locked revision"
    ]

    text = definition.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.1.0", 1)
    definition.write_text(text, encoding="utf-8")
    problems = module.violations(locked, module.current_entries(tmp_path))
    assert f"{rule_id}: version changed from the locked revision" in problems
    assert f"{rule_id}: definition_digest changed from the locked revision" in problems

    definition.unlink()
    assert module.violations(locked, module.current_entries(tmp_path)) == [
        f"{rule_id}: locked Rule was removed; deprecate it instead"
    ]


def test_new_rules_must_be_locked(tmp_path: Path) -> None:
    module = _load_module()
    _copy_rule(tmp_path, "network.nsg.no-inbound-any-ssh")

    assert module.violations({}, module.current_entries(tmp_path)) == [
        "network.nsg.no-inbound-any-ssh: new Rule is not locked; run with --write"
    ]
