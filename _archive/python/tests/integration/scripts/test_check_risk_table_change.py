from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-risk-table-change.py"
    spec = importlib.util.spec_from_file_location("check_risk_table_change", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table(
    *,
    version: str = "1.0.0",
    owner_group: str = "aw-owners",
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if rules is None:
        rules = [
            {
                "id": "deny-policy",
                "if": {"policy_violation": True},
                "decision": "deny",
                "reason": "r",
            },
            {
                "id": "hil-destructive",
                "if": {"destructive": True},
                "decision": "hil",
                "reason": "r",
            },
            {"id": "auto-low", "if": {"reversible": True}, "decision": "auto", "reason": "r"},
            {"id": "default-hil", "default": "hil", "reason": "fail toward safety"},
        ]
    return {"version": version, "owner_group": owner_group, "rules": rules}


class TestMetadataContract:
    def test_the_shipped_table_satisfies_the_contract(self) -> None:
        import yaml

        module = _load_module()
        raw = yaml.safe_load(
            (REPO_ROOT / "rule-catalog/risk-classification.yaml").read_text(encoding="utf-8")
        )

        assert module.metadata_violations(raw) == []

    def test_a_representative_table_is_accepted(self) -> None:
        module = _load_module()

        assert module.metadata_violations(_table()) == []

    def test_a_rule_without_a_written_justification_is_rejected(self) -> None:
        module = _load_module()
        table = _table()
        table["rules"][1]["reason"] = "   "

        errors = module.metadata_violations(table)

        assert any("non-empty reason" in error for error in errors)

    def test_a_repeated_rule_id_is_rejected(self) -> None:
        module = _load_module()
        table = _table()
        table["rules"][2]["id"] = "deny-policy"

        errors = module.metadata_violations(table)

        assert any("repeats rule id 'deny-policy'" in error for error in errors)

    def test_a_non_semver_version_is_rejected(self) -> None:
        module = _load_module()

        errors = module.metadata_violations(_table(version="1.0"))

        assert "version must be a MAJOR.MINOR.PATCH string" in errors

    def test_an_empty_owner_group_is_rejected(self) -> None:
        module = _load_module()

        errors = module.metadata_violations(_table(owner_group="  "))

        assert "owner_group must be a non-empty string" in errors

    def test_a_default_that_does_not_fail_close_is_rejected(self) -> None:
        module = _load_module()
        table = _table()
        table["rules"][3]["default"] = "auto"

        errors = module.metadata_violations(table)

        assert any("fail close to hil or deny" in error for error in errors)

    def test_a_missing_default_entry_is_rejected(self) -> None:
        module = _load_module()
        table = _table()
        table["rules"] = table["rules"][:3]

        errors = module.metadata_violations(table)

        assert "table must carry exactly one fail-close default entry" in errors

    def test_a_default_that_is_not_last_is_rejected(self) -> None:
        module = _load_module()
        table = _table()
        table["rules"].append(
            {"id": "auto-extra", "if": {"reversible": True}, "decision": "auto", "reason": "r"}
        )

        errors = module.metadata_violations(table)

        assert "the fail-close default entry must be the last rule" in errors

    def test_a_rule_setting_both_decision_and_default_is_rejected(self) -> None:
        module = _load_module()
        table = _table()
        table["rules"][3]["decision"] = "hil"

        errors = module.metadata_violations(table)

        assert any("either decision or default" in error for error in errors)


class TestChangeDirection:
    def test_an_identical_table_is_neutral(self) -> None:
        module = _load_module()

        assert module.change_direction(_table(), _table()) == "neutral"

    def test_widening_a_rule_to_auto_is_loosening(self) -> None:
        module = _load_module()
        current = _table(version="1.1.0")
        current["rules"][1]["decision"] = "auto"

        assert module.change_direction(_table(), current) == "loosening"

    def test_dropping_a_deny_rule_is_loosening(self) -> None:
        module = _load_module()
        current = _table(version="1.1.0")
        current["rules"] = current["rules"][1:]

        assert module.change_direction(_table(), current) == "loosening"

    def test_lowering_a_quorum_is_loosening(self) -> None:
        module = _load_module()
        previous = _table()
        previous["rules"][1]["quorum"] = 2
        current = _table(version="1.1.0")

        assert module.change_direction(previous, current) == "loosening"

    def test_editing_a_match_condition_is_treated_as_loosening(self) -> None:
        module = _load_module()
        current = _table(version="1.1.0")
        current["rules"][2]["if"] = {"reversible": True, "environment": "dev"}

        assert module.change_direction(_table(), current) == "loosening"

    def test_reordering_rules_is_treated_as_loosening(self) -> None:
        module = _load_module()
        current = _table(version="1.1.0")
        current["rules"][0], current["rules"][1] = current["rules"][1], current["rules"][0]

        assert module.change_direction(_table(), current) == "loosening"

    def test_adding_a_deny_rule_is_tightening(self) -> None:
        module = _load_module()
        current = _table(version="1.0.1")
        current["rules"].insert(
            0, {"id": "deny-new", "if": {"graph_stale": True}, "decision": "deny", "reason": "r"}
        )

        assert module.change_direction(_table(), current) == "tightening"

    def test_moving_auto_to_hil_is_tightening(self) -> None:
        module = _load_module()
        current = _table(version="1.0.1")
        current["rules"][2]["decision"] = "hil"

        assert module.change_direction(_table(), current) == "tightening"

    def test_rewording_a_justification_alone_is_neutral(self) -> None:
        module = _load_module()
        current = _table(version="1.0.1")
        current["rules"][1]["reason"] = "delete/drop/purge always requires an approver"

        assert module.change_direction(_table(), current) == "neutral"


class TestChangeContract:
    def test_a_tightening_patch_bump_is_accepted(self) -> None:
        module = _load_module()
        current = _table(version="1.0.1")
        current["rules"][2]["decision"] = "hil"

        assert module.change_violations(_table(), current) == []

    def test_a_change_without_a_version_bump_is_rejected(self) -> None:
        module = _load_module()
        current = _table()
        current["rules"][2]["decision"] = "hil"

        errors = module.change_violations(_table(), current)

        assert any("version must increase on every change" in error for error in errors)

    def test_a_version_rollback_is_rejected(self) -> None:
        module = _load_module()

        errors = module.change_violations(_table(version="1.2.0"), _table(version="1.1.9"))

        assert any("version must increase on every change" in error for error in errors)

    def test_rehoming_ownership_is_rejected(self) -> None:
        module = _load_module()

        errors = module.change_violations(
            _table(), _table(version="1.0.1", owner_group="aw-operators")
        )

        assert any("owner_group must not change" in error for error in errors)

    def test_a_loosening_change_hiding_behind_a_patch_bump_is_rejected(self) -> None:
        module = _load_module()
        current = _table(version="1.0.1")
        current["rules"][1]["decision"] = "auto"

        errors = module.change_violations(_table(), current)

        assert any("must bump at least the minor version" in error for error in errors)

    def test_a_loosening_change_with_a_minor_bump_is_accepted(self) -> None:
        module = _load_module()
        current = _table(version="1.1.0")
        current["rules"][1]["decision"] = "auto"

        assert module.change_violations(_table(), current) == []

    def test_a_loosening_change_with_a_major_bump_is_accepted(self) -> None:
        module = _load_module()
        current = _table(version="2.0.0")
        current["rules"][1]["decision"] = "auto"

        assert module.change_violations(_table(), current) == []
