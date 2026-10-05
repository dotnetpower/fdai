"""Tests for the reviewable refresh-only drift summary and digest."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _ROOT / "scripts" / "deployment" / "service"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "refresh_drift_digest", _SCRIPTS / "refresh_drift_digest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


digest_module = _load()


def _plan(**overrides: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "resource_drift": [
            {
                "address": "module.state_store.azurerm_postgresql_flexible_server.primary",
                "change": {
                    "actions": ["update"],
                    "before": {"sku_name": "B_Standard_B1ms", "administrator_password": "s1"},
                    "after": {"sku_name": "B_Standard_B4ms", "administrator_password": "s1"},
                },
            },
            {
                "address": "azurerm_private_dns_zone.unchanged",
                "change": {"actions": ["no-op"], "before": {}, "after": {}},
            },
        ],
        "resource_changes": [
            {
                "address": "module.identity_change[0].azurerm_user_assigned_identity.primary",
                "previous_address": "module.identity_change.azurerm_user_assigned_identity.primary",
                "change": {"actions": ["no-op"]},
            }
        ],
        "output_changes": {
            "service": {"actions": ["update"], "before": {"rev": "a"}, "after": {"rev": "b"}},
            "stable": {"actions": ["no-op"], "before": 1, "after": 1},
        },
    }
    plan.update(overrides)
    return plan


def test_summary_names_paths_moves_and_outputs_without_values() -> None:
    summary = digest_module.summarize(_plan(), root_id="legacy")

    assert summary["root_id"] == "legacy"
    [drift] = summary["resource_drift"]
    assert [change["path"] for change in drift["changes"]] == ["sku_name"]
    assert summary["moves"] == [
        {
            "from": "module.identity_change.azurerm_user_assigned_identity.primary",
            "to": "module.identity_change[0].azurerm_user_assigned_identity.primary",
        }
    ]
    assert [output["name"] for output in summary["output_changes"]] == ["service"]
    rendered = digest_module.render([summary])
    assert "sku_name" in rendered
    assert "B_Standard_B4ms" not in json.dumps(summary)
    assert "B_Standard_B4ms" not in rendered
    assert digest_module.has_drift(summary) is True


def test_digest_binds_exact_values_not_only_paths() -> None:
    reviewed = digest_module.summarize(_plan(), root_id="legacy")
    changed = _plan()
    changed["resource_drift"][0]["change"]["after"]["sku_name"] = "B_Standard_B8ms"
    different = digest_module.summarize(changed, root_id="legacy")

    assert digest_module.aggregate_digest([reviewed]) != digest_module.aggregate_digest([different])


def test_digest_is_order_independent_and_rejects_duplicate_roots() -> None:
    first = digest_module.summarize(_plan(), root_id="a")
    second = digest_module.summarize(_plan(resource_drift=[]), root_id="b")

    assert digest_module.aggregate_digest([first, second]) == digest_module.aggregate_digest(
        [second, first]
    )
    with pytest.raises(digest_module.RefreshDriftError, match="duplicate root"):
        digest_module.aggregate_digest([first, first])


@pytest.mark.parametrize("actions", [["update"], ["create"], ["delete"], ["delete", "create"]])
def test_only_refresh_only_plans_are_summarized(actions: list[str]) -> None:
    plan = _plan(
        resource_changes=[{"address": "azurerm_resource_group.app", "change": {"actions": actions}}]
    )

    with pytest.raises(digest_module.RefreshDriftError, match="only refresh-only plans"):
        digest_module.summarize(plan, root_id="legacy")


def test_clean_plan_has_no_drift() -> None:
    summary = digest_module.summarize(
        {"resource_drift": [], "resource_changes": [], "output_changes": {}}, root_id="bootstrap"
    )

    assert digest_module.has_drift(summary) is False
    assert digest_module.render([summary]) == "bootstrap: no drift"


def test_cli_summarizes_digests_and_reports_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_plan()), encoding="utf-8")
    assert digest_module.main(["summarize", "--root-id", "legacy", "--plan-json", str(plan)]) == 0
    summary = tmp_path / "legacy.json"
    summary.write_text(capsys.readouterr().out, encoding="utf-8")

    assert digest_module.main(["digest", str(summary)]) == 0
    assert capsys.readouterr().out.strip().startswith("sha256:")
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert digest_module.main(["digest", str(bad)]) == 1
