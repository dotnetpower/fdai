from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.deployment.azure.verify_a3e_evidence_plan import (
    EXPECTED_CREATES,
    PlanVerificationError,
    main,
    verify_plan,
)


def _plan() -> dict[str, object]:
    return {
        "resource_changes": [
            {
                "address": address,
                "mode": "managed",
                "change": {"actions": ["create"]},
            }
            for address in sorted(EXPECTED_CREATES)
        ]
    }


def test_verify_plan_accepts_only_the_exact_create_set() -> None:
    verify_plan(_plan())


@pytest.mark.parametrize("actions", [["update"], ["delete", "create"], ["delete"]])
def test_verify_plan_rejects_non_create_actions(actions: list[str]) -> None:
    plan = _plan()
    resource_changes = plan["resource_changes"]
    assert isinstance(resource_changes, list)
    resource_changes[0]["change"]["actions"] = actions

    with pytest.raises(PlanVerificationError, match="only create actions"):
        verify_plan(plan)


def test_verify_plan_rejects_missing_and_unreviewed_addresses() -> None:
    missing = _plan()
    missing_changes = missing["resource_changes"]
    assert isinstance(missing_changes, list)
    missing_changes.pop()
    with pytest.raises(PlanVerificationError, match="omits"):
        verify_plan(missing)

    extra = _plan()
    extra_changes = extra["resource_changes"]
    assert isinstance(extra_changes, list)
    extra_changes.append(
        {
            "address": "azurerm_public_ip.unreviewed",
            "change": {"actions": ["create"]},
        }
    )
    with pytest.raises(PlanVerificationError, match="unreviewed"):
        verify_plan(extra)


def test_main_reports_only_value_free_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")

    assert main([str(plan_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "A3E_EVIDENCE_PLAN_OK create=12 update=0 delete=0\n"
    assert captured.err == ""


def test_main_fails_closed_for_malformed_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("not-json", encoding="utf-8")

    assert main([str(plan_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("A3E_EVIDENCE_PLAN_BLOCKED reason=")
