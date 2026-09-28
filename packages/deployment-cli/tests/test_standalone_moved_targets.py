from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_stage_targets

_CONFIG = """
moved {
  from = azurerm_role_assignment.inventory_cost_reader
  to   = azurerm_role_assignment.inventory_cost_reader[0]
}

moved {
  from = module.read_api
  to   = module.operator_api
}
"""


def _state(monkeypatch: pytest.MonkeyPatch, *, returncode: int, addresses: list[str]) -> None:
    monkeypatch.setattr(
        standalone_stage_targets.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=returncode, stdout="\n".join(addresses)
        ),
    )


def test_moved_destinations_are_added_only_for_sources_in_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "main.tf").write_text(_CONFIG, encoding="utf-8")
    _state(
        monkeypatch,
        returncode=0,
        addresses=["azurerm_role_assignment.inventory_cost_reader", "module.network[0].x.y"],
    )

    targets = standalone_stage_targets.stage_targets(
        "substrate",
        {
            "infra": str(tmp_path),
            "runtime_profile": {"runtime_platform": "aks", "database_placement": "postgres-flex"},
        },
    )

    assert "azurerm_role_assignment.inventory_cost_reader[0]" in targets
    assert "azurerm_role_assignment.inventory_cost_reader" in targets
    assert "module.operator_api" not in targets
    assert targets.count("azurerm_role_assignment.inventory_cost_reader[0]") == 1


def test_module_sources_match_their_nested_addresses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "main.tf").write_text(_CONFIG, encoding="utf-8")
    _state(monkeypatch, returncode=0, addresses=["module.read_api.azurerm_container_app.x"])

    assert standalone_stage_targets.moved_state_targets(tmp_path) == (
        "module.operator_api",
        "module.read_api",
    )


def test_unreadable_state_adds_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "main.tf").write_text(_CONFIG, encoding="utf-8")
    _state(monkeypatch, returncode=1, addresses=[])

    assert standalone_stage_targets.moved_state_targets(tmp_path) == ()


def test_untargeted_stages_stay_untargeted(tmp_path: Path) -> None:
    assert standalone_stage_targets.stage_targets("runtime", {"infra": str(tmp_path)}) == ()
