from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_application, standalone_host
from fdai_deployment_cli.contracts import canonical_digest


def _review() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": "substrate",
        "plan_digest": "a" * 64,
        "target_binding": "b" * 64,
        "source_commit": "c" * 40,
        "summary": {"action_counts": {"create": 1}},
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    value["review_digest"] = canonical_digest(value)
    return value


def _context(review: dict[str, object]) -> dict[str, object]:
    return {
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
    }


def test_standalone_plan_summary_counts_replacements_once() -> None:
    result = standalone_host._plan_summary(
        {
            "resource_changes": [
                {
                    "address": "azurerm_resource_group.main",
                    "type": "azurerm_resource_group",
                    "change": {"actions": ["create"]},
                },
                {
                    "address": "azurerm_linux_virtual_machine.runner",
                    "type": "azurerm_linux_virtual_machine",
                    "change": {"actions": ["delete", "create"]},
                },
                {
                    "address": "azurerm_container_app.core",
                    "type": "azurerm_container_app",
                    "change": {"actions": ["update"]},
                },
            ]
        }
    )

    assert result["action_counts"] == {
        "create": 1,
        "update": 1,
        "delete": 0,
        "replace": 1,
        "read": 0,
        "no-op": 0,
    }
    assert result["resource_type_counts"] == {
        "azurerm_container_app": 1,
        "azurerm_linux_virtual_machine": 1,
        "azurerm_resource_group": 1,
    }
    assert result["resource_changes"] == [
        {"address": "azurerm_resource_group.main", "actions": ["create"]},
        {
            "address": "azurerm_linux_virtual_machine.runner",
            "actions": ["delete", "create"],
        },
        {"address": "azurerm_container_app.core", "actions": ["update"]},
    ]


def test_standalone_apply_requires_exact_unexpired_approval() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    }

    standalone_host._validate_approval(review, approval, context=_context(review))

    approval["plan_digest"] = "e" * 64
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))


def test_standalone_apply_rejects_expired_approval() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    }

    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))


def test_standalone_apply_rejects_tampered_review_and_context() -> None:
    review = _review()
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": review["stage"],
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": "d" * 64,
        "approved_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    }
    review["summary"] = {"action_counts": {"delete": 1}}
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(review, approval, context=_context(review))

    review = _review()
    approval["review_digest"] = review["review_digest"]
    approval["plan_digest"] = review["plan_digest"]
    approval["target_binding"] = review["target_binding"]
    with pytest.raises(ValueError, match="invalid or expired"):
        standalone_host._validate_approval(
            review,
            approval,
            context={**_context(review), "target_binding": "e" * 64},
        )


def test_remote_preparation_uses_only_fixed_argument_commands(tmp_path: Path) -> None:
    class Tunnel:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []

        def ssh(self, command: tuple[str, ...], *, timeout: int):
            del timeout
            self.commands.append(command)
            stdout = "a" * 64 + "  kit.tar.gz\n" if command[0] == "sha256sum" else ""
            return SimpleNamespace(returncode=0, stdout=stdout)

        def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
            del source, destination, timeout

    tunnel = Tunnel()
    inputs = []
    for name in ("archive", "handoff", "entra"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        inputs.append(path)
    standalone_application._prepare_remote(
        tunnel,
        remote_root="/home/fdai/.fdai-transfer-abc",
        remote_archive="/home/fdai/.fdai-transfer-abc/kit.tar.gz",
        archive=inputs[0],
        archive_digest="a" * 64,
        handoff_path=inputs[1],
        remote_handoff="/home/fdai/.fdai-transfer-abc/handoff.json",
        entra_path=inputs[2],
        remote_entra="/home/fdai/.fdai-transfer-abc/entra.json",
        app_work="/home/fdai/.fdai-transfer-abc/application",
        timeout_seconds=1800,
    )

    assert all(command[0] not in {"bash", "sh"} for command in tunnel.commands)
    assert any(command[:3] == ("python3", "-m", "venv") for command in tunnel.commands)
    assert tunnel.commands[-1][1:3] == ("-m", "fdai_deployment_cli.standalone_host")
